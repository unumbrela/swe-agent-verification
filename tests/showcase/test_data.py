import json
from pathlib import Path

import pytest

from showcase import data


def write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj) if not isinstance(obj, list) else "".join(json.dumps(r) + "\n" for r in obj))


def assistant(prompt_tokens: int, command: str) -> dict:
    return {
        "role": "assistant",
        "content": "thinking",
        "reasoning_content": "why",
        "extra": {"actions": [{"command": command}], "response": {"usage": {"prompt_tokens": prompt_tokens}}},
    }


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    write(tmp_path / "review/preds.json", {"i1": {"model_patch": "a"}, "i2": {"model_patch": "b"}})
    write(tmp_path / "eval/m.review.json", {"resolved_ids": ["i1"]})
    write(tmp_path / "review_first/preds.json", {"i2": {"model_patch": "c"}})
    write(tmp_path / "eval/m.review_first.json", {"resolved_ids": ["i2"]})
    review = {"exit_status": "Submitted", "verdict": "VERDICT: FAIL", "passed": False, "n_calls": 3}
    write(
        tmp_path / "review/i1/i1.traj.json",
        {
            "messages": [{"role": "system", "content": "sys"}, assistant(10, "ls")],
            "info": {
                "model_stats": {"api_calls": 7},
                "exit_status": "Submitted",
                "reviews": [review | {"messages": [assistant(5, "cat x")]}],
            },
        },
    )
    write(
        tmp_path / "eval/logs/run_evaluation/review/m/i1/report.json",
        {"i1": {"tests_status": {"FAIL_TO_PASS": {"success": ["t1"], "failure": ["t2"]}, "PASS_TO_PASS": {}}}},
    )
    patches = [
        {"id": 0, "instance_id": "A", "resolved": True, "sources": ["baseline_nonet", "self_check"], "patch": "p0"},
        {"id": 1, "instance_id": "A", "resolved": False, "sources": ["review_first"], "patch": "p1"},
        {"id": 2, "instance_id": "B", "resolved": True, "sources": data.POOL, "patch": "p2"},
        {"id": 3, "instance_id": "B", "resolved": False, "sources": ["baseline"], "patch": "p3"},
    ]
    write(tmp_path / "verifier/patches.jsonl", patches)
    write(tmp_path / "verifier/pointwise.jsonl", [{"id": i, "score": s} for i, s in enumerate([80, 90, 70, 75])])
    write(tmp_path / "verifier/listwise.jsonl", [{"key": f"A/{k}", "best": b} for k, b in enumerate([0, 0, 1])])
    return tmp_path


def test_load_run_with_review_and_base(runs: Path):
    i1 = data.load_run(runs, "review")["i1"]
    assert (i1["steps"], i1["review_steps"], i1["prompt_tokens"], i1["resolved"]) == (7, 3, 15, True)
    assert i1["reviews"] == [{"exit_status": "Submitted", "verdict": "VERDICT: FAIL", "passed": False, "n_calls": 3}]
    assert i1["tests"]["FAIL_TO_PASS"] == {"passed": 1, "failed": ["t2"]}
    assert "steps" not in data.load_run(runs, "review")["i2"]
    first = data.load_run(runs, "review_first", "review")
    assert first["i1"] == {"patch": "a", "resolved": True, "tests": i1["tests"]}
    assert first["i2"] == {"patch": "c", "resolved": True, "tests": None}


def test_trajectory(runs: Path):
    traj = data.trajectory(runs, "review", "i1")
    assert traj["messages"][1] == {"role": "assistant", "content": "thinking", "reasoning": "why", "commands": ["ls"]}
    assert traj["reviews"][0]["passed"] is False
    assert traj["reviews"][0]["messages"][0]["commands"] == ["cat x"]


def test_verifier(runs: Path):
    v = data.verifier(runs)
    assert v["auroc"] == {"global": 0.25, "instance_mean": 0.5, "within": 0.0, "pairs": 2}
    assert {s["key"]: (round(s["total"], 3), round(s["mixed"], 3)) for s in v["selection"]} == {
        "pass1": (1.667, 0.667),
        "majority": (2, 1),
        "pointwise": (1, 0),
        "listwise": (1.667, 0.667),
        "oracle": (2, 1),
    }
    assert [i["id"] for i in v["instances"]] == ["A"]
    assert [c["picks"] for c in v["instances"][0]["candidates"]] == [2, 1]
    assert v["listwise"]["correct"] == 2 and v["listwise"]["calls"] == 3
    assert v["listwise"]["p"] == pytest.approx(20 / 27)
