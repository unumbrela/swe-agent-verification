"""Agent that holds back the first submission(s) and asks the model to verify its fix against acceptance criteria."""

from minisweagent.agents.default import AgentConfig, DefaultAgent
from minisweagent.exceptions import Submitted
from minisweagent.utils.serialize import recursive_merge


class SelfCheckAgentConfig(AgentConfig):
    review_template: str
    """User message sent in place of accepting a held-back submission."""
    max_reviews: int = 1
    """Number of submissions to hold back before accepting one."""


class SelfCheckAgent(DefaultAgent):
    def __init__(self, *args, config_class: type = SelfCheckAgentConfig, **kwargs):
        super().__init__(*args, config_class=config_class, **kwargs)
        self.n_reviews = 0

    def run(self, task: str = "", **kwargs) -> dict:
        self.n_reviews = 0
        return super().run(task, **kwargs)

    def execute_actions(self, message: dict) -> list[dict]:
        outputs = []
        for action in message.get("extra", {}).get("actions", []):
            try:
                outputs.append(self.env.execute(action))
            except Submitted:
                if self.n_reviews >= self.config.max_reviews:
                    raise
                self.n_reviews += 1
                outputs.append(
                    {"output": "Submission on hold, see next message.", "returncode": 0, "exception_info": ""}
                )
                return self.add_messages(
                    *self.model.format_observation_messages(message, outputs, self.get_template_vars()),
                    self.model.format_message(role="user", content=self._render_template(self.config.review_template)),
                )
        return self.add_messages(*self.model.format_observation_messages(message, outputs, self.get_template_vars()))

    def serialize(self, *extra_dicts) -> dict:
        return super().serialize(recursive_merge({"info": {"n_reviews": self.n_reviews}}, *extra_dicts))
