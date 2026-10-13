from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import StateSnapshot


@dataclass(frozen=True)
class PendingGraphInterrupt:
    interrupt_id: str
    value: dict[str, Any]
    last_message: Any | None


def _snapshots(snapshot):
    yield snapshot
    for task in getattr(snapshot, "tasks", ()) or ():
        child = getattr(task, "state", None)
        if isinstance(child, StateSnapshot):
            yield from _snapshots(child)


def pending_interrupt_from_snapshot(snapshot) -> PendingGraphInterrupt | None:
    for current in _snapshots(snapshot):
        interrupts = getattr(current, "interrupts", ()) or ()
        if not interrupts:
            continue

        interrupt = interrupts[0]
        messages = (getattr(current, "values", None) or {}).get("messages") or []
        value = interrupt.value if isinstance(interrupt.value, dict) else {}
        return PendingGraphInterrupt(
            interrupt_id=str(interrupt.id),
            value=value,
            last_message=messages[-1] if messages else None,
        )
    return None


def pending_action_count(pending: PendingGraphInterrupt) -> int:
    requests = pending.value.get("action_requests")
    return len(requests) if isinstance(requests, list) and requests else 1


def boolean_decisions(
    pending: PendingGraphInterrupt, approved: bool
) -> dict[str, list[dict[str, str]]]:
    decision = (
        {"type": "approve"}
        if approved
        else {"type": "reject", "message": "Rejected by user."}
    )
    return {
        "decisions": [dict(decision) for _ in range(pending_action_count(pending))]
    }


def get_action_description(last_msg, action_request: dict[str, Any] | None = None) -> str:
    # The interrupt's own action request is authoritative: during a HITL pause
    # the specialist's last message can still be the user's question.
    if action_request:
        return f"Exécuter : {action_request.get('name', 'action')} ({action_request.get('args', {})})"

    if isinstance(last_msg, AIMessage):
        if last_msg.tool_calls:
            tool_call = last_msg.tool_calls[0]
            return f"Exécuter : {tool_call['name']} ({tool_call['args']})"
        if last_msg.content:
            return last_msg.content
    return "Action nécessitant une approbation"
