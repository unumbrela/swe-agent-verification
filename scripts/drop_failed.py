"""Remove instances that did not end in a normal submission (e.g. relay outages) so a rerun picks them up again."""

import json
import shutil
from pathlib import Path

import typer


def main(run_dir: Path):
    preds = json.loads((run_dir / "preds.json").read_text()) if (run_dir / "preds.json").exists() else {}

    def ok(iid: str) -> bool:
        traj = run_dir / iid / f"{iid}.traj.json"
        return traj.exists() and json.loads(traj.read_text())["info"].get("exit_status") == "Submitted"

    keep = {iid: v for iid, v in preds.items() if ok(iid)}
    for d in run_dir.iterdir():
        if d.is_dir() and d.name not in keep:
            shutil.rmtree(d)
    (run_dir / "preds.json").write_text(json.dumps(keep, indent=2))
    print(len(keep))


if __name__ == "__main__":
    typer.run(main)
