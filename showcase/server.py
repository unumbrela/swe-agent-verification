"""Showcase site: a read-only JSON API over runs/ plus the static frontend in web/."""

from pathlib import Path

import typer
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from showcase import data

RUNS = Path(__file__).resolve().parents[1] / "runs"

app = FastAPI(title="mini-swe-agent showcase")


@app.get("/api/overview")
def overview() -> dict:
    return {k: data.CONTENT[k] for k in ("title", "subtitle", "summary", "noise", "findings")} | {
        "runs": data.run_summary(RUNS),
        "selection": data.verifier(RUNS)["selection"],
    }


@app.get("/api/runs")
def runs() -> dict:
    return data.runs_page(RUNS)


@app.get("/api/instances/{iid}")
def instance(iid: str) -> dict:
    if iid not in data.instance_ids(RUNS):
        raise HTTPException(404, f"unknown instance {iid}")
    return data.instance(RUNS, iid)


@app.get("/api/trajectories/{key}/{iid}")
def trajectory(key: str, iid: str) -> dict:
    if not any(r["key"] == key and r["has_traj"] for r in data.run_summary(RUNS)) or iid not in data.instance_ids(RUNS):
        raise HTTPException(404, f"no trajectory for {key}/{iid}")
    return data.trajectory(RUNS, key, iid)


@app.get("/api/verifier")
def verifier() -> dict:
    return data.verifier(RUNS)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True))


def main(host: str = "127.0.0.1", port: int = 8000):
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    typer.run(main)
