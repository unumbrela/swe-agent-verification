import pytest

from minisweagent.agents.self_check import SelfCheckAgent
from minisweagent.environments.local import LocalEnvironment
from tests.agents.test_default import make_tc_model, toolcall_config  # noqa: F401

SUBMIT = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && echo patch"


@pytest.mark.parametrize(
    ("max_reviews", "n_submits", "n_queries"),
    [(0, 1, 1), (1, 2, 2), (2, 3, 3)],
)
def test_submissions_held_back(toolcall_config, max_reviews, n_submits, n_queries):  # noqa: F811
    agent = SelfCheckAgent(
        model=make_tc_model([("submit", [{"command": SUBMIT}])] * n_submits),
        env=LocalEnvironment(),
        **toolcall_config,
        review_template="REVIEW {{ n_model_calls }}",
        max_reviews=max_reviews,
    )
    assert agent.run("t") == {"exit_status": "Submitted", "submission": "patch\n"}
    assert agent.n_calls == n_queries
    assert [m["content"] for m in agent.messages if m["content"].startswith("REVIEW")] == [
        f"REVIEW {i}" for i in range(1, max_reviews + 1)
    ]
    assert agent.serialize()["info"]["n_reviews"] == max_reviews


def test_other_actions_in_held_message_get_tool_results(toolcall_config):  # noqa: F811
    agent = SelfCheckAgent(
        model=make_tc_model(
            [
                ("both", [{"command": "echo before"}, {"command": SUBMIT}, {"command": "echo after"}]),
                ("again", [{"command": SUBMIT}]),
            ]
        ),
        env=LocalEnvironment(),
        **toolcall_config,
        review_template="REVIEW",
    )
    agent.run("t")
    tool_msgs = [m for m in agent.messages if m["role"] == "tool"][:3]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call_0_0", "call_0_1", "call_0_2"]
    assert "before" in tool_msgs[0]["content"]
    assert "on hold" in tool_msgs[1]["content"]
    assert "not executed" in tool_msgs[2]["content"]
    assert agent.messages[agent.messages.index(tool_msgs[2]) + 1]["content"] == "REVIEW"
