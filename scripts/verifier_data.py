"""Build a labeled patch dataset (issue, patch, hidden-test label) from finished runs, deduplicated per instance."""

import json
import re
from pathlib import Path

import typer
from datasets import load_dataset

RUNS = {"baseline": "baseline", "baseline_nonet": "baseline_nonet", "self_check": "self_check", "review": "review"}
"""Source name -> run dir / eval run_id. `review_first` (first submissions of the review run) is derived below."""


def normalize(patch: str) -> str:
    return "\n".join(l.rstrip() for l in patch.strip().splitlines() if not re.match(r"index [0-9a-f]+\.\.[0-9a-f]+", l))


def load_run(name: str) -> dict[str, tuple[str, bool]]:
    preds = json.loads(Path(f"runs/{name}/preds.json").read_text())
    resolved = set(json.loads(Path(f"runs/eval/openai__deepseek-v4-pro.{name}.json").read_text())["resolved_ids"])
    return {iid: (p["model_patch"], iid in resolved) for iid, p in preds.items()}


def main(out: Path = Path("runs/verifier/patches.jsonl")):
    sources = {name: load_run(run) for name, run in RUNS.items()}
    sources["review_first"] = sources["review"] | load_run("review_first")
    issues = {
        r["instance_id"]: r["problem_statement"] for r in load_dataset("SWE-bench/SWE-bench_Verified", split="test")
    }
    rows = {}
    for source, preds in sources.items():
        for iid, (patch, label) in preds.items():
            row = rows.setdefault(
                (iid, normalize(patch)), {"instance_id": iid, "patch": patch, "labels": {}, "sources": []}
            )
            row["sources"].append(source)
            row["labels"][source] = label
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for i, row in enumerate(sorted(rows.values(), key=lambda r: r["instance_id"])):
            labels = set(row["labels"].values())
            row |= {
                "id": i,
                "resolved": all(labels),
                "label_conflict": len(labels) > 1,
                "issue": issues[row["instance_id"]],
            }
            row["leaked_only"] = row["sources"] == ["baseline"]
            f.write(json.dumps(row) + "\n")
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    print(
        f"{len(rows)} distinct patches over {len({r['instance_id'] for r in rows})} instances, "
        f"{sum(r['resolved'] for r in rows)} resolved, {sum(r['label_conflict'] for r in rows)} label conflicts, "
        f"{sum(r['leaked_only'] for r in rows)} only from the networked baseline"
    )


if __name__ == "__main__":
    typer.run(main)
