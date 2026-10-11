"""Graph-level input guardrail: runs before the supervisor, whose router is
a raw ChatOpenAI call that no create_agent middleware can wrap. Without this
node a credit-card number reached OpenAI (via the supervisor) before any
specialist guard could block it."""

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.agent.guardrails.detection import SENSITIVE_DATA_WARNING, contains_credit_card


def input_guard(state) -> Command[Literal["supervisor", "finalize_turn"]]:
    """Ends the turn with a warning, and no LLM call, if the latest user
    message contains a credit card number. Emails pass: several specialists
    need real addresses, and the third-party ones redact them instead."""
    messages = state.get("messages", [])
    latest = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
    if latest is not None and contains_credit_card(latest.content):
        return Command(
            goto="finalize_turn",
            update={"messages": [AIMessage(content=SENSITIVE_DATA_WARNING)]},
        )
    return Command(goto="supervisor")
