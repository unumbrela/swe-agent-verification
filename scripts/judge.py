"""Run single-call LLM judges on the patch dataset. Results are appended to a jsonl cache, so reruns resume."""

import json
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import litellm
import typer
import yaml
from jinja2 import StrictUndefined, Template

import minisweagent  # noqa: F401  (loads API key / base from the global .env)
from minisweagent.models.utils.retry import retry
from minisweagent.utils.log import logger

POOL = {"baseline_nonet", "self_check", "review_first"}
"""Candidate pool for selection: one patch per no-network run, before any reviewer intervention."""

app = typer.Typer()


def query(config: dict, model: str, template: str, reasoning_effort: str | None = None, **kwargs) -> str:
    messages = [
        {"role": "system", "content": config["system_template"]},
        {"role": "user", "content": Template(config[template], undefined=StrictUndefined).render(**kwargs)},
    ]
    # streaming: long non-streamed reasoning requests get dropped by the relay; retry also covers mid-stream drops
    for attempt in retry(logger=logger, abort_exceptions=[litellm.BadRequestError, litellm.AuthenticationError]):
        with attempt:
            chunks = list(
                litellm.completion(
                    model=model,
                    messages=messages,
                    stream=True,
                    timeout=3600,
                    **({"reasoning_effort": reasoning_effort} if reasoning_effort else {}),
                )
            )
    return litellm.stream_chunk_builder(chunks).choices[0].message.content or ""


def run_jobs(out: Path, jobs: dict[str, callable], workers: int):
    done = {json.loads(l)["key"] for l in out.read_text().splitlines()} if out.exists() else set()
    todo = {k: f for k, f in jobs.items() if k not in done}
    print(f"{len(todo)} jobs to run ({len(done)} cached)")
    with ThreadPoolExecutor(workers) as pool, out.open("a") as f:
        futures = {pool.submit(fn): key for key, fn in todo.items()}
        for i, future in enumerate(as_completed(futures)):
            key = futures[future]
            f.write(json.dumps({"key": key} | future.result()) + "\n")
            f.flush()
            print(f"[{i + 1}/{len(todo)}] {key}")


def last_int(pattern: str, text: str) -> int | None:
    return int(m[-1]) if (m := re.findall(pattern, text)) else None


@app.command()
def pointwise(
    data: Path = Path("runs/verifier/patches.jsonl"),
    out: Path = Path("runs/verifier/pointwise.jsonl"),
    config: Path = Path("configs/judge.yaml"),
    model: str = "openai/deepseek-v4-pro",
    samples: int = 3,
    workers: int = 8,
    reasoning_effort: str | None = None,
):
    cfg = yaml.safe_load(config.read_text())
    rows = [json.loads(l) for l in data.read_text().splitlines()]

    def job(row: dict) -> dict:
        response = query(cfg, model, "pointwise_template", reasoning_effort, issue=row["issue"], patch=row["patch"])
        return {"id": row["id"], "score": last_int(r"SCORE:\s*(\d+)", response), "response": response}

    run_jobs(out, {f"{r['id']}/{s}": (lambda r=r: job(r)) for r in rows for s in range(samples)}, workers)


@app.command()
def listwise(
    data: Path = Path("runs/verifier/patches.jsonl"),
    out: Path = Path("runs/verifier/listwise.jsonl"),
    config: Path = Path("configs/judge.yaml"),
    model: str = "openai/deepseek-v4-pro",
    samples: int = 3,
    workers: int = 8,
    mixed_only: bool = typer.Option(
        True, help="Only instances whose candidates differ in label (others can't change the outcome)"
    ),
):
    """One call per instance with all distinct pool candidates, in a different random order per sample."""
    cfg = yaml.safe_load(config.read_text())
    by_instance: dict[str, list[dict]] = {}
    for row in map(json.loads, data.read_text().splitlines()):
        if POOL & set(row["sources"]):
            by_instance.setdefault(row["instance_id"], []).append(row)

    def job(rows: list[dict], seed: int) -> dict:
        order = random.Random(seed).sample(rows, len(rows))
        response = query(cfg, model, "listwise_template", issue=rows[0]["issue"], patches=[r["patch"] for r in order])
        best = last_int(r"BEST:\s*(\d+)", response)
        return {
            "order": [r["id"] for r in order],
            "best": order[best - 1]["id"] if best and best <= len(order) else None,
            "response": response,
        }

    jobs = {
        f"{iid}/{s}": (lambda rows=rows, s=s: job(rows, s))
        for iid, rows in by_instance.items()
        if len(rows) > 1 and (not mixed_only or len({r["resolved"] for r in rows}) > 1)
        for s in range(samples)
    }
    run_jobs(out, jobs, workers)


if __name__ == "__main__":
    app()
