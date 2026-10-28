"""Evaluate verifiers as classifiers on the patch dataset, and as selectors over the no-network candidate pool."""

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

import typer

POOL = ["baseline_nonet", "self_check", "review_first"]


def auroc(pos: list[float], neg: list[float]) -> float:
    return mean((p > n) + 0.5 * (p == n) for p in pos for n in neg)


def pick(cands: list[dict], key) -> float:
    """Expected resolve of picking the max-key candidate, ties broken uniformly at random."""
    best = max(map(key, cands))
    return mean(c["resolved"] for c in cands if key(c) == best)


def agentic_reviewer(run_dir: Path, rows: list[dict]):
    first = {r["instance_id"]: r["resolved"] for r in rows if "review_first" in r["sources"]}
    counts = Counter()
    for traj in sorted(run_dir.glob("*/*.traj.json")):
        review = json.loads(traj.read_text())["info"]["reviews"][0]
        verdict = "no verdict" if review["exit_status"] != "Submitted" else "PASS" if review["passed"] else "FAIL"
        counts[(verdict, "correct" if first[traj.parent.name] else "wrong")] += 1
    print("\n## Agentic reviewer (review run, first submissions)")
    for verdict in ["PASS", "FAIL", "no verdict"]:
        print(
            f"{verdict:>10}: on correct patch {counts[(verdict, 'correct')]:2}, on wrong patch {counts[(verdict, 'wrong')]:2}"
        )


def poisson_binomial_tail(ps: list[float], k: int) -> float:
    """P(at least k successes) for independent trials with success probabilities ps."""
    dist = [1.0]
    for p in ps:
        dist = [a * (1 - p) + b * p for a, b in zip(dist + [0], [0] + dist)]
    return sum(dist[k:])


def classifier(rows: list[dict], score: dict[int, float], name: str):
    print(f"\n## {name} as classifier")
    rows = [r for r in rows if r["id"] in score]
    for subset, rs in [("all", rows), ("no-network only", [r for r in rows if not r["leaked_only"]])]:
        pos, neg = [score[r["id"]] for r in rs if r["resolved"]], [score[r["id"]] for r in rs if not r["resolved"]]
        flagged = [r for r in rs if score[r["id"]] < 50]
        print(
            f"{subset}: n={len(rs)} ({len(neg)} wrong)  AUROC {auroc(pos, neg):.3f}  "
            f"reject(score<50): {len(flagged)}, of which wrong {sum(not r['resolved'] for r in flagged)}"
        )
    # a judge can score well across instances just by spotting hard issues; selection needs within-instance ranking
    inst = defaultdict(list)
    for r in rows:
        inst[r["instance_id"]].append(score[r["id"]])
    print(
        f"AUROC from per-instance mean score only (no patch information): "
        f"{auroc(*[[mean(inst[r['instance_id']]) for r in rows if r['resolved'] == label] for label in (True, False)]):.3f}"
    )
    pairs = [
        (score[p["id"]], score[n["id"]])
        for p in rows
        if p["resolved"]
        for n in rows
        if not n["resolved"] and n["instance_id"] == p["instance_id"]
    ]
    print(
        f"within-instance AUROC (correct vs wrong patch of the same issue): "
        f"{mean((p > n) + 0.5 * (p == n) for p, n in pairs):.3f} over {len(pairs)} pairs"
    )


def main(
    data: Path = Path("runs/verifier/patches.jsonl"),
    pointwise: Path = Path("runs/verifier/pointwise.jsonl"),
    listwise: Path = Path("runs/verifier/listwise.jsonl"),
    review_run: Path = Path("runs/review"),
):
    rows = [json.loads(l) for l in data.read_text().splitlines()]
    agentic_reviewer(review_run, rows)

    samples = defaultdict(list)
    for r in map(json.loads, pointwise.read_text().splitlines() if pointwise.exists() else []):
        if r["score"] is not None:
            samples[r["id"]].append(r["score"])
    score = {i: mean(s) for i, s in samples.items()}
    if score:
        classifier(rows, score, f"Pointwise judge (mean of {max(map(len, samples.values()))} samples)")

    listwise_picks = defaultdict(list)
    for r in map(json.loads, listwise.read_text().splitlines() if listwise.exists() else []):
        if r["best"] is not None:
            listwise_picks[r["key"].split("/")[0]].append(r["best"])

    pools = defaultdict(list)
    for r in rows:
        if votes := sum(s in POOL for s in r["sources"]):
            pools[r["instance_id"]].append(r | {"votes": votes})
    by_id = {r["id"]: r for r in rows}

    def pass1(cs: list[dict]) -> float:
        return sum(c["resolved"] * c["votes"] for c in cs) / sum(c["votes"] for c in cs)

    def one_call(cs: list[dict]) -> float:
        picks = listwise_picks[cs[0]["instance_id"]]
        return mean(by_id[b]["resolved"] for b in picks) if picks else pass1(cs)

    methods = {
        "pass@1 (random candidate)": pass1,
        "majority vote": lambda cs: pick(cs, lambda c: c["votes"]),
        "pointwise judge": lambda cs: pick(cs, lambda c: score.get(c["id"], 0)),
        "majority, ties by pointwise": lambda cs: pick(cs, lambda c: (c["votes"], score.get(c["id"], 0))),
        "listwise judge (1 call)": one_call,
        "listwise judge (vote of calls)": lambda cs: pick(
            cs, lambda c: listwise_picks[c["instance_id"]].count(c["id"])
        ),
        "oracle (pass@3)": lambda cs: max(c["resolved"] for c in cs),
    }
    mixed = sorted(iid for iid, cs in pools.items() if len({c["resolved"] for c in cs}) > 1)
    print(
        f"\n## Selection over {len(POOL)} no-network runs ({len(pools)} instances, {len(mixed)} with mixed candidates)"
    )
    for run in POOL:
        print(f"{run:>30}: {sum(c['resolved'] for cs in pools.values() for c in cs if run in c['sources']):5.1f}")
    for name, method in methods.items():
        print(
            f"{name:>30}: {sum(map(method, pools.values())):5.1f}   on mixed: {sum(method(pools[i]) for i in mixed):4.1f}/{len(mixed)}"
        )
    calls = [(pass1(pools[iid]), by_id[b]["resolved"]) for iid in mixed for b in listwise_picks[iid]]
    if calls:
        k = sum(ok for _, ok in calls)
        print(
            f"listwise calls on mixed instances: {k}/{len(calls)} picked a correct patch "
            f"(random: {sum(p for p, _ in calls):.1f}), one-sided p = {poisson_binomial_tail([p for p, _ in calls], k):.3f}"
        )


if __name__ == "__main__":
    typer.run(main)
