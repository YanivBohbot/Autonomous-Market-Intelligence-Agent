# Multi-Agent API Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-built, already-live-QA'd `app/agent/multi_agent` supervisor+specialist graph into the real FastAPI `/stream` and `/approve` endpoints, replacing the old single-agent graph (`app/agent/graph.py`) as what the API actually serves.

**Architecture:** Hard replace, no toggle. `server.py`'s lifespan builds `build_multi_agent_app` instead of `build_agent_app`. `stream.py` gains `subgraphs=True` on its `astream(...)` call (required to preserve live token streaming from inside specialist subgraphs — verified empirically, see spec) and generalizes its per-node checks (streamable-node set instead of a single `"generate"` name; plain `snapshot.next` truthiness instead of `"approval" in snapshot.next`, since interrupt is the only pause mechanism left in the new graph). `approve.py` needs no changes.

**Tech Stack:** FastAPI, LangGraph 1.1.10 (installed version confirmed; default streaming contract, not the opt-in `version="v2"` dict format), Python 3.12.

**Spec:** `docs/superpowers/specs/2026-09-15-multi-agent-api-cutover-design.md`

## Global Constraints

- No env-var toggle between single-agent and multi-agent — hard replace only.
- `approve.py` is not modified (confirmed in spec: it already checks `snapshot.next` generically).
- `app/agent/graph.py` is not deleted — its functions (`approval_node`, `record_question`, `route_after_approval`) are imported and reused by every specialist in `app/agent/multi_agent/`.
- `app/voice/graph.py` is not touched — it imports node functions directly, not `build_agent_app`, so it's unaffected either way.
- Installed LangGraph is 1.1.10; do not pass `version="v2"` to `astream` — the default (undecorated) tuple contract is what this plan targets and what was verified empirically against the live graph.

---

### Task 1: Rewrite `tests/unit/test_stream.py` for the new streaming contract (RED)

**Files:**
- Modify: `tests/unit/test_stream.py` (whole file — the fake and all 6 tests)

**Interfaces:**
- Consumes: nothing new — this task only changes test fixtures/assertions to describe the target behavior `stream.py` will be updated to match in Task 2.
- Produces: a `_FakeAgentApp.astream(self, inputs, config, stream_mode, subgraphs=False)` that yields 3-tuples `(ns, mode, chunk)`, matching the real LangGraph `subgraphs=True` contract (confirmed via live spike against the actual installed langgraph 1.1.10, and cross-checked against official docs — the default `astream(..., subgraphs=True)` without `version="v2"` yields `(namespace, mode, chunk)` tuples, `namespace` being `()` for the root graph or `("<node>:<task_id>",)` for a nested subgraph node).

This is a pure test-first step: after this task, running the suite should show these 6 tests **failing** against the still-unmodified `stream.py` (which doesn't pass `subgraphs=True` and unpacks 2-tuples, not 3). That failure is expected and is the "RED" checkpoint — verify it, don't skip it.

- [ ] **Step 1: Replace the whole file with the new fixture + tests**

```python
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
    """Stand-in for agent_app with controllable multi-mode astream + get_state.

    Mirrors the real astream(..., subgraphs=True) contract: yields 3-tuples
    (namespace, mode, chunk). `namespace` is () for the root graph or a tuple
    like ("finance_agent:<task_id>",) for a nested specialist subgraph node —
    stream.py itself doesn't branch on namespace (the emitted SSE "node"
    event only ever carries the bare node name), so tests use whatever
    namespace is convenient to construct.
    """

    def __init__(self, tokens, updates=(), next_after=(), state_messages=None):
        # tokens: list[(ns, AIMessageChunk, meta_dict)]
        # updates: list[(ns, dict)]  where dict is {node_name: state}
        self._tokens = tokens
        self._updates = updates
        self._next_after = next_after
        self._state_messages = state_messages or []

    def astream(self, inputs, config, stream_mode, subgraphs=False):
        async def gen():
            for ns, upd in self._updates:
                yield ns, "updates", upd
            for ns, tok, meta in self._tokens:
                yield ns, "messages", (tok, meta)

        return gen()

    async def aget_state(self, config):
        return SimpleNamespace(
            next=self._next_after,
            values={"messages": self._state_messages},
        )


def test_stream_happy_path_yields_token_then_done():
    tokens = [
        ((), AIMessageChunk(content="Hello"), {"langgraph_node": "agent"}),
        ((), AIMessageChunk(content=" "), {"langgraph_node": "agent"}),
        ((), AIMessageChunk(content="world"), {"langgraph_node": "agent"}),
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


def test_stream_emits_token_from_rag_agents_synthesize_node():
    """rag_agent's answer-producing node is named "synthesize", not "agent"
    — the streamable-node set must include both."""
    tokens = [
        ((), AIMessageChunk(content="Amazon"), {"langgraph_node": "synthesize"}),
    ]
    fake = _FakeAgentApp(tokens, next_after=())

    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post(
        "/stream",
        json={"query": "Amazon net income?", "thread_id": "t-synthesize"},
    )

    events = _parse_sse(response.text)
    token_events = [(e, d) for e, d in events if e == "token"]
    assert [d["token"] for _, d in token_events] == ["Amazon"]


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
        ((), {"supervisor": {"messages": []}}),
        (("finance_agent:x",), {"agent": {"messages": [tool_msg]}}),
    ]
    fake = _FakeAgentApp(tokens, updates=updates, next_after=())

    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post("/stream", json={"query": "AMZN?", "thread_id": "t-node"})

    assert response.status_code == 200
    events = _parse_sse(response.text)

    node_events = [d for e, d in events if e == "node"]
    assert {"node": "supervisor", "tool_calls": None} in node_events
    assert {"node": "agent", "tool_calls": ["yfinance_get_ticker_info"]} in node_events
    assert events[-1][0] == "done"


def test_stream_emits_interrupted_when_graph_pauses_on_a_specialist():
    """In the multi-agent graph, snapshot.next reports the PAUSED SPECIALIST's
    name (e.g. "email_agent"), never the literal "approval" — confirmed via
    live QA of memory_agent's HITL flow. interrupt() inside approval_node is
    the only pause mechanism left in the whole graph, so plain truthiness of
    snapshot.next is the correct (and only needed) interrupted signal."""
    tokens = [
        ((), AIMessageChunk(content="Sending"), {"langgraph_node": "agent"}),
    ]
    pending_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_1",
                "name": "send_email",
                "args": {"recipient": "vip@example.com", "subject": "Hi"},
            }
        ],
    )
    fake = _FakeAgentApp(
        tokens,
        next_after=("email_agent",),
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


def test_stream_treats_any_nonempty_snapshot_next_as_interrupted_regardless_of_specialist_name():
    """Confirms the new invariant is generic: whatever specialist name is
    paused, a non-empty snapshot.next always means interrupted — there is no
    other pause path in the new graph to distinguish against."""
    tokens = [
        ((), AIMessageChunk(content="Writing"), {"langgraph_node": "agent"}),
    ]
    pending_msg = AIMessage(
        content="",
        tool_calls=[{"id": "call_2", "name": "write_file", "args": {"path": "x.txt", "content": "y"}}],
    )
    fake = _FakeAgentApp(
        tokens,
        next_after=("filesystem_agent",),
        state_messages=[pending_msg],
    )

    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post(
        "/stream",
        json={"query": "write a file", "thread_id": "t-test-fs"},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)

    assert events[-1][0] == "interrupted"
    done_events = [e for e, _ in events if e == "done"]
    assert done_events == []


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
        (("browser_agent:x",), {"tools": {"messages": [other_msg, shot_msg]}}),
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
        ((), AIMessageChunk(content="Here it is"), {"langgraph_node": "agent"}),
    ]
    shot_msg = ToolMessage(
        content="screenshots/evidence.png",
        name="browser_take_screenshot",
        tool_call_id="call_1",
    )
    updates = [(("browser_agent:x",), {"tools": {"messages": [shot_msg]}})]
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

    def astream(self, inputs, config, stream_mode, subgraphs=False):
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
```

- [ ] **Step 2: Run the suite and confirm it fails against the unmodified `stream.py`**

Run: `uv run pytest tests/unit/test_stream.py -v`
Expected: multiple FAILs — e.g. a `TypeError` about `subgraphs` being an
unexpected keyword argument, or `ValueError: too many values to unpack`,
raised from inside `stream.py`'s current `async for mode, chunk in
agent_app.astream(inputs, config, stream_mode=[...])` line (2-tuple
unpacking against a 3-tuple generator, and no `subgraphs` kwarg accepted by
the real call signature `stream.py` will grow in Task 2). This is the "RED"
checkpoint — confirm the failure is exactly this shape, not a typo/import
error, before moving on.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_stream.py
git commit -m "test(stream): update fixtures for the multi-agent subgraphs=True contract"
```

---

### Task 2: Update `stream.py` to the new streaming contract (GREEN)

**Files:**
- Modify: `app/api/routers/stream.py:74-127` (the whole `stream_endpoint` function, plus a new module-level constant)

**Interfaces:**
- Consumes: `request.app.state.agent_app` (unchanged access pattern — Task 3 changes what object actually gets assigned there, not how this router reads it).
- Produces: the SSE event contract (`node`, `token`, `screenshot`, `interrupted`, `done`, `error` — payload shapes unchanged) that `test_stream.py` (Task 1) and the frontend/Streamlit clients already expect.

- [ ] **Step 1: Add the streamable-node constant and rewrite `stream_endpoint`**

Replace the existing `@router.post("/stream", ...)` function body (keep
`_tool_names_from_update`, `_screenshot_filename`, `_screenshot_urls_from_update`
exactly as they are — they need no changes) with:

```python
_STREAMABLE_NODES = {"agent", "synthesize"}


@router.post("/stream", response_class=EventSourceResponse)
async def stream_endpoint(
    request: Request, payload: StreamRequest
) -> AsyncIterable[ServerSentEvent]:
    agent_app = request.app.state.agent_app
    config = {
        "configurable": {
            "thread_id": payload.thread_id,
            "actor_id": "mia-agent",
        }
    }
    inputs = {"question": payload.query}

    try:
        async for _ns, mode, chunk in agent_app.astream(
            inputs, config, stream_mode=["updates", "messages"], subgraphs=True
        ):
            if mode == "updates":
                for node_name, update in chunk.items():
                    yield ServerSentEvent(
                        data={
                            "node": node_name,
                            "tool_calls": _tool_names_from_update(update),
                        },
                        event="node",
                    )
                    for url in _screenshot_urls_from_update(update):
                        yield ServerSentEvent(data={"url": url}, event="screenshot")
            elif mode == "messages":
                token, meta = chunk
                if (
                    isinstance(token, AIMessageChunk)
                    and meta.get("langgraph_node") in _STREAMABLE_NODES
                    and token.content
                    and not getattr(token, "tool_call_chunks", None)
                ):
                    yield ServerSentEvent(
                        data={"token": token.content}, event="token"
                    )

        snapshot = await agent_app.aget_state(config)
        if snapshot.next:
            last_msg = snapshot.values["messages"][-1]
            action = get_action_description(last_msg)
            yield ServerSentEvent(
                data={"action": action, "next_step": str(snapshot.next)},
                event="interrupted",
            )
        else:
            yield ServerSentEvent(data={}, event="done")
    except Exception as exc:
        logger.exception("stream failed for thread %s", payload.thread_id)
        yield ServerSentEvent(data={"error": str(exc)}, event="error")
```

Note: `_ns` (the namespace tuple that `subgraphs=True` prepends) is
intentionally unused — the emitted `"node"` SSE event carries only the bare
node name (`node_name`), matching the spec's decision to keep the wire
contract unchanged for existing clients.

- [ ] **Step 2: Run the stream tests and confirm they pass**

Run: `uv run pytest tests/unit/test_stream.py -v`
Expected: all 8 tests PASS (6 original + the 2 new ones added in Task 1:
`test_stream_emits_token_from_rag_agents_synthesize_node` and
`test_stream_treats_any_nonempty_snapshot_next_as_interrupted_regardless_of_specialist_name`).

- [ ] **Step 3: Commit**

```bash
git add app/api/routers/stream.py
git commit -m "feat(stream): stream subgraphs, generalize node checks for multi-agent graph"
```

---

### Task 3: Wire `server.py` to build the multi-agent graph

**Files:**
- Modify: `app/api/server.py:7,32-36`

**Interfaces:**
- Consumes: `app.agent.multi_agent.build_multi_agent_app(checkpointer, store)` — same `(checkpointer: BaseCheckpointSaver, store: BaseStore | None = None)` signature as the old `build_agent_app`, already implemented and tested (`app/agent/multi_agent/graph.py`).
- Produces: `app.state.agent_app` now holds the compiled multi-agent graph — this is what `stream.py` (Task 2) and `approve.py` (unmodified) both read.

- [ ] **Step 1: Swap the import and the lifespan call**

In `app/api/server.py`, change:
```python
from app.agent.graph import build_agent_app
```
to:
```python
from app.agent.multi_agent import build_multi_agent_app
```

And change the lifespan body from:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with create_checkpointer() as checkpointer:
        store = create_store()
        app.state.agent_app = build_agent_app(checkpointer, store)
        app.state.voice_agent_app = build_voice_agent_app(checkpointer, store)
        yield
```
to:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with create_checkpointer() as checkpointer:
        store = create_store()
        app.state.agent_app = build_multi_agent_app(checkpointer, store)
        app.state.voice_agent_app = build_voice_agent_app(checkpointer, store)
        yield
```

(`app.state.voice_agent_app` is untouched — `app/voice/graph.py` imports
node functions directly from `app.agent.graph`, not `build_agent_app`, so it
keeps working unchanged regardless of this cutover.)

- [ ] **Step 2: Run the full unit suite**

Run: `uv run pytest tests/ -v`
Expected: all tests pass (the `test_agentcore_contract.py` /
`test_health.py` tests that exercise `app/api/server.py`'s `app` object at
import time should be unaffected, since they don't invoke the lifespan
directly — only `test_stream.py`'s `TestClient(app)` calls matter here, and
those set `app.state.agent_app` to a fake directly, bypassing the lifespan).

- [ ] **Step 3: Commit**

```bash
git add app/api/server.py
git commit -m "feat(server): serve the multi-agent graph instead of the single-agent graph"
```

---

### Task 4: Live end-to-end verification through the real HTTP endpoints

**Files:** none created or modified — this task runs the real server and
drives real HTTP requests against it, per the spec's testing plan step 2.
No mocks: real OpenAI calls, real MCP tool calls, real SQLite checkpointer.

**Interfaces:**
- Consumes: the running FastAPI app (`uv run uvicorn app.api.server:app
  --host 0.0.0.0 --port 8000`), `POST /stream`, `POST /approve` exactly as
  documented in `CLAUDE.md`.

- [ ] **Step 1: Start the real server in the background**

```bash
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000
```
Run with `run_in_background: true` (or equivalent) so it keeps serving while
the following requests are made. Wait for a log line confirming startup
(e.g. "Application startup complete") before proceeding.

- [ ] **Step 2: Drive one real turn per specialist over real HTTP**

For each of the following, POST to `http://localhost:8000/stream` with a
JSON body `{"query": "<question>", "thread_id": "<unique-id>"}` and read the
SSE response body (e.g. via `curl -N` or Python `httpx.stream`), confirming:
(a) `token` events arrive incrementally (not all at once at the end —
this is the whole point of verifying `subgraphs=True` actually works live,
not just in the unit-test fake), (b) the final event is `done` for read-only
questions, and (c) `node` events show sensible names (`supervisor`, then a
specialist name, then possibly `agent`/`tools`/`approval` for nested steps).

Minimum set (mirrors the spec's testing plan):
1. Finance: `{"query": "What's AAPL trading at?", "thread_id": "cutover-finance"}`
2. CRM: `{"query": "How many customers do we have?", "thread_id": "cutover-crm"}`
3. RAG: `{"query": "What was Amazon's net income in 2024?", "thread_id": "cutover-rag"}` — confirm tokens stream from the `synthesize` node (this is the case Task 1's new `test_stream_emits_token_from_rag_agents_synthesize_node` test guards against regressing).
4. Memory (approval path): `{"query": "Remember that my favorite color is teal.", "thread_id": "cutover-memory"}` — confirm the response ends in an `interrupted` SSE event (not `done`), with a real `action` description mentioning `save_memory`.

- [ ] **Step 3: Drive the real HITL resume over HTTP for the memory turn**

`POST http://localhost:8000/approve` with body
`{"thread_id": "cutover-memory", "approved": true}`. Confirm the JSON
response has `"status": "completed"` and a `"response"` string confirming
the save (mirrors the direct-`ainvoke` live QA already done for
`memory_agent` earlier — this step's only new thing is going through the
real HTTP layer instead of calling the graph directly).

- [ ] **Step 4: Confirm the Streamlit UI still completes a basic turn**

Streamlit doesn't parse the `node` SSE event at all (only
`token`/`screenshot`/`interrupted`/`done`/`error`), so this is a regression
check on the event framing, not a new code path. With the server from Step
1 still running:
```bash
uv run streamlit run app/ui/app.py --server.port 8080 --server.address 0.0.0.0
```
Open the app, ask a simple question (e.g. "What's AAPL trading at?"),
confirm the answer streams in and the UI doesn't error or hang. Stop the
Streamlit process once confirmed.

- [ ] **Step 5: Stop the background server**

Terminate the background uvicorn process once all checks above pass.

- [ ] **Step 6: Commit** (only if any fixes were needed during this step; if
  everything passed as-is, there's nothing new to commit — move to Task 5)

---

### Task 5 (optional, cosmetic): Extend the React activity rail's node labels

**Files:**
- Modify: `frontend/src/components/ActivityRail.tsx:4-11`

**Interfaces:**
- Consumes: nothing new — `NodeBadge`'s existing fallback
  (`node.toUpperCase().slice(0, 6)`) already handles any node name not in
  the map, so this task is purely a label-quality improvement, not a
  correctness fix. Skip this task entirely if you'd rather ship the
  functional cutover alone first.

- [ ] **Step 1: Add entries for the new common node names**

Change:
```typescript
const NODE_CONFIG: Record<string, { color: string; label: string }> = {
  rag: { color: "text-sky-400", label: "RAG" },
  grader: { color: "text-violet-400", label: "GRADE" },
  web_search: { color: "text-amber-400", label: "SEARCH" },
  generate: { color: "text-terminal-accent", label: "GEN" },
  tools: { color: "text-pink-400", label: "TOOLS" },
  approval: { color: "text-terminal-warn", label: "GATE" },
};
```
to:
```typescript
const NODE_CONFIG: Record<string, { color: string; label: string }> = {
  record_question: { color: "text-terminal-muted", label: "IN" },
  supervisor: { color: "text-sky-400", label: "ROUTE" },
  agent: { color: "text-terminal-accent", label: "GEN" },
  synthesize: { color: "text-terminal-accent", label: "GEN" },
  web_search: { color: "text-amber-400", label: "SEARCH" },
  tools: { color: "text-pink-400", label: "TOOLS" },
  approval: { color: "text-terminal-warn", label: "GATE" },
};
```

(`rag`/`grader`/`generate` are dropped since those exact node names no
longer occur in the multi-agent graph — `synthesize` and `agent` replace
`generate`'s role; keeping stale entries around would be dead code.)

- [ ] **Step 2: Rebuild and manually confirm in the dev console**

```bash
cd frontend && npm run dev
```
Drive one turn through the UI (any question) and confirm the activity rail
shows recognizable colored badges instead of generic fallback text for
`supervisor`/`agent`/`tools`/`approval` steps.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ActivityRail.tsx
git commit -m "chore(frontend): relabel activity rail for multi-agent node names"
```
