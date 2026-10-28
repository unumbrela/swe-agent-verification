"""Smoke test: run DefaultAgent with a local env on a trivial task and print the trajectory."""

import logging
import sys
import tempfile
from pathlib import Path

import typer
import yaml

from minisweagent import package_dir
from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models.litellm_model import LitellmModel

logging.basicConfig(level=logging.WARNING, stream=sys.stdout)


def main(model: str = "openai/deepseek-v4-flash", api_base: str = "https://xhyapi.com/v1", step_limit: int = 15):
    cfg = yaml.safe_load((package_dir / "config/mini.yaml").read_text())
    workdir = Path(tempfile.mkdtemp(prefix="mswea_smoke_"))
    agent = DefaultAgent(
        LitellmModel(
            model_name=model, cost_tracking="ignore_errors", model_kwargs={"api_base": api_base, "timeout": 60}
        ),
        LocalEnvironment(cwd=str(workdir)),
        **(cfg["agent"] | {"step_limit": step_limit}),
    )
    result = agent.run("Create hello.py that prints 'hi', run it, then submit.")
    for m in agent.messages[2:]:
        print(f"--- [{m['role']}]", str(m.get("content"))[:400], m.get("extra", {}).get("actions", ""))
    print("RESULT", result, "| steps:", agent.n_calls, "| files:", [p.name for p in workdir.iterdir()])


if __name__ == "__main__":
    typer.run(main)
