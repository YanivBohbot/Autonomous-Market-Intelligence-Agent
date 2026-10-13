"""Follow-up suggestions after a Market Desk answer: one small structured
model call on the last question/answer. Runs only for AG-UI turns (the pills
live in CopilotKit) and never fails the turn."""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from app.agent.middleware import specialist_model
from app.agent.orchestration.state import AG_UI_KEY

logger = logging.getLogger(__name__)

_PROMPT = (
    "You suggest follow-up questions for a wealth-management advisor using a market research assistant. "
    "Given the last question and answer, propose exactly 3 short, specific follow-ups the assistant can do next "
    "(compare tickers, simulate a trade, check watchlist alerts, email a client, show news). "
    "title: at most 5 words. message: the full question to send."
)


class Suggestion(BaseModel):
    title: str = Field(max_length=60)
    message: str = Field(max_length=200)


class FollowUps(BaseModel):
    suggestions: list[Suggestion] = Field(min_length=1, max_length=3)


async def _ask_model(question: str, answer: str) -> FollowUps:
    # Internal call: hidden from the Market Desk chat like the router's.
    model = specialist_model().with_structured_output(FollowUps).with_config(
        {"metadata": {"emit-messages": False, "emit-tool-calls": False}}
    )
    return await model.ainvoke([("system", _PROMPT), ("human", f"Question: {question}\n\nAnswer: {answer}")])


async def suggest_followups(state) -> dict:
    if state.get(AG_UI_KEY) is None:
        return {}
    messages = state.get("messages") or []
    if not messages or not isinstance(messages[-1], AIMessage) or not messages[-1].content:
        return {"suggestions": []}
    question = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), "")
    try:
        result = await _ask_model(str(question), str(messages[-1].content))
        return {"suggestions": [s.model_dump() for s in result.suggestions]}
    except Exception:
        logger.exception("follow-up suggestions failed")
        return {"suggestions": []}


def suggest_followups_sync(state) -> dict:
    """Sync twin for graph.invoke() callers (tests, sync paths): those never
    come through AG-UI, so there is nothing to suggest."""
    if state.get(AG_UI_KEY) is None:
        return {}
    return {"suggestions": []}
