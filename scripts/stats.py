"""Summarize a run directory: resolve rate (from harness report), steps, tokens, exit statuses, DeepSeek artifact counts."""

import json
import re
from collections import Counter
from pathlib import Path

import typer

ARTIFACT_RE = re.compile(r"<ds_safety>|DSML")


def load_traj(path: Path) -> dict:
    data = json.loads(path.read_text())
    review_msgs = [m for r in data["info"].get("reviews", []) for m in r["messages"]]
    assistant = [m for m in data["messages"] + review_msgs if m.get("role") == "assistant"]
    usage = [m.get("extra", {}).get("response", {}).get("usage") or {} for m in assistant]
    return {
        "id": path.parent.name,
        "exit_status": data["info"]["exit_status"],
        "steps": data["info"]["model_stats"]["api_calls"],
        "prompt_tokens": sum(u.get("prompt_tokens") or 0 for u in usage),
        "completion_tokens": sum(u.get("completion_tokens") or 0 for u in usage),
        "artifacts": sum(bool(ARTIFACT_RE.search(str(m.get("content") or ""))) for m in assistant),
        "empty_patch": not data["info"]["submission"].strip(),
        "review_calls": sum(r["n_calls"] for r in data["info"].get("reviews", [])),
        "review_rejected": any(not r["passed"] for r in data["info"].get("reviews", [])),
    }


def main(run_dir: Path, report: Path | None = typer.Option(None, help="SWE-bench harness report json")):
    trajs = [load_traj(p) for p in sorted(run_dir.glob("*/*.traj.json"))]
    resolved = set(json.loads(report.read_text())["resolved_ids"]) if report else set()
    n = len(trajs)

    def mean(key: str) -> float:
        return sum(t[key] for t in trajs) / n

    print(f"run: {run_dir}  instances: {n}")
    if report:
        print(f"resolved: {len(resolved)}/{n} = {len(resolved) / n:.1%}")
    print(
        f"mean steps: {mean('steps'):.1f}   mean prompt tok: {mean('prompt_tokens'):,.0f}   mean completion tok: {mean('completion_tokens'):,.0f}"
    )
    print(
        f"empty patches: {sum(t['empty_patch'] for t in trajs)}   steps with DeepSeek artifacts: {sum(t['artifacts'] for t in trajs)}"
    )
    print("exit statuses:", dict(Counter(t["exit_status"] for t in trajs)))
    if any(t["review_calls"] for t in trajs):
        print(
            f"reviewer: mean calls {mean('review_calls'):.1f}   rejected first submission: {sum(t['review_rejected'] for t in trajs)}/{n}"
        )
    rows = [t | {"resolved": t["id"] in resolved} for t in trajs]
    (run_dir / "stats.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


if __name__ == "__main__":
    typer.run(main)
