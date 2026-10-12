"""Credit-card guardrail for the supervisor's router agent, written as the
documented deterministic guardrail (`@before_agent(can_jump_to=["end"])`,
docs.langchain.com/oss/python/langchain/guardrails). It runs before the
router's model call, so a card number never reaches OpenAI. It returns the
question masked under the SAME id: the supervisor node copies it into the
shared conversation, where the add_messages reducer replaces the raw one,
so no later turn sends it to a model either."""

from typing import Any

from langchain.agents.middleware import AgentState, before_agent
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from app.agent.guardrails.detection import (
    SENSITIVE_DATA_WARNING,
    contains_credit_card,
    mask_credit_cards_in,
)


@before_agent(can_jump_to=["end"])
def block_credit_cards(state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
    latest = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None)
    if latest is None or not contains_credit_card(latest.content):
        return None
    masked = latest.model_copy(update={"content": mask_credit_cards_in(latest.content)})
    return {"messages": [masked, AIMessage(content=SENSITIVE_DATA_WARNING)], "jump_to": "end"}
