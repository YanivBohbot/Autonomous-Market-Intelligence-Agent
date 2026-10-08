from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.types import Interrupt, PregelTask, StateSnapshot

from app.api.server import app


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


def _pending_snapshot(*actions: dict) -> StateSnapshot:
    message = AIMessage(
        content="",
        tool_calls=[
            {"id": f"call-{index}", "name": action["name"], "args": action["args"]}
            for index, action in enumerate(actions, start=1)
        ],
    )
    child = _snapshot(
        messages=(message,),
        interrupts=(
            Interrupt(
                id="interrupt-1",
                value={"action_requests": list(actions)},
            ),
        ),
    )
    return _snapshot(
        tasks=(PregelTask("task-1", "email_agent", ("email_agent",), state=child),),
    )


class _FakeGraph:
    def __init__(self, snapshots, final_state=None):
        self._snapshots = iter(snapshots)
        self.final_state = final_state or {"messages": [AIMessage(content="Done")]}
        self.command = None
        self.state_calls = 0

    async def aget_state(self, config, subgraphs=False):
        assert subgraphs is True
        self.state_calls += 1
        return next(self._snapshots)

    async def ainvoke(self, command, config):
        self.command = command
        return self.final_state


def _email_action(subject: str) -> dict:
    return {
        "name": "send_email",
        "args": {"to": "vip@example.com", "subject": subject},
    }


def test_approve_expands_one_decision_per_pending_action():
    fake = _FakeGraph(
        [
            _pending_snapshot(_email_action("Morning"), _email_action("Evening")),
            _snapshot(),
        ]
    )
    app.state.agent_app = fake

    response = TestClient(app).post(
        "/approve",
        json={"thread_id": "approve-two", "approved": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert fake.command.resume == {
        "decisions": [{"type": "approve"}, {"type": "approve"}]
    }
    assert fake.state_calls == 2


def test_reject_expands_one_explained_decision_per_pending_action():
    fake = _FakeGraph(
        [
            _pending_snapshot(_email_action("Morning"), _email_action("Evening")),
            _snapshot(),
        ]
    )
    app.state.agent_app = fake

    response = TestClient(app).post(
        "/approve",
        json={"thread_id": "reject-two", "approved": False},
    )

    assert response.status_code == 200
    assert fake.command.resume == {
        "decisions": [
            {"type": "reject", "message": "Rejected by user."},
            {"type": "reject", "message": "Rejected by user."},
        ]
    }


def test_approve_returns_expired_response_when_no_interrupt_is_pending():
    fake = _FakeGraph([_snapshot()])
    app.state.agent_app = fake

    response = TestClient(app).post(
        "/approve",
        json={"thread_id": "expired", "approved": True},
    )

    assert response.status_code == 200
    assert response.json() == {
        "response": "⚠️ Session expirée ou terminée. Veuillez relancer votre demande.",
        "status": "completed",
        "next_step": None,
    }
    assert fake.command is None
    assert fake.state_calls == 1


def test_approve_describes_a_second_nested_interrupt():
    fake = _FakeGraph(
        [
            _pending_snapshot(_email_action("First")),
            _pending_snapshot(_email_action("Second approval")),
        ],
        final_state={"messages": [AIMessage(content="stale top-level response")]},
    )
    app.state.agent_app = fake

    response = TestClient(app).post(
        "/approve",
        json={"thread_id": "second-interrupt", "approved": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "interrupted"
    assert "send_email" in body["response"]
    assert "Second approval" in body["response"]
    assert "stale top-level response" not in body["response"]
