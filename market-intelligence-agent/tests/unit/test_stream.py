import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk

from app.api.server import app


def _parse_sse(body: str):
    """Parse raw SSE text into a list of (event, data_dict) tuples."""
    events = []
    current_event = None
    current_data = None
    for line in body.splitlines():
        if line.startswith("event: "):
            current_event = line[len("event: "):].strip()
        elif line.startswith("data: "):
            current_data = json.loads(line[len("data: "):])
        elif line == "" and (current_event or current_data is not None):
            events.append((current_event, current_data))
            current_event, current_data = None, None
    if current_event or current_data is not None:
        events.append((current_event, current_data))
    return events


class _FakeAgentApp:
    """Stand-in for agent_app with controllable astream + get_state."""

    def __init__(self, tokens, next_after=(), state_messages=None):
        self._tokens = tokens
        self._next_after = next_after
        self._state_messages = state_messages or []

    def astream(self, inputs, config, stream_mode):
        async def gen():
            for tok, meta in self._tokens:
                yield tok, meta

        return gen()

    def get_state(self, config):
        return SimpleNamespace(
            next=self._next_after,
            values={"messages": self._state_messages},
        )


def test_stream_happy_path_yields_token_then_done(monkeypatch):
    tokens = [
        (AIMessageChunk(content="Hello"), {"langgraph_node": "generate"}),
        (AIMessageChunk(content=" "), {"langgraph_node": "generate"}),
        (AIMessageChunk(content="world"), {"langgraph_node": "generate"}),
    ]
    fake = _FakeAgentApp(tokens, next_after=())

    import app.api.routers.stream as stream_module
    monkeypatch.setattr(stream_module, "agent_app", fake)

    client = TestClient(app)
    response = client.post(
        "/stream",
        json={"query": "hi", "thread_id": "t-test-1"},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)

    token_events = [(e, d) for e, d in events if e == "token"]
    assert [d["token"] for _, d in token_events] == ["Hello", " ", "world"]

    assert events[-1][0] == "done"


def test_stream_emits_interrupted_when_graph_pauses_before_tools(monkeypatch):
    tokens = [
        (AIMessageChunk(content="Sending"), {"langgraph_node": "generate"}),
    ]
    pending_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_1",
                "name": "send_email",
                "args": {"to": "vip@example.com", "subject": "Hi"},
            }
        ],
    )
    fake = _FakeAgentApp(
        tokens,
        next_after=("tools",),
        state_messages=[pending_msg],
    )

    import app.api.routers.stream as stream_module
    monkeypatch.setattr(stream_module, "agent_app", fake)

    client = TestClient(app)
    response = client.post(
        "/stream",
        json={"query": "send the email", "thread_id": "t-test-2"},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)

    token_events = [(e, d) for e, d in events if e == "token"]
    assert [d["token"] for _, d in token_events] == ["Sending"]

    assert events[-1][0] == "interrupted"
    interrupted_data = events[-1][1]
    assert "send_email" in interrupted_data["action"]
    assert "vip@example.com" in interrupted_data["action"]

    done_events = [e for e, _ in events if e == "done"]
    assert done_events == []


class _ExplodingAgentApp:
    """astream raises mid-iteration to simulate a runtime failure."""

    def __init__(self, error_message):
        self._error_message = error_message

    def astream(self, inputs, config, stream_mode):
        async def gen():
            raise RuntimeError(self._error_message)
            yield  # pragma: no cover - makes this an async generator

        return gen()

    def get_state(self, config):
        return SimpleNamespace(next=(), values={"messages": []})


def test_stream_emits_error_frame_when_astream_raises(monkeypatch):
    fake = _ExplodingAgentApp("boom")

    import app.api.routers.stream as stream_module
    monkeypatch.setattr(stream_module, "agent_app", fake)

    client = TestClient(app)
    response = client.post(
        "/stream",
        json={"query": "anything", "thread_id": "t-test-3"},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)

    assert events[-1][0] == "error"
    assert events[-1][1]["error"] == "boom"

    done_events = [e for e, _ in events if e == "done"]
    assert done_events == []
