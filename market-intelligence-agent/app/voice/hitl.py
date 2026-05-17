"""Verbal HITL: bridge LangGraph interrupts to spoken yes/no turns."""
import logging
import re

from langgraph.types import Command

logger = logging.getLogger(__name__)

_AFFIRMATIVE = re.compile(r"\b(yes|yeah|yep|sure|ok(ay)?|approve|go ahead|do it|confirm)\b", re.I)
_NEGATIVE = re.compile(r"\b(no|nope|cancel|stop|don'?t|reject|deny)\b", re.I)


def classify_verdict(utterance: str) -> str | None:
    """Return 'approve', 'reject', or None if ambiguous."""
    if _NEGATIVE.search(utterance):
        return "reject"
    if _AFFIRMATIVE.search(utterance):
        return "approve"
    return None


async def is_interrupted(agent_app, thread_id: str) -> tuple[bool, str | None]:
    """Return (is_paused, action_description) for the given thread.

    Only treat the graph as awaiting HITL approval when it is specifically paused
    at the `approval` node. Any other non-empty `snapshot.next` (e.g. a failed
    task waiting to be retried after an unrelated exception) must NOT trigger a
    verbal "Say yes or no" prompt.
    """
    snapshot = await agent_app.aget_state({"configurable": {"thread_id": thread_id}})
    if not snapshot.next or "approval" not in snapshot.next:
        return False, None
    last = snapshot.values["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return True, "an action"
    descs = [f"{tc['name']} with args {tc['args']}" for tc in tool_calls]
    return True, "; ".join(descs)


async def resume_with(agent_app, thread_id: str, verdict: str) -> dict:
    """Resume the paused graph with 'approve' or 'reject'. Returns final state."""
    config = {"configurable": {"thread_id": thread_id}}
    return await agent_app.ainvoke(Command(resume=verdict), config)
