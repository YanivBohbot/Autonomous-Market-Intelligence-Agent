import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

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
    """Stand-in for agent_app with controllable multi-mode astream + get_state."""

    def __init__(self, tokens, updates=(), next_after=(), state_messages=None):
        # tokens: list[(AIMessageChunk, meta_dict)] -> emitted as ("messages", (tok, meta))
        # updates: list[dict]                        -> emitted as ("updates", {node: state})
        self._tokens = tokens
        self._updates = updates
        self._next_after = next_after
        self._state_messages = state_messages or []

    def astream(self, inputs, config, stream_mode):
        async def gen():
            for upd in self._updates:
                yield "updates", upd
            for tok, meta in self._tokens:
                yield "messages", (tok, meta)

        return gen()

    async def aget_state(self, config):
        return SimpleNamespace(
            next=self._next_after,
            values={"messages": self._state_messages},
        )


def test_stream_happy_path_yields_token_then_done():
    tokens = [
        (AIMessageChunk(content="Hello"), {"langgraph_node": "generate"}),
        (AIMessageChunk(content=" "), {"langgraph_node": "generate"}),
        (AIMessageChunk(content="world"), {"langgraph_node": "generate"}),
    ]
    fake = _FakeAgentApp(tokens, next_after=())

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


def test_stream_emits_node_events_for_graph_updates():
    tokens = [
        (AIMessageChunk(content="Hi"), {"langgraph_node": "generate"}),
    ]
    tool_msg = AIMessage(
        content="",
        tool_calls=[
            {"id": "c1", "name": "yfinance_get_ticker_info", "args": {"ticker": "AMZN"}}
        ],
    )
    updates = [
        {"rag": {"messages": []}},
        {"generate": {"messages": [tool_msg]}},
    ]
    fake = _FakeAgentApp(tokens, updates=updates, next_after=())

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
    # A real HITL pause leaves snapshot.next == ("approval",) — that's the node
    # interrupt() was called from, and the one Command(resume=...) resumes.
    fake = _FakeAgentApp(
        tokens,
        next_after=("approval",),
        state_messages=[pending_msg],
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
    fall through to `done`, matching app/voice/hitl.py's is_interrupted, which
    narrows "paused" to specifically 'approval' in snapshot.next for the same
    reason: both independently drive the same shared-thread awaiting_approval
    flag in Streamlit, and must agree."""
    tokens = [
        (AIMessageChunk(content="Retrying"), {"langgraph_node": "generate"}),
    ]
    fake = _FakeAgentApp(
        tokens,
        next_after=("tools",),
        state_messages=[AIMessage(content="")],
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
        (AIMessageChunk(content="Here it is"), {"langgraph_node": "generate"}),
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
        {"tools": {"messages": [other_msg, shot_msg]}},
    ]
    fake = _FakeAgentApp(tokens, updates=updates, next_after=())

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
        (AIMessageChunk(content="Here it is"), {"langgraph_node": "generate"}),
    ]
    shot_msg = ToolMessage(
        content="screenshots/evidence.png",
        name="browser_take_screenshot",
        tool_call_id="call_1",
    )
    updates = [{"tools": {"messages": [shot_msg]}}]
    fake = _FakeAgentApp(tokens, updates=updates, next_after=())

    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post(
        "/stream",
        json={"query": "show me the page", "thread_id": "t-screenshot-2"},
    )

    events = _parse_sse(response.text)
    screenshot_events = [d for e, d in events if e == "screenshot"]
    assert screenshot_events == [{"url": "/workspace/screenshots/evidence.png"}]


class _ExplodingAgentApp:
    """astream raises mid-iteration to simulate a runtime failure."""

    def __init__(self, error_message):
        self._error_message = error_message

    def astream(self, inputs, config, stream_mode):
        async def gen():
            raise RuntimeError(self._error_message)
            yield  # pragma: no cover - makes this an async generator

        return gen()

    async def aget_state(self, config):
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
