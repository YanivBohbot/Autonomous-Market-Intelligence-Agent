from langchain_core.messages import AIMessage
from langgraph.types import Interrupt, PregelTask, StateSnapshot

from app.api.routers._helpers import (
    PendingGraphInterrupt,
    get_action_description,
    pending_action_count,
    pending_interrupt_from_snapshot,
)


def _snapshot(*, messages=(), tasks=(), interrupts=()) -> StateSnapshot:
    return StateSnapshot(
        values={"messages": list(messages)},
        next=(),
        config={},
        metadata=None,
        created_at=None,
        parent_config=None,
        tasks=tuple(tasks),
        interrupts=tuple(interrupts),
    )


def _email_interrupt() -> Interrupt:
    return Interrupt(
        id="interrupt-email-1",
        value={
            "action_requests": [
                {
                    "name": "send_email",
                    "args": {"to": "vip@example.com", "subject": "Market update"},
                }
            ]
        },
    )


def _pending_email_message() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call-email-1",
                "name": "send_email",
                "args": {"to": "vip@example.com", "subject": "Market update"},
            }
        ],
    )


def test_pending_interrupt_comes_from_nested_specialist():
    child = _snapshot(
        messages=(_pending_email_message(),),
        interrupts=(_email_interrupt(),),
    )
    parent = _snapshot(
        tasks=(PregelTask("task-1", "email_agent", ("email_agent",), state=child),),
    )

    pending = pending_interrupt_from_snapshot(parent)

    assert pending is not None
    assert pending.interrupt_id == "interrupt-email-1"
    assert pending.value["action_requests"][0]["name"] == "send_email"
    assert pending.last_message.tool_calls[0]["name"] == "send_email"


def test_pending_interrupt_can_come_from_direct_snapshot():
    snapshot = _snapshot(
        messages=(_pending_email_message(),),
        interrupts=(_email_interrupt(),),
    )

    pending = pending_interrupt_from_snapshot(snapshot)

    assert pending is not None
    assert pending.interrupt_id == "interrupt-email-1"


def test_pending_interrupt_returns_none_for_empty_state():
    assert pending_interrupt_from_snapshot(_snapshot()) is None


def test_pending_action_count_uses_requests_and_defaults_safely():
    pending = PendingGraphInterrupt(
        "i",
        {"action_requests": [{"name": "one"}, {"name": "two"}]},
        None,
    )

    assert pending_action_count(pending) == 2
    assert pending_action_count(PendingGraphInterrupt("i", {}, None)) == 1


def test_action_description_falls_back_to_raw_action_request():
    action = get_action_description(
        None,
        {"name": "send_email", "args": {"to": "vip@example.com"}},
    )

    assert "send_email" in action
    assert "vip@example.com" in action
