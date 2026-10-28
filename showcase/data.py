"""Load experiment results from runs/ for the showcase site. Every number shown on the site is computed here."""

import json
from collections import defaultdict
from functools import cache
from pathlib import Path
from statistics import mean

import yaml

CONTENT = yaml.safe_load((Path(__file__).parent / "content.yaml").read_text(encoding="utf-8"))
POOL = ["baseline_nonet", "self_check", "review_first"]
"""Candidate pool for selection: one patch per no-network run, before any reviewer intervention."""


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def tests(runs: Path, key: str, iid: str) -> dict | None:
    report = next((runs / "eval/logs/run_evaluation" / key).glob(f"*/{iid}/report.json"), None)
    if not report:
        return None
    status = read_json(report)[iid].get("tests_status", {})
    return {
        name: {
            "passed": len(status.get(name, {}).get("success", [])),
            "failed": status.get(name, {}).get("failure", []),
        }
        for name in ("FAIL_TO_PASS", "PASS_TO_PASS")
    }


def traj_stats(path: Path) -> dict:
    if not path.exists():
        return {}
    info = (data := read_json(path))["info"]
    reviews = info.get("reviews", [])
    assistant = [m for m in data["messages"] + [m for r in reviews for m in r["messages"]] if m["role"] == "assistant"]
    return {
        "steps": info["model_stats"]["api_calls"],
        "review_steps": sum(r["n_calls"] for r in reviews),
        "prompt_tokens": sum(
            (m.get("extra", {}).get("response", {}).get("usage") or {}).get("prompt_tokens") or 0 for m in assistant
        ),
        "exit_status": info["exit_status"],
        "reviews": [{k: r[k] for k in ("exit_status", "verdict", "passed", "n_calls")} for r in reviews],
        "has_traj": True,
    }


@cache
def load_run(runs: Path, key: str, base: str | None = None) -> dict[str, dict]:
    """Per-instance results of one run; `base` supplies the instances this run did not resubmit."""
    rows = (
        {iid: {k: r[k] for k in ("patch", "resolved", "tests")} for iid, r in load_run(runs, base).items()}
        if base
        else {}
    )
    resolved = set(read_json(next((runs / "eval").glob(f"*.{key}.json")))["resolved_ids"])
    for iid, pred in read_json(runs / key / "preds.json").items():
        rows[iid] = {"patch": pred["model_patch"], "resolved": iid in resolved, "tests": tests(runs, key, iid)}
        rows[iid] |= traj_stats(runs / key / iid / f"{iid}.traj.json")
    return rows


def run_summary(runs: Path) -> list[dict]:
    out = []
    for run in CONTENT["runs"]:
        rows = load_run(runs, run["key"], run.get("base")).values()
        trajs = [r for r in rows if r.get("has_traj")]
        avg = lambda k: mean(r[k] for r in trajs) if trajs else None  # noqa: E731
        out.append(
            run
            | {
                "n": len(rows),
                "resolved": sum(r["resolved"] for r in rows),
                "steps": avg("steps"),
                "review_steps": avg("review_steps"),
                "prompt_tokens": avg("prompt_tokens"),
                "has_traj": bool(trajs),
            }
        )
    return out


def instance_ids(runs: Path) -> list[str]:
    return sorted({iid for run in CONTENT["runs"] for iid in load_run(runs, run["key"], run.get("base"))})


def runs_page(runs: Path) -> dict:
    return {
        "runs": run_summary(runs),
        "instances": [
            {
                "id": iid,
                "failure": CONTENT["failures"].get(iid),
                "results": {
                    run["key"]: load_run(runs, run["key"], run.get("base")).get(iid, {}).get("resolved")
                    for run in CONTENT["runs"]
                },
            }
            for iid in instance_ids(runs)
        ],
    }


def instance(runs: Path, iid: str) -> dict:
    patches = [r for r in read_jsonl(runs / "verifier/patches.jsonl") if r["instance_id"] == iid]
    return {
        "id": iid,
        "issue": patches[0]["issue"] if patches else "",
        "failure": CONTENT["failures"].get(iid),
        "runs": [
            run | load_run(runs, run["key"], run.get("base"))[iid]
            for run in CONTENT["runs"]
            if iid in load_run(runs, run["key"], run.get("base"))
        ],
        "selection": next((i for i in verifier(runs)["instances"] if i["id"] == iid), None),
    }


def simplify(message: dict) -> dict:
    return {
        "role": message["role"],
        "content": message.get("content") or "",
        "reasoning": message.get("reasoning_content") or "",
        "commands": [a["command"] for a in message.get("extra", {}).get("actions", [])],
    }


def trajectory(runs: Path, key: str, iid: str) -> dict:
    data = read_json(runs / key / iid / f"{iid}.traj.json")
    return {
        "messages": [simplify(m) for m in data["messages"]],
        "reviews": [
            {"verdict": r["verdict"], "passed": r["passed"], "messages": [simplify(m) for m in r["messages"]]}
            for r in data["info"].get("reviews", [])
        ],
    }


def auroc(pos: list[float], neg: list[float]) -> float:
    return mean((p > n) + 0.5 * (p == n) for p in pos for n in neg)


def pick(cands: list[dict], key) -> float:
    """Expected resolve of picking the max-key candidate, ties broken uniformly at random."""
    best = max(map(key, cands))
    return mean(c["resolved"] for c in cands if key(c) == best)


def poisson_binomial_tail(ps: list[float], k: int) -> float:
    dist = [1.0]
    for p in ps:
        dist = [a * (1 - p) + b * p for a, b in zip(dist + [0], [0] + dist)]
    return sum(dist[k:])


@cache
def verifier(runs: Path) -> dict:
    rows = read_jsonl(runs / "verifier/patches.jsonl")
    by_id = {r["id"]: r for r in rows}
    samples = defaultdict(list)
    for r in read_jsonl(runs / "verifier/pointwise.jsonl"):
        if r["score"] is not None:
            samples[r["id"]].append(r["score"])
    score = {i: mean(s) for i, s in samples.items()}
    calls = defaultdict(list)
    for r in read_jsonl(runs / "verifier/listwise.jsonl"):
        if r["best"] is not None:
            calls[r["key"].split("/")[0]].append(r)

    scored = [r | {"score": score[r["id"]]} for r in rows if r["id"] in score]
    inst_mean = {
        iid: mean(r["score"] for r in scored if r["instance_id"] == iid) for iid in {r["instance_id"] for r in scored}
    }
    split = lambda f: [[f(r) for r in scored if r["resolved"] == label] for label in (True, False)]  # noqa: E731
    pairs = [
        (p["score"], n["score"])
        for p in scored
        if p["resolved"]
        for n in scored
        if not n["resolved"] and n["instance_id"] == p["instance_id"]
    ]

    pools = defaultdict(list)
    for r in rows:
        if votes := sum(s in POOL for s in r["sources"]):
            pools[r["instance_id"]].append(
                {
                    "id": r["id"],
                    "instance_id": r["instance_id"],
                    "resolved": r["resolved"],
                    "votes": votes,
                    "score": score.get(r["id"]),
                    "patch": r["patch"],
                }
                | {"picks": sum(c["best"] == r["id"] for c in calls[r["instance_id"]])}
            )

    def pass1(cs: list[dict]) -> float:
        return sum(c["resolved"] * c["votes"] for c in cs) / sum(c["votes"] for c in cs)

    def listwise(cs: list[dict]) -> float:
        picks = calls[cs[0]["instance_id"]]
        return mean(by_id[c["best"]]["resolved"] for c in picks) if picks else pass1(cs)

    methods = {
        "pass1": pass1,
        "majority": lambda cs: pick(cs, lambda c: c["votes"]),
        "pointwise": lambda cs: pick(cs, lambda c: c["score"] or 0),
        "listwise": listwise,
        "oracle": lambda cs: max(c["resolved"] for c in cs),
    }
    mixed = sorted(iid for iid, cs in pools.items() if len({c["resolved"] for c in cs}) > 1)
    listwise_calls = [(pass1(pools[iid]), by_id[c["best"]]["resolved"]) for iid in mixed for c in calls[iid]]
    k = sum(ok for _, ok in listwise_calls)
    return {
        "n_patches": len(rows),
        "n_resolved": sum(r["resolved"] for r in rows),
        "auroc": {
            "global": auroc(*split(lambda r: r["score"])),
            "instance_mean": auroc(*split(lambda r: inst_mean[r["instance_id"]])),
            "within": mean((p > n) + 0.5 * (p == n) for p, n in pairs),
            "pairs": len(pairs),
        },
        "selection": [
            {
                "key": key,
                "label": CONTENT["selection"][key],
                "total": sum(map(f, pools.values())),
                "mixed": sum(f(pools[i]) for i in mixed),
            }
            for key, f in methods.items()
        ],
        "n_mixed": len(mixed),
        "listwise": {
            "correct": k,
            "calls": len(listwise_calls),
            "random": sum(p for p, _ in listwise_calls),
            "p": poisson_binomial_tail([p for p, _ in listwise_calls], k),
        },
        "instances": [{"id": iid, "candidates": pools[iid], "calls": calls[iid]} for iid in mixed],
        "scores": [{"instance": r["instance_id"], "score": r["score"], "resolved": r["resolved"]} for r in scored],
    }
