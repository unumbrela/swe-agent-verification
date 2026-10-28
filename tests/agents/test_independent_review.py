import subprocess

import pytest

from minisweagent.agents.independent_review import IndependentReviewAgent
from minisweagent.environments.local import LocalEnvironment
from tests.agents.test_default import make_tc_model, toolcall_config  # noqa: F401

SUBMIT = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && echo patch"
REVIEWER = {"system_template": "reviewer", "instance_template": "review {{task}} {{patch}}", "step_limit": 5}


@pytest.fixture
def repo(tmp_path):
    subprocess.run(
        "git init -q && echo a > f.txt && git add f.txt && git -c user.email=x -c user.name=x commit -qm i && echo main > f.txt",
        shell=True,
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def make_agent(repo, outputs, toolcall_config):  # noqa: F811
    return IndependentReviewAgent(
        model=make_tc_model(outputs),
        env=LocalEnvironment(cwd=str(repo)),
        **(toolcall_config | {"cost_limit": 0}),
        reviewer=REVIEWER,
        feedback_template="FEEDBACK: {{ feedback }}",
    )


def test_pass_verdict_accepts_first_submission(repo, toolcall_config):  # noqa: F811
    agent = make_agent(
        repo,
        [
            ("main", [{"command": SUBMIT}]),
            ("rev", [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && echo VERDICT: PASS"}]),
        ],
        toolcall_config,
    )
    assert agent.run("task") == {"exit_status": "Submitted", "submission": "patch\n"}
    assert agent.n_calls == 1
    assert [(r["passed"], r["n_calls"], r["workspace"]) for r in agent.reviews] == [(True, 1, "clean")]
    assert agent.reviews[0]["messages"][1]["content"] == "review task patch\n"


def test_fail_verdict_feeds_back_and_restores_workspace(repo, toolcall_config):  # noqa: F811
    agent = make_agent(
        repo,
        [
            ("main", [{"command": SUBMIT}]),
            ("rev", [{"command": "echo tampered > f.txt"}]),
            ("rev", [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && echo VERDICT: FAIL && echo broken"}]),
            ("main again", [{"command": SUBMIT}]),
        ],
        toolcall_config,
    )
    assert agent.run("task")["exit_status"] == "Submitted"
    assert agent.n_calls == 2
    assert (repo / "f.txt").read_text() == "main\n"
    assert [(r["passed"], r["n_calls"], r["workspace"]) for r in agent.reviews] == [(False, 2, "restored")]
    assert [m["content"] for m in agent.messages if m["content"].startswith("FEEDBACK")] == [
        "FEEDBACK: VERDICT: FAIL\nbroken\n"
    ]
    assert agent.serialize()["info"]["reviews"][0]["verdict"] == "VERDICT: FAIL\nbroken\n"
