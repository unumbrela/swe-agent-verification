"""Agent whose first submission is checked by an independent reviewer agent (fresh context: only the task and the diff)."""

from jinja2 import StrictUndefined, Template

from minisweagent.agents.default import AgentConfig, DefaultAgent
from minisweagent.exceptions import Submitted
from minisweagent.utils.serialize import recursive_merge

_STATE_FILE = "/tmp/.mswea_main_state.patch"


class IndependentReviewAgentConfig(AgentConfig):
    reviewer: dict
    """Config (system_template, instance_template, step_limit, ...) for the reviewer DefaultAgent."""
    feedback_template: str
    """User message sent to the main agent when the reviewer rejects the submission."""
    max_reviews: int = 1
    """Number of submissions to review; later submissions are accepted directly."""


class IndependentReviewAgent(DefaultAgent):
    def __init__(self, *args, config_class: type = IndependentReviewAgentConfig, **kwargs):
        super().__init__(*args, config_class=config_class, **kwargs)
        self.reviews: list[dict] = []

    def run(self, task: str = "", **kwargs) -> dict:
        self.reviews = []
        return super().run(task, **kwargs)

    def execute_actions(self, message: dict) -> list[dict]:
        outputs = []
        for action in message.get("extra", {}).get("actions", []):
            try:
                outputs.append(self.env.execute(action))
            except Submitted as e:
                if (
                    len(self.reviews) >= self.config.max_reviews
                    or self.review(e.messages[0]["extra"]["submission"])["passed"]
                ):
                    raise
                outputs.append(
                    {"output": "Submission on hold, see next message.", "returncode": 0, "exception_info": ""}
                )
                feedback = Template(self.config.feedback_template, undefined=StrictUndefined).render(
                    **self.get_template_vars(feedback=self.reviews[-1]["verdict"])
                )
                return self.add_messages(
                    *self.model.format_observation_messages(message, outputs, self.get_template_vars()),
                    self.model.format_message(role="user", content=feedback),
                )
        return self.add_messages(*self.model.format_observation_messages(message, outputs, self.get_template_vars()))

    def review(self, patch: str) -> dict:
        self.env.execute({"command": f"git diff > {_STATE_FILE}"})
        reviewer = DefaultAgent(self.model, self.env, **self.config.reviewer)
        info = reviewer.run(self.extra_template_vars["task"], patch=patch)
        restore = self.env.execute(
            {
                "command": f"git diff | cmp -s - {_STATE_FILE} && echo clean || "
                f"(git checkout -- . && git apply {_STATE_FILE} && echo restored)"
            }
        )
        self.cost += reviewer.cost
        verdict = info.get("submission", "")
        self.reviews.append(
            {
                "exit_status": info.get("exit_status", ""),
                "verdict": verdict,
                "passed": "VERDICT: FAIL" not in verdict,
                "workspace": restore["output"].strip(),
                "n_calls": reviewer.n_calls,
                "messages": reviewer.messages,
            }
        )
        return self.reviews[-1]

    def serialize(self, *extra_dicts) -> dict:
        return super().serialize(recursive_merge({"info": {"reviews": self.reviews}}, *extra_dicts))
