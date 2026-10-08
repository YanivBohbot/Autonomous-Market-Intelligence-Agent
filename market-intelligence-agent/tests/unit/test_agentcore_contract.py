"""Smoke tests for the AgentCore Runtime contract endpoints (/ping, /invocations)."""

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.types import Interrupt, PregelTask, StateSnapshot

from app.api.server import app

client = TestClient(app)


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
            Interrupt(id="interrupt-agentcore", value={"action_requests": list(actions)}),
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


def test_ping_returns_healthy():
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "Healthy"}


def test_invocations_rejects_empty_payload():
    """Neither prompt nor resume → returns a clean error in the response body
    (200, not 422) so AgentCore Runtime treats it as a normal invocation."""
    response = client.post("/invocations", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert "prompt or resume" in body["response"].lower()
    assert body["session_id"] == "default_thread"


def test_invocations_honors_session_header():
    """The X-Amzn-Bedrock-AgentCore-Runtime-Session-Id header should be
    threaded into the response when no session_id is in the body."""
    response = client.post(
        "/invocations",
        json={},
        headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "abc-123"},
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == "abc-123"


def test_invocations_invalid_resume_defaults_to_reject_for_every_action():
    actions = [
        {"name": "send_email", "args": {"to": "one@example.com"}},
        {"name": "save_memory", "args": {"content": "remember this"}},
    ]
    fake = _FakeGraph([_pending_snapshot(*actions), _snapshot()])
    app.state.agent_app = fake

    response = client.post(
        "/invocations",
        json={"resume": "unexpected", "session_id": "agentcore-reject"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert fake.command.resume == {
        "decisions": [
            {"type": "reject", "message": "Rejected by user."},
            {"type": "reject", "message": "Rejected by user."},
        ]
    }
    assert fake.state_calls == 2


def test_invocations_describes_nested_interrupt_after_prompt():
    action = {
        "name": "send_email",
        "args": {"to": "vip@example.com", "subject": "Portfolio report"},
    }
    fake = _FakeGraph(
        [_pending_snapshot(action)],
        final_state={"messages": [AIMessage(content="stale top-level response")]},
    )
    app.state.agent_app = fake

    response = client.post(
        "/invocations",
        json={"prompt": "Send the report", "session_id": "agentcore-prompt"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "interrupted"
    assert "send_email" in body["response"]
    assert body["pending_tool_calls"] == [action]
    assert fake.state_calls == 1
