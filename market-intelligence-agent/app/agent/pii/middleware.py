"""Multi-agent guard: stops the run before any specialist's model call if the
user's message contains sensitive data."""

from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState, Runtime, hook_config
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.pii.detection import SENSITIVE_DATA_WARNING, contains_sensitive_data


class SensitiveDataGuard(AgentMiddleware):
    """Checks the last `HumanMessage` for a credit card or email before the
    model, any prompt middleware, or any tool ever sees it. Placed first in
    `base_middleware()` — unlike `mask_credit_cards()` / `redact_emails()`,
    which let a scrubbed version of the data through, this blocks the turn
    outright and returns a warning instead."""

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                if contains_sensitive_data(msg.content):
                    return {
                        "messages": [AIMessage(content=SENSITIVE_DATA_WARNING)],
                        "jump_to": "end",
                    }
                return None
        return None

    @hook_config(can_jump_to=["end"])
    async def abefore_model(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        return self.before_model(state, runtime)
