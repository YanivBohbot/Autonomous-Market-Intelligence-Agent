import json
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Interrupt, PregelTask, StateSnapshot

from app.api.server import app
from app.agent.turn_coordinator import ThreadTurnCoordinator


@pytest.fixture(autouse=True)
def _fresh_turn_coordinator():
    app.state.turn_coordinator = ThreadTurnCoordinator()


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
    """Stand-in for agent_app with controllable multi-mode astream + get_state."""

    def __init__(self, tokens, updates=(), snapshot=None):
        # tokens: list[(namespace, AIMessageChunk, meta_dict)]
        # updates: list[(namespace, {node: state})]
        self._tokens = tokens
        self._updates = updates
        self._snapshot = snapshot or _state_snapshot()
        self.stream_calls = 0

    def astream(self, inputs, config, stream_mode, subgraphs=False):
        assert subgraphs is True
        self.stream_calls += 1

        async def gen():
            for namespace, update in self._updates:
                yield namespace, "updates", update
            for namespace, token, metadata in self._tokens:
                yield namespace, "messages", (token, metadata)

        return gen()

    async def aget_state(self, config, subgraphs=False):
        assert subgraphs is True
        return self._snapshot


def _state_snapshot(*, messages=(), tasks=(), interrupts=()) -> StateSnapshot:
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


def _parent_with_email_interrupt(pending_message: AIMessage) -> StateSnapshot:
    child = _state_snapshot(
        messages=(pending_message,),
        interrupts=(
            Interrupt(
                id="interrupt-email-1",
                value={
                    "action_requests": [
                        {
                            "name": "send_email",
                            "args": {"to": "vip@example.com", "subject": "Hi"},
                        }
                    ]
                },
            ),
        ),
    )
    return _state_snapshot(
        tasks=(PregelTask("task-1", "email_agent", ("email_agent",), state=child),),
    )


def test_stream_happy_path_yields_token_then_done():
    tokens = [
        ((), AIMessageChunk(content="Hello"), {"langgraph_node": "agent"}),
        ((), AIMessageChunk(content=" "), {"langgraph_node": "agent"}),
        ((), AIMessageChunk(content="world"), {"langgraph_node": "synthesize"}),
    ]
    fake = _FakeAgentApp(tokens)

    app.state.agent_app = fake
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


def test_stream_emits_token_from_installed_create_agent_model_node():
    fake = _FakeAgentApp(
        [((), AIMessageChunk(content="Visible live"), {"langgraph_node": "model"})]
    )
    app.state.agent_app = fake

    response = TestClient(app).post(
        "/stream",
        json={"query": "research this", "thread_id": "t-model-node"},
    )

    events = _parse_sse(response.text)
    assert [data["token"] for event, data in events if event == "token"] == [
        "Visible live"
    ]
    assert events[-1][0] == "done"


def test_stream_emits_node_events_for_graph_updates():
    tokens = [
        ((), AIMessageChunk(content="Hi"), {"langgraph_node": "agent"}),
    ]
    tool_msg = AIMessage(
        content="",
        tool_calls=[
            {"id": "c1", "name": "yfinance_get_ticker_info", "args": {"ticker": "AMZN"}}
        ],
    )
    updates = [
        ((), {"rag": {"messages": []}}),
        (("finance_agent:task",), {"generate": {"messages": [tool_msg]}}),
    ]
    fake = _FakeAgentApp(tokens, updates=updates)

    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post("/stream", json={"query": "AMZN?", "thread_id": "t-node"})

    assert response.status_code == 200
    events = _parse_sse(response.text)

    node_events = [d for e, d in events if e == "node"]
    assert {"node": "rag", "tool_calls": None} in node_events
    assert {"node": "generate", "tool_calls": ["yfinance_get_ticker_info"]} in node_events
    assert events[-1][0] == "done"


def test_stream_emits_interrupted_when_graph_pauses_at_approval():
    tokens = [
        ((), AIMessageChunk(content="Sending"), {"langgraph_node": "agent"}),
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
    # A real HITL pause leaves snapshot.next == ("approval",) — that's the node
    # interrupt() was called from, and the one Command(resume=...) resumes.
    fake = _FakeAgentApp(
        tokens,
        snapshot=_parent_with_email_interrupt(pending_msg),
    )

    app.state.agent_app = fake
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


def test_stream_does_not_emit_interrupted_for_non_approval_pause():
    """A pause at any node other than `approval` (e.g. a failed task retry) must
    fall through to `done`, matching the nested-interrupt detection in
    `_helpers.pending_interrupt_from_snapshot`. Both
    narrow "paused" to specifically 'approval' in snapshot.next for the same
    reason: both independently drive the same shared-thread awaiting_approval
    flag in Streamlit, and must agree."""
    tokens = [
        ((), AIMessageChunk(content="Retrying"), {"langgraph_node": "agent"}),
    ]
    fake = _FakeAgentApp(
        tokens,
        snapshot=_state_snapshot(messages=(AIMessage(content=""),)),
    )

    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post(
        "/stream",
        json={"query": "do something", "thread_id": "t-test-non-approval"},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)

    assert events[-1][0] == "done"
    interrupted_events = [e for e, _ in events if e == "interrupted"]
    assert interrupted_events == []


def test_stream_emits_screenshot_event_for_playwright_mcp_result():
    """@playwright/mcp (local dev backend) returns a list-of-content-blocks
    ToolMessage, not a bare path — the filename is embedded in a markdown
    link inside the block's 'text', e.g. the real shape observed from a
    live browser_take_screenshot call:
    [{'type': 'text', 'text': "### Result\\n- [Screenshot of viewport](./debug-test.png)\\n### Ran Playwright code\\n...", 'id': '...'}]
    """
    tokens = [
        ((), AIMessageChunk(content="Here it is"), {"langgraph_node": "agent"}),
    ]
    shot_msg = ToolMessage(
        content=[
            {
                "type": "text",
                "text": (
                    "### Result\n- [Screenshot of viewport](./evidence.png)\n"
                    "### Ran Playwright code\n```js\nawait page.screenshot({\n"
                    "  path: './evidence.png',\n  scale: 'css',\n  type: 'png'\n});\n```\n"
                    "### Page\n- Page URL: https://example.com/"
                ),
                "id": "lc_abc123",
            }
        ],
        name="browser_take_screenshot",
        tool_call_id="call_1",
    )
    other_msg = ToolMessage(
        content="Navigated to https://example.com",
        name="browser_navigate",
        tool_call_id="call_0",
    )
    updates = [
        (("browser_agent:task",), {"tools": {"messages": [other_msg, shot_msg]}}),
    ]
    fake = _FakeAgentApp(tokens, updates=updates)

    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post(
        "/stream",
        json={"query": "show me the page", "thread_id": "t-screenshot"},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)

    screenshot_events = [d for e, d in events if e == "screenshot"]
    assert screenshot_events == [{"url": "/workspace/screenshots/evidence.png"}]
    assert events[-1][0] == "done"


def test_stream_emits_screenshot_event_for_custom_agentcore_server_result():
    """The custom stdio server (app/mcp/browser/server.py, BROWSER_BACKEND=
    agentcore) returns a plain workspace-relative path string instead."""
    tokens = [
        ((), AIMessageChunk(content="Here it is"), {"langgraph_node": "agent"}),
    ]
    shot_msg = ToolMessage(
        content="screenshots/evidence.png",
        name="browser_take_screenshot",
        tool_call_id="call_1",
    )
    updates = [(("browser_agent:task",), {"tools": {"messages": [shot_msg]}})]
    fake = _FakeAgentApp(tokens, updates=updates)

    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post(
        "/stream",
        json={"query": "show me the page", "thread_id": "t-screenshot-2"},
    )

    events = _parse_sse(response.text)
    screenshot_events = [d for e, d in events if e == "screenshot"]
    assert screenshot_events == [{"url": "/workspace/screenshots/evidence.png"}]


def test_stream_emits_pii_guard_warning_as_token():
    """pii_guard's short-circuit AIMessage is added straight to graph state,
    never streamed as an AIMessageChunk -- that only happens for generate's
    LLM call. Without surfacing it, a blocked turn was record_question ->
    pii_guard -> done with zero token events: the block worked (the LLM
    never saw the data) but the client never saw the warning either."""
    from app.agent.guardrails.detection import SENSITIVE_DATA_WARNING

    warning_msg = AIMessage(content=SENSITIVE_DATA_WARNING)
    updates = [
        ((), {"pii_guard": {"messages": [warning_msg]}}),
    ]
    fake = _FakeAgentApp([], updates=updates)

    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post(
        "/stream",
        json={"query": "my card is 4111 1111 1111 1111", "thread_id": "t-pii"},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)

    token_events = [d["token"] for e, d in events if e == "token"]
    assert token_events == [SENSITIVE_DATA_WARNING]
    assert events[-1][0] == "done"


class _ExplodingAgentApp:
    """astream raises mid-iteration to simulate a runtime failure."""

    def __init__(self, error_message):
        self._error_message = error_message

    def astream(self, inputs, config, stream_mode, subgraphs=False):
        assert subgraphs is True

        async def gen():
            raise RuntimeError(self._error_message)
            yield  # pragma: no cover - makes this an async generator

        return gen()

    async def aget_state(self, config, subgraphs=False):
        assert subgraphs is True
        return SimpleNamespace(next=(), values={"messages": []})


def test_stream_emits_error_frame_when_astream_raises():
    fake = _ExplodingAgentApp("boom")

    app.state.agent_app = fake
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
    assert asyncio.run(app.state.turn_coordinator.owner("t-test-3")) is None


def test_stream_emits_conflict_without_invoking_graph_when_voice_owns_thread():
    fake = _FakeAgentApp([])
    app.state.agent_app = fake
    coordinator = app.state.turn_coordinator
    lease = asyncio.run(coordinator.try_acquire("stream-locked", "voice:test"))
    assert lease is not None
    try:
        response = TestClient(app).post(
            "/stream",
            json={"query": "anything", "thread_id": "stream-locked"},
        )
    finally:
        asyncio.run(coordinator.release(lease))

    assert response.status_code == 200
    assert _parse_sse(response.text) == [
        ("error", {"error": "Voice mode is active for this thread."})
    ]
    assert fake.stream_calls == 0
