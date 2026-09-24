# CopilotKit foundation ("Market Desk") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CopilotKit-based "Market Desk" mode to the React console, served by a new opt-in AG-UI endpoint on FastAPI that runs the multi-agent graph, with a live activity rail and interactive approval cards.

**Architecture:** FastAPI gains `POST /copilot/market-desk`, an AG-UI SSE endpoint backed by `ag_ui_langgraph.LangGraphAgent` wrapping `build_multi_agent_app(checkpointer, store)`, built in `lifespan` and enabled only when `COPILOT_ENABLED=true`. The browser uses CopilotKit v2 (`@copilotkit/react-core/v2`) with a locally registered `HttpAgent` (no CopilotKit runtime). A pure reducer turns AG-UI events into activity rows; a pure approval panel turns user clicks into `HumanInTheLoopMiddleware` decisions.

**Tech Stack:** Python 3 / FastAPI / LangGraph / `ag-ui-langgraph` 0.0.45; React 18 / Vite 5 / Tailwind 3 / Vitest 2 / `@copilotkit/react-core` 1.73.3 / `zod`.

**Spec:** `docs/superpowers/specs/2026-09-24-copilotkit-foundation-design.md`

## Global Constraints

- Server side stays 100% Python. No CopilotKit runtime (Node or Python).
- Endpoint path `POST /copilot/market-desk`; AG-UI agent id `market_desk` everywhere (provider, `CopilotChat`, `useAgent`, `useInterrupt`).
- `COPILOT_ENABLED: bool = False`. Disabled → the path returns 404. `true` only in local `.env`.
- `LangGraphAgent(name="market_desk", graph=..., emit_subagent_events=True, emit_interrupt_outcome=True, enable_legacy_on_interrupt_event=False)`.
- `ag-ui-langgraph` goes into `pyproject.toml` / `uv.lock` only. `requirements.agentcore.txt` is NOT changed.
- Single-agent graph, `/stream`, `/approve`, Streamlit, voice, `VoicePanel`, Classic mode: untouched in behavior.
- Frontend deps: `@copilotkit/react-core` `1.73.3` (exact), `zod` `^3.25`. React stays 18. Import `@copilotkit/react-core/v2/styles.css`.
- UI labels in English.
- Tests: no OpenAI calls (fake models, `patch.object(supervisor_mod, "_router")`, `tests/unit/fake_chat.FakeToolModel`).
- All Python commands via `uv run` from `market-intelligence-agent/`. Do NOT push (user rule); commit locally only.

## Deviations from the spec (found while planning, verified in the installed sources)

1. **Hiding the supervisor's routing output.** The spec says "`nostream` tag". `ag-ui-langgraph` 0.0.45 streams through `graph.astream_events` and ignores the `nostream` tag; it filters on run metadata `emit-messages` / `emit-tool-calls` (`ag_ui_langgraph/agent.py`, `_handle_single_event`). The plan configures `_router` with `metadata={"emit-messages": False, "emit-tool-calls": False}` instead. Same intent, working mechanism.
2. **`@ag-ui/client` is not added.** `@copilotkit/react-core/v2` re-exports `HttpAgent` and pins its own `@ag-ui/client` (0.0.59). Importing `HttpAgent` from CopilotKit avoids two copies of the client with mismatched `AbstractAgent` types.
3. **`threadId` is not a provider prop** in 1.73.3 (`CopilotKitProviderProps` has `agentId`, `agents__unsafe_dev_only`, no `threadId`). The plan sets `agentId="market_desk"` on `CopilotKitProvider`, passes `threadId` to `CopilotChat` and `useAgent`, and remounts the desk with `key={threadId}` on New session.
4. **Resume format.** Python tests resume with the AG-UI 1.0 field `resume: [{interruptId, status: "resolved", payload}]` rather than the deprecated `forwardedProps.command.resume` (both work; the latter logs a deprecation warning).

## Review Focus

1. **Second turn in the same thread** — CopilotKit re-sends the whole message list on every run; the checkpointed state must not end up with the first question twice. Pinned in Task 2 (`test_second_turn_does_not_duplicate_history`).
2. **Double click on the last decision** — resuming twice would replay the graph; the panel must submit exactly once. Pinned in Task 6 (`submits once even when clicked twice`).
3. **Request before startup finished / agent missing** — must be a clean 503, not a 500 traceback. Pinned in Task 2 (`test_returns_503_when_agent_not_ready`).
4. **Backend error mid-run (`RUN_ERROR`)** — the rail must show the error instead of looking stuck on "running". Pinned in Task 5 (`RUN_ERROR becomes an error row`).
5. **Interrupt without `action_requests`** (malformed or a future interrupt type) — the user must still be able to cancel instead of being stuck. Pinned in Task 6 (`renders a cancel-only card when there are no requests`).

---

## File map

**Python**
- Modify `app/agent/multi_agent/supervisor.py` — `_router` gets the AG-UI "don't emit" metadata.
- Modify `app/core/config.py` — `COPILOT_ENABLED`.
- Create `app/api/routers/copilot.py` — `build_market_desk_agent()`, `attach_market_desk()`, router with `POST /copilot/market-desk`.
- Modify `app/api/server.py` — lifespan attaches the agent when enabled; router included only when enabled.
- Modify `pyproject.toml`, `uv.lock` — `ag-ui-langgraph==0.0.45`.
- Modify `CLAUDE.md` — optional key `COPILOT_ENABLED`, React command note.
- Tests: `tests/unit/test_multi_agent_supervisor_routing.py` (1 new test), `tests/unit/test_copilot_endpoint.py` (new), `tests/unit/test_copilot_wiring.py` (new).

**Frontend (`frontend/`)**
- Modify `package.json`, `package-lock.json`, `vite.config.ts` (`/copilot` proxy).
- Create `src/desk/constants.ts` — `MARKET_DESK_AGENT_ID`, `MARKET_DESK_URL`.
- Create `src/desk/mode.ts` — `loadMode()` / `saveMode()`.
- Create `src/desk/DeskView.tsx` — provider + chat + rail + interrupt hook.
- Create `src/desk/activity.ts` — `reduceActivity()` (pure).
- Create `src/desk/DeskActivityRail.tsx`.
- Create `src/desk/approvals.ts` — `readApproval()`, `EDITABLE_FIELDS` (pure).
- Create `src/desk/ApprovalPanel.tsx` — presentational cards; `src/desk/useDeskInterrupt.tsx` — CopilotKit glue.
- Modify `src/App.tsx`, `src/components/Header.tsx`, `src/App.test.tsx`.
- Tests: `src/desk/mode.test.ts`, `src/desk/activity.test.ts`, `src/desk/approvals.test.ts`, `src/desk/ApprovalPanel.test.tsx`.

---

### Task 1: Hide the supervisor's routing output from AG-UI streams

**Files:**
- Modify: `app/agent/multi_agent/supervisor.py` (the `_router = ...` line)
- Test: `tests/unit/test_multi_agent_supervisor_routing.py`

**Interfaces:**
- Produces: `supervisor._router` is a runnable whose `.config["metadata"]` contains `{"emit-messages": False, "emit-tool-calls": False}`. Existing tests patch `_router` wholesale, so they are unaffected.

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_multi_agent_supervisor_routing.py`:

```python
def test_router_output_is_hidden_from_ag_ui_streams():
    # ag-ui-langgraph streams via astream_events and drops LLM chunks whose run
    # metadata says emit-messages/emit-tool-calls False. The routing JSON
    # ({"next": ...}) must never show up as chat text in Market Desk.
    metadata = supervisor_mod._router.config["metadata"]
    assert metadata["emit-messages"] is False
    assert metadata["emit-tool-calls"] is False
```

(`supervisor_mod` is already imported at the top of that file as `from app.agent.multi_agent import supervisor as supervisor_mod`; if the file uses a different alias, use it.)

- [ ] **Step 2: Run it, expect FAIL**

Run: `uv run pytest tests/unit/test_multi_agent_supervisor_routing.py::test_router_output_is_hidden_from_ag_ui_streams -v`
Expected: FAIL (`AttributeError` on `.config` or `KeyError: 'metadata'`).

- [ ] **Step 3: Implement** — in `supervisor.py` replace

```python
_router = _llm.with_structured_output(RoutingDecision)
```

with

```python
# The routing decision is internal: Market Desk (ag-ui-langgraph, which streams
# via astream_events) must not render its JSON as chat text. The decision stays
# visible through state.next_agent and STEP_STARTED events.
_router = _llm.with_structured_output(RoutingDecision).with_config(
    metadata={"emit-messages": False, "emit-tool-calls": False}
)
```

- [ ] **Step 4: Run the supervisor + multi-agent tests, expect PASS**

Run: `uv run pytest tests/unit/test_multi_agent_supervisor_routing.py tests/unit/test_multi_agent_end_to_end.py tests/unit/test_multi_agent_hitl.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/multi_agent/supervisor.py tests/unit/test_multi_agent_supervisor_routing.py
git commit -m "feat(multi-agent): hide supervisor routing output from AG-UI streams"
```

---

### Task 2: AG-UI endpoint `POST /copilot/market-desk`

**Files:**
- Modify: `pyproject.toml`, `uv.lock`
- Modify: `app/core/config.py`
- Create: `app/api/routers/copilot.py`
- Test: `tests/unit/test_copilot_endpoint.py`

**Interfaces:**
- Consumes: `build_multi_agent_app(checkpointer, store)` from `app.agent.multi_agent`.
- Produces (used by Task 3):
  - `MARKET_DESK_AGENT_NAME = "market_desk"`
  - `build_market_desk_agent(checkpointer: BaseCheckpointSaver, store: BaseStore | None) -> LangGraphAgent`
  - `attach_market_desk(app: FastAPI, checkpointer, store) -> None` — sets `app.state.market_desk_agent`.
  - `router: APIRouter` with `POST /copilot/market-desk`.
  - `settings.COPILOT_ENABLED: bool`.

- [ ] **Step 1: Add the dependency**

Run: `uv add "ag-ui-langgraph==0.0.45"`
Expected: `pyproject.toml` and `uv.lock` updated; `uv run python -c "import ag_ui_langgraph, ag_ui.encoder; print('ok')"` prints `ok`.
Do NOT touch `requirements.agentcore.txt`.

- [ ] **Step 2: Add the setting** — in `app/core/config.py`, below `WORKSPACE_ROOT`:

```python
    # Market Desk (CopilotKit / AG-UI) endpoint for the multi-agent graph.
    # Local dev only until prod exposure is decided.
    COPILOT_ENABLED: bool = False
```

- [ ] **Step 3: Write the failing tests** — create `tests/unit/test_copilot_endpoint.py`:

```python
"""POST /copilot/market-desk: AG-UI SSE over the multi-agent graph.
Every LLM is faked; the router is exercised on a bare FastAPI app so the
test doesn't depend on the COPILOT_ENABLED flag (see test_copilot_wiring)."""
import json
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import email_agent as email_mod
from app.agent.multi_agent import finance_agent as finance_mod
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision
from app.api.routers.copilot import attach_market_desk, router
from tests.unit.fake_chat import FakeToolModel

PATH = "/copilot/market-desk"
SENT: list[dict] = []


@tool("send_email")
async def _fake_send_email(recipient: str, subject: str, body: str) -> str:
    """Fake send."""
    SENT.append({"recipient": recipient, "subject": subject, "body": body})
    return f"sent to {recipient}"


async def _always_known(address: str) -> bool:
    return True


def _events(body: str) -> list[dict]:
    """AG-UI SSE frames are `data: {json}` lines."""
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]


def _run_input(thread_id: str, run_id: str, messages: list[dict], **extra) -> dict:
    return {"threadId": thread_id, "runId": run_id, "messages": messages,
            "state": {}, "tools": [], "context": [], "forwardedProps": {}, **extra}


def _client_with(stack: ExitStack, route_to: str) -> tuple[TestClient, FastAPI]:
    router_mock = stack.enter_context(patch.object(supervisor_mod, "_router"))
    router_mock.invoke.return_value = RoutingDecision(next=route_to, reasoning="test")
    app = FastAPI()
    app.include_router(router)
    attach_market_desk(app, InMemorySaver(), None)
    return TestClient(app), app


@pytest.fixture
def finance_client():
    fake = FakeToolModel([AIMessage(content="AAPL is trading at $200."),
                          AIMessage(content="MSFT is trading at $400.")])
    with ExitStack() as stack:
        stack.enter_context(patch.object(finance_mod, "specialist_model", return_value=fake))
        client, app = _client_with(stack, "finance_agent")
        yield client, app


@pytest.fixture
def email_client():
    SENT.clear()
    call = {"id": "e1", "name": "send_email",
            "args": {"recipient": "a@example.com", "subject": "Hi", "body": "Report"}}
    fake = FakeToolModel([AIMessage(content="", tool_calls=[call]), AIMessage(content="Email handled.")])
    with ExitStack() as stack:
        stack.enter_context(patch.object(email_mod, "specialist_model", return_value=fake))
        stack.enter_context(patch.object(email_mod, "_TOOLS", [_fake_send_email]))
        stack.enter_context(patch.object(email_mod, "_is_client_email", _always_known))
        client, _ = _client_with(stack, "email_agent")
        yield client


def test_returns_503_when_agent_not_ready():
    app = FastAPI()
    app.include_router(router)  # no attach_market_desk: startup not finished
    resp = TestClient(app).post(PATH, json=_run_input("t0", "r0", []))
    assert resp.status_code == 503


def test_streams_a_finance_answer(finance_client):
    client, _ = finance_client
    resp = client.post(PATH, json=_run_input("t1", "r1", [{"id": "u1", "role": "user", "content": "AAPL price?"}]),
                       headers={"accept": "text/event-stream"})
    assert resp.status_code == 200
    events = _events(resp.text)
    types = [e["type"] for e in events]
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    text = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "AAPL is trading at $200." in text
    # Routing JSON is never rendered as chat text (Task 1).
    assert '"next"' not in text
    assert any(e["type"] == "STEP_STARTED" and e.get("stepName") == "finance_agent" for e in events)


def test_second_turn_does_not_duplicate_history(finance_client):
    # CopilotKit re-sends the whole thread on every run; ag-ui-langgraph must
    # merge by message id so the checkpoint keeps each question once.
    client, app = finance_client
    first = {"id": "u1", "role": "user", "content": "AAPL price?"}
    client.post(PATH, json=_run_input("t2", "r1", [first]))
    second = {"id": "u2", "role": "user", "content": "And MSFT?"}
    client.post(PATH, json=_run_input("t2", "r2", [first, second]))

    graph = app.state.market_desk_agent.graph
    state = graph.get_state({"configurable": {"thread_id": "t2"}})
    humans = [m.content for m in state.values["messages"] if isinstance(m, HumanMessage)]
    assert humans == ["AAPL price?", "And MSFT?"]


def test_email_interrupts_then_reject_does_not_send(email_client):
    ask = {"id": "u1", "role": "user", "content": "email the report"}
    first = _events(email_client.post(PATH, json=_run_input("t3", "r1", [ask])).text)
    finished = [e for e in first if e["type"] == "RUN_FINISHED"][-1]
    assert finished["outcome"]["type"] == "interrupt"
    interrupt = finished["outcome"]["interrupts"][0]
    request = interrupt["metadata"]["langgraph"]["raw"]["action_requests"][0]
    assert request["name"] == "send_email"
    assert SENT == []

    resume = [{"interruptId": interrupt["id"], "status": "resolved",
               "payload": {"decisions": [{"type": "reject", "message": "not now"}]}}]
    second = email_client.post(PATH, json=_run_input("t3", "r2", [ask], resume=resume))
    assert second.status_code == 200
    assert [e["type"] for e in _events(second.text)][-1] == "RUN_FINISHED"
    assert SENT == []
```

- [ ] **Step 4: Run, expect FAIL**

Run: `uv run pytest tests/unit/test_copilot_endpoint.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'app.api.routers.copilot'`.

- [ ] **Step 5: Implement** — create `app/api/routers/copilot.py`:

```python
"""Market Desk: AG-UI endpoint over the multi-agent graph (CopilotKit v2 talks
to it directly, no CopilotKit runtime).

The graph needs the app's checkpointer, which only exists inside lifespan, so
the agent is attached to app.state at startup (attach_market_desk) and this
handler mirrors ag_ui_langgraph.add_langgraph_fastapi_endpoint around it.
Included only when settings.COPILOT_ENABLED is true (see server.py).
"""
from ag_ui.core.types import RunAgentInput
from ag_ui.encoder import EventEncoder
from ag_ui_langgraph import LangGraphAgent
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from app.agent.multi_agent import build_multi_agent_app

MARKET_DESK_AGENT_NAME = "market_desk"

router = APIRouter()


def build_market_desk_agent(
    checkpointer: BaseCheckpointSaver, store: BaseStore | None
) -> LangGraphAgent:
    return LangGraphAgent(
        name=MARKET_DESK_AGENT_NAME,
        graph=build_multi_agent_app(checkpointer, store),
        emit_subagent_events=True,
        emit_interrupt_outcome=True,
        enable_legacy_on_interrupt_event=False,
    )


def attach_market_desk(
    app: FastAPI, checkpointer: BaseCheckpointSaver, store: BaseStore | None
) -> None:
    app.state.market_desk_agent = build_market_desk_agent(checkpointer, store)


@router.post("/copilot/market-desk")
async def market_desk(input_data: RunAgentInput, request: Request):
    agent: LangGraphAgent | None = getattr(request.app.state, "market_desk_agent", None)
    if agent is None:
        raise HTTPException(status_code=503, detail="Market Desk agent is not ready.")

    encoder = EventEncoder(accept=request.headers.get("accept"))
    # LangGraphAgent keeps per-run state on the instance: one clone per request.
    run_agent = agent.clone()

    async def events():
        async for event in run_agent.run(input_data):
            yield encoder.encode(event)

    return StreamingResponse(events(), media_type=encoder.get_content_type())
```

- [ ] **Step 6: Run, expect PASS**

Run: `uv run pytest tests/unit/test_copilot_endpoint.py -v`
Expected: 4 PASS.
If `test_email_interrupts_then_reject_does_not_send` fails on the event shape, print `first` and adjust only the *reading* of the outcome (key names) to what ag-ui-langgraph actually emits — the spike recorded `outcome = {type: "interrupt", interrupts: [{id, reason, metadata: {langgraph: {raw: {action_requests, review_configs}}}}]}`. Do not weaken the `SENT == []` assertions.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock app/core/config.py app/api/routers/copilot.py tests/unit/test_copilot_endpoint.py
git commit -m "feat(api): AG-UI endpoint /copilot/market-desk over the multi-agent graph"
```

---

### Task 3: Wire the endpoint into the server behind `COPILOT_ENABLED`

**Files:**
- Modify: `app/api/server.py`
- Modify: `CLAUDE.md`
- Test: `tests/unit/test_copilot_wiring.py`

**Interfaces:**
- Consumes: `attach_market_desk`, `router` from Task 2; `settings.COPILOT_ENABLED`.

- [ ] **Step 1: Write the failing tests** — create `tests/unit/test_copilot_wiring.py`:

```python
"""COPILOT_ENABLED gates Market Desk: off by default (404), and when on the
lifespan attaches the agent to app.state."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.api import server
from app.api.routers.copilot import MARKET_DESK_AGENT_NAME


def test_disabled_by_default_returns_404():
    assert server.settings.COPILOT_ENABLED is False
    resp = TestClient(server.app).post("/copilot/market-desk", json={})
    assert resp.status_code == 404


def test_setup_market_desk_attaches_agent_when_enabled(monkeypatch):
    monkeypatch.setattr(server.settings, "COPILOT_ENABLED", True)
    app = FastAPI()
    server.setup_market_desk(app, InMemorySaver(), None)
    assert app.state.market_desk_agent.name == MARKET_DESK_AGENT_NAME


def test_setup_market_desk_is_a_no_op_when_disabled(monkeypatch):
    monkeypatch.setattr(server.settings, "COPILOT_ENABLED", False)
    app = FastAPI()
    server.setup_market_desk(app, InMemorySaver(), None)
    assert not hasattr(app.state, "market_desk_agent")
```

Note: `TestClient(server.app)` without a `with` block does not run the lifespan, so no MCP/SQLite startup happens in the 404 test.

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/unit/test_copilot_wiring.py -v`
Expected: `AttributeError: module 'app.api.server' has no attribute 'setup_market_desk'` (the 404 test may already pass).

- [ ] **Step 3: Implement** — in `app/api/server.py`:

Add the import next to the other routers:

```python
from app.api.routers.copilot import attach_market_desk, router as copilot_router
```

Add above `lifespan`:

```python
def setup_market_desk(app: FastAPI, checkpointer, store) -> None:
    """Market Desk (multi-agent over AG-UI) is opt-in: COPILOT_ENABLED."""
    if settings.COPILOT_ENABLED:
        attach_market_desk(app, checkpointer, store)
```

In `lifespan`, after `app.state.voice_agent_app = ...`:

```python
        setup_market_desk(app, checkpointer, store)
```

After the last `app.include_router(...)`:

```python
if settings.COPILOT_ENABLED:
    app.include_router(copilot_router)
```

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/unit/test_copilot_wiring.py tests/unit/test_stream.py -v`
Expected: all PASS.

- [ ] **Step 5: Docs** — in `CLAUDE.md`:
  - In the "Optional with defaults" line, append `` `COPILOT_ENABLED` (False — enables the Market Desk AG-UI endpoint `/copilot/market-desk`; set `true` in local `.env`) ``.
  - In "API routers", add a bullet: `` - `copilot.py` — `POST /copilot/market-desk` (AG-UI SSE over the multi-agent graph, agent id `market_desk`), included only when `COPILOT_ENABLED`; the agent is built in `lifespan`. ``
  - In "Multi-agent mode", replace "Not wired to the API/UI/voice" with "Wired only to the opt-in Market Desk endpoint (`COPILOT_ENABLED`); not to `/stream`, Streamlit or voice".
  - Add `COPILOT_ENABLED=true` to the local `.env` by hand (do not commit `.env`; if `.env.example` exists, add `COPILOT_ENABLED=false` there).

- [ ] **Step 6: Full Python suite**

Run: `uv run pytest tests/ -q`
Expected: all pass (previous count 238 + 1 + 4 + 3 = 246).

- [ ] **Step 7: Commit**

```bash
git add app/api/server.py tests/unit/test_copilot_wiring.py CLAUDE.md
git add .env.example 2>/dev/null || true
git commit -m "feat(api): mount Market Desk endpoint behind COPILOT_ENABLED"
```

---

### Task 4: Frontend deps, proxy, mode toggle and Market Desk shell

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.ts`
- Create: `frontend/src/desk/constants.ts`, `frontend/src/desk/mode.ts`, `frontend/src/desk/DeskView.tsx`
- Modify: `frontend/src/components/Header.tsx`, `frontend/src/App.tsx`, `frontend/src/App.test.tsx`
- Test: `frontend/src/desk/mode.test.ts`, `frontend/src/App.test.tsx`

**Interfaces:**
- Produces:
  - `constants.ts`: `export const MARKET_DESK_AGENT_ID = "market_desk"; export const MARKET_DESK_URL = "/copilot/market-desk";`
  - `mode.ts`: `export type ConsoleMode = "desk" | "classic"; export function loadMode(): ConsoleMode; export function saveMode(mode: ConsoleMode): void;`
  - `DeskView.tsx`: `export function DeskView({ threadId }: { threadId: string })`. Task 5 fills the rail slot with `<DeskActivityRail threadId={threadId} />`; Task 6 calls `useDeskInterrupt()` inside `DeskBody`.
  - `Header` gets props `mode: ConsoleMode; onModeChange: (m: ConsoleMode) => void`.

All commands in this task run from `frontend/`.

- [ ] **Step 1: Install deps and add the proxy**

Run: `npm install --save-exact @copilotkit/react-core@1.73.3 && npm install "zod@^3.25"`
Expected: `package.json` has `"@copilotkit/react-core": "1.73.3"` (exact) and `"zod": "^3.25.x"`.
In `vite.config.ts` add next to the other proxy entries:

```ts
      "/copilot": { target: API_TARGET, changeOrigin: true },
```

- [ ] **Step 2: Write the failing tests** — create `src/desk/mode.test.ts`:

```ts
import { describe, it, expect, beforeEach, vi } from "vitest";
import { loadMode, saveMode } from "./mode";

describe("console mode persistence", () => {
  beforeEach(() => localStorage.clear());

  it("defaults to desk", () => {
    expect(loadMode()).toBe("desk");
  });

  it("round-trips through localStorage", () => {
    saveMode("classic");
    expect(loadMode()).toBe("classic");
  });

  it("ignores garbage values", () => {
    localStorage.setItem("mia.consoleMode", "banana");
    expect(loadMode()).toBe("desk");
  });

  it("survives a throwing storage", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadMode()).toBe("desk");
    expect(() => saveMode("classic")).not.toThrow();
    spy.mockRestore();
  });
});
```

Replace `src/App.test.tsx` with:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// CopilotKit needs a real browser + backend; the desk shell is covered by the
// live pass. Here we only check that App switches between the two layouts.
vi.mock("./desk/DeskView", () => ({
  DeskView: ({ threadId }: { threadId: string }) => <div data-testid="desk-view">{threadId}</div>,
}));

import App from "./App";

describe("App", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "ok", version: "1.2.3" }),
    }));
  });

  it("opens in Market Desk mode by default", () => {
    render(<App />);
    expect(screen.getByTestId("desk-view")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/ask the agent/i)).not.toBeInTheDocument();
  });

  it("switches to Classic, shows the classic chat, and remembers it", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<App />);
    await user.click(screen.getByRole("button", { name: "Classic" }));
    expect(screen.getByText(/MIA · Dev Console/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/ask the agent/i)).toBeInTheDocument();
    expect(screen.queryByTestId("desk-view")).not.toBeInTheDocument();
    unmount();

    render(<App />);
    expect(screen.getByPlaceholderText(/ask the agent/i)).toBeInTheDocument();
  });

  it("New session gives the desk a new thread id", async () => {
    const user = userEvent.setup();
    render(<App />);
    const before = screen.getByTestId("desk-view").textContent;
    await user.click(screen.getByRole("button", { name: /new session/i }));
    expect(screen.getByTestId("desk-view").textContent).not.toBe(before);
  });
});
```

- [ ] **Step 3: Run, expect FAIL**

Run: `npm test`
Expected: FAIL — `./mode` and `./desk/DeskView` cannot be resolved.

- [ ] **Step 4: Implement**

`src/desk/constants.ts`:

```ts
// AG-UI agent id registered with CopilotKit. Every CopilotKit hook/component
// must pass it, otherwise CopilotKit looks for "default" and fails.
export const MARKET_DESK_AGENT_ID = "market_desk";
export const MARKET_DESK_URL = "/copilot/market-desk";
```

`src/desk/mode.ts`:

```ts
export type ConsoleMode = "desk" | "classic";

const KEY = "mia.consoleMode";

export function loadMode(): ConsoleMode {
  try {
    return localStorage.getItem(KEY) === "classic" ? "classic" : "desk";
  } catch {
    return "desk";
  }
}

export function saveMode(mode: ConsoleMode): void {
  try {
    localStorage.setItem(KEY, mode);
  } catch {
    // Storage blocked (private window): the toggle still works for this tab.
  }
}
```

`src/desk/DeskView.tsx`:

```tsx
import { useMemo } from "react";
import { CopilotChat, CopilotKitProvider, HttpAgent } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { MARKET_DESK_AGENT_ID, MARKET_DESK_URL } from "./constants";

// Market Desk: CopilotKit v2 talking AG-UI straight to FastAPI (no runtime).
// Remounted per thread by App (key={threadId}), so New session starts clean.
export function DeskView({ threadId }: { threadId: string }) {
  const agent = useMemo(() => new HttpAgent({ url: MARKET_DESK_URL }), []);
  return (
    <CopilotKitProvider
      agentId={MARKET_DESK_AGENT_ID}
      agents__unsafe_dev_only={{ [MARKET_DESK_AGENT_ID]: agent }}
      showDevConsole={false}
    >
      <DeskBody threadId={threadId} />
    </CopilotKitProvider>
  );
}

function DeskBody({ threadId }: { threadId: string }) {
  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <CopilotChat agentId={MARKET_DESK_AGENT_ID} threadId={threadId} className="h-full" />
      </main>
    </div>
  );
}
```

`src/components/Header.tsx` — extend props and add the toggle before the session pill:

```tsx
import type { ConsoleMode } from "../desk/mode";

interface HeaderProps {
  threadId: string;
  onNewSession: () => void;
  mode: ConsoleMode;
  onModeChange: (mode: ConsoleMode) => void;
}

export function Header({ threadId, onNewSession, mode, onModeChange }: HeaderProps) {
```

and inside the right-hand `<div className="flex items-center gap-3">`, first child:

```tsx
        <div className="flex overflow-hidden rounded border border-terminal-border">
          {(["desk", "classic"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => onModeChange(m)}
              className={`px-2.5 py-1 font-mono text-xs transition-colors ${
                mode === m
                  ? "bg-terminal-accent/15 text-terminal-accent"
                  : "bg-terminal-bg text-terminal-muted hover:text-terminal-text"
              }`}
            >
              {m === "desk" ? "Market Desk" : "Classic"}
            </button>
          ))}
        </div>
```

`src/App.tsx`:
- Imports: `import { DeskView } from "./desk/DeskView"; import { loadMode, saveMode, type ConsoleMode } from "./desk/mode";`
- State: `const [mode, setMode] = useState<ConsoleMode>(loadMode);` and

```tsx
  function onModeChange(next: ConsoleMode) {
    setMode(next);
    saveMode(next);
  }
```

- Header: `<Header threadId={threadId} onNewSession={onNewSession} mode={mode} onModeChange={onModeChange} />`
- Wrap the existing main-content `<div className="flex min-h-0 flex-1">…</div>` (chat column + `ActivityRail`) as the classic branch:

```tsx
      {mode === "desk" ? (
        <DeskView key={threadId} threadId={threadId} />
      ) : (
        <div className="flex min-h-0 flex-1">
          {/* …existing classic markup unchanged… */}
        </div>
      )}
```

(The classic markup is moved verbatim inside the `else` branch; nothing inside it changes.)

- [ ] **Step 5: Run, expect PASS**

Run: `npm test && npx tsc -b`
Expected: all Vitest tests PASS (existing `sse.test.ts`, `ApprovalCard.test.tsx` included); `tsc` exits 0.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/desk frontend/src/components/Header.tsx frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(frontend): Market Desk mode shell with CopilotKit v2 and mode toggle"
```

---

### Task 5: Live activity rail

**Files:**
- Create: `frontend/src/desk/activity.ts`, `frontend/src/desk/DeskActivityRail.tsx`
- Modify: `frontend/src/desk/DeskView.tsx` (mount the rail)
- Test: `frontend/src/desk/activity.test.ts`

**Interfaces:**
- Consumes: `MARKET_DESK_AGENT_ID` (Task 4).
- Produces:

```ts
export type SpecialistLabel = "RAG" | "FINANCE" | "PORTFOLIO" | "BROWSER" | "EMAIL" | "FILES" | "MEMORY";
export type DeskActivity =
  | { kind: "specialist"; id: string; ts: number; label: SpecialistLabel }
  | { kind: "tool"; id: string; ts: number; toolCallId: string; name: string; status: "running" | "done"; durationMs?: number }
  | { kind: "awaiting"; id: string; ts: number }
  | { kind: "done"; id: string; ts: number; totalTokens: number | null }
  | { kind: "error"; id: string; ts: number; message: string };
export interface AgUiEvent { type: string; [key: string]: unknown }
export function reduceActivity(items: DeskActivity[], event: AgUiEvent, now: number): DeskActivity[];
```

The spec's "pure mapper `toActivity(event)`" becomes a pure reducer, because a `TOOL_CALL_END` must update the row its `TOOL_CALL_START` created (to compute the duration).

- [ ] **Step 1: Write the failing tests** — create `src/desk/activity.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { reduceActivity, type AgUiEvent, type DeskActivity } from "./activity";

function run(events: AgUiEvent[], start = 1000, step = 100): DeskActivity[] {
  return events.reduce<DeskActivity[]>((acc, e, i) => reduceActivity(acc, e, start + i * step), []);
}

describe("reduceActivity", () => {
  it("maps each specialist node to its badge", () => {
    const names: Array<[string, string]> = [
      ["rag_agent", "RAG"], ["finance_agent", "FINANCE"], ["portfolio_agent", "PORTFOLIO"],
      ["browser_agent", "BROWSER"], ["email_agent", "EMAIL"], ["filesystem_agent", "FILES"],
      ["memory_agent", "MEMORY"],
    ];
    for (const [stepName, label] of names) {
      const [row] = run([{ type: "STEP_STARTED", stepName }]);
      expect(row).toMatchObject({ kind: "specialist", label });
    }
  });

  it("ignores supervisor, middleware and internal steps", () => {
    const rows = run([
      { type: "STEP_STARTED", stepName: "record_question" },
      { type: "STEP_STARTED", stepName: "supervisor" },
      { type: "STEP_STARTED", stepName: "model" },
      { type: "STEP_STARTED", stepName: "tools" },
      { type: "STEP_STARTED", stepName: "SummarizationMiddleware.before_model" },
      { type: "TEXT_MESSAGE_CONTENT", delta: "hi" },
    ]);
    expect(rows).toEqual([]);
  });

  it("tracks a tool call with its duration", () => {
    const rows = run([
      { type: "TOOL_CALL_START", toolCallId: "c1", toolCallName: "portfolio_metrics" },
      { type: "TOOL_CALL_ARGS", toolCallId: "c1", delta: "{}" },
      { type: "TOOL_CALL_END", toolCallId: "c1" },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ kind: "tool", name: "portfolio_metrics", status: "done", durationMs: 200 });
  });

  it("an end for an unknown tool call changes nothing", () => {
    expect(run([{ type: "TOOL_CALL_END", toolCallId: "nope" }])).toEqual([]);
  });

  it("RUN_FINISHED with an interrupt outcome becomes an awaiting row", () => {
    const [row] = run([{ type: "RUN_FINISHED", outcome: { type: "interrupt", interrupts: [] } }]);
    expect(row.kind).toBe("awaiting");
  });

  it("RUN_FINISHED becomes a done row with total tokens", () => {
    expect(run([{ type: "RUN_FINISHED", usage: { totalTokens: 1234 } }])[0])
      .toMatchObject({ kind: "done", totalTokens: 1234 });
    expect(run([{ type: "RUN_FINISHED", usage: { inputTokens: 10, outputTokens: 5 } }])[0])
      .toMatchObject({ kind: "done", totalTokens: 15 });
    expect(run([{ type: "RUN_FINISHED" }])[0]).toMatchObject({ kind: "done", totalTokens: null });
  });

  it("RUN_ERROR becomes an error row", () => {
    const [row] = run([{ type: "RUN_ERROR", message: "boom" }]);
    expect(row).toMatchObject({ kind: "error", message: "boom" });
  });

  it("does not mutate its input", () => {
    const before: DeskActivity[] = [];
    reduceActivity(before, { type: "STEP_STARTED", stepName: "rag_agent" }, 1);
    expect(before).toEqual([]);
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

Run: `npm test -- activity`
Expected: FAIL — cannot resolve `./activity`.

- [ ] **Step 3: Implement** — create `src/desk/activity.ts`:

```ts
// Pure AG-UI event → activity-row reducer for the Market Desk rail.

export type SpecialistLabel = "RAG" | "FINANCE" | "PORTFOLIO" | "BROWSER" | "EMAIL" | "FILES" | "MEMORY";

export type DeskActivity =
  | { kind: "specialist"; id: string; ts: number; label: SpecialistLabel }
  | { kind: "tool"; id: string; ts: number; toolCallId: string; name: string; status: "running" | "done"; durationMs?: number }
  | { kind: "awaiting"; id: string; ts: number }
  | { kind: "done"; id: string; ts: number; totalTokens: number | null }
  | { kind: "error"; id: string; ts: number; message: string };

export interface AgUiEvent {
  type: string;
  [key: string]: unknown;
}

const SPECIALISTS: Record<string, SpecialistLabel> = {
  rag_agent: "RAG",
  finance_agent: "FINANCE",
  portfolio_agent: "PORTFOLIO",
  browser_agent: "BROWSER",
  email_agent: "EMAIL",
  filesystem_agent: "FILES",
  memory_agent: "MEMORY",
};

function readTotalTokens(usage: unknown): number | null {
  if (!usage || typeof usage !== "object") return null;
  const u = usage as Record<string, unknown>;
  const num = (v: unknown) => (typeof v === "number" ? v : undefined);
  const total = num(u.totalTokens) ?? num(u.total_tokens);
  if (total !== undefined) return total;
  const input = num(u.inputTokens) ?? num(u.input_tokens);
  const output = num(u.outputTokens) ?? num(u.output_tokens);
  return input !== undefined || output !== undefined ? (input ?? 0) + (output ?? 0) : null;
}

export function reduceActivity(items: DeskActivity[], event: AgUiEvent, now: number): DeskActivity[] {
  const id = `${event.type}-${now}-${items.length}`;
  switch (event.type) {
    case "STEP_STARTED": {
      const label = SPECIALISTS[String(event.stepName)];
      return label ? [...items, { kind: "specialist", id, ts: now, label }] : items;
    }
    case "TOOL_CALL_START":
      return [
        ...items,
        { kind: "tool", id, ts: now, toolCallId: String(event.toolCallId),
          name: String(event.toolCallName), status: "running" },
      ];
    case "TOOL_CALL_END":
      return items.map((it) =>
        it.kind === "tool" && it.toolCallId === event.toolCallId && it.status === "running"
          ? { ...it, status: "done", durationMs: now - it.ts }
          : it,
      );
    case "RUN_FINISHED": {
      const outcome = event.outcome as { type?: string } | undefined;
      if (outcome?.type === "interrupt") return [...items, { kind: "awaiting", id, ts: now }];
      return [...items, { kind: "done", id, ts: now, totalTokens: readTotalTokens(event.usage) }];
    }
    case "RUN_ERROR":
      return [...items, { kind: "error", id, ts: now, message: String(event.message ?? "Run failed") }];
    default:
      return items;
  }
}
```

- [ ] **Step 4: Run, expect PASS**

Run: `npm test -- activity`
Expected: 8 PASS.

- [ ] **Step 5: The rail component** — create `src/desk/DeskActivityRail.tsx` (styling mirrors `components/ActivityRail.tsx`):

```tsx
import { useEffect, useState } from "react";
import { useAgent } from "@copilotkit/react-core/v2";
import { MARKET_DESK_AGENT_ID } from "./constants";
import { reduceActivity, type AgUiEvent, type DeskActivity } from "./activity";

const LABEL_COLOR: Record<string, string> = {
  RAG: "text-sky-400",
  FINANCE: "text-amber-400",
  PORTFOLIO: "text-terminal-accent",
  BROWSER: "text-violet-400",
  EMAIL: "text-pink-400",
  FILES: "text-teal-400",
  MEMORY: "text-indigo-400",
};

function time(ts: number) {
  return new Date(ts).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function Row({ item }: { item: DeskActivity }) {
  let body;
  switch (item.kind) {
    case "specialist":
      body = (
        <span className={`rounded bg-black/30 px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-wider ${LABEL_COLOR[item.label]}`}>
          {item.label}
        </span>
      );
      break;
    case "tool":
      body = (
        <span className="rounded border border-terminal-border bg-terminal-bg px-1 py-0.5 font-mono text-[9px] text-terminal-muted">
          {item.name.replace(/^yfinance_/, "yf:")}
          {item.status === "running" ? " …" : ` · ${item.durationMs} ms`}
        </span>
      );
      break;
    case "awaiting":
      body = <span className="font-mono text-[10px] text-terminal-warn">awaiting approval</span>;
      break;
    case "done":
      body = (
        <span className="font-mono text-[10px] text-terminal-accent">
          done{item.totalTokens !== null ? ` · ${item.totalTokens} tokens` : ""}
        </span>
      );
      break;
    case "error":
      body = <span className="font-mono text-[10px] text-terminal-danger">error · {item.message}</span>;
      break;
  }
  return (
    <div className="animate-slide-in-right mb-2.5 flex items-center justify-between gap-2 border-l-2 border-terminal-border/50 pl-2.5">
      {body}
      <span className="font-mono text-[9px] tabular-nums text-terminal-muted">{time(item.ts)}</span>
    </div>
  );
}

export function DeskActivityRail({ threadId }: { threadId: string }) {
  const { agent } = useAgent({ agentId: MARKET_DESK_AGENT_ID, threadId });
  const [items, setItems] = useState<DeskActivity[]>([]);

  useEffect(() => {
    const sub = agent.subscribe({
      onEvent: ({ event }) => {
        setItems((prev) => reduceActivity(prev, event as unknown as AgUiEvent, Date.now()));
      },
    });
    return () => sub.unsubscribe();
  }, [agent]);

  return (
    <aside className="flex h-full w-64 flex-none flex-col border-l border-terminal-border bg-terminal-panel">
      <div className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-terminal-muted">Agent activity</span>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        {items.length === 0 ? (
          <div className="pt-6 text-center font-mono text-[10px] text-terminal-muted">idle</div>
        ) : (
          items.map((it) => <Row key={it.id} item={it} />)
        )}
      </div>
    </aside>
  );
}
```

In `DeskView.tsx`, import `DeskActivityRail` and add it as the last child of `DeskBody`'s outer `div`, after `</main>`:

```tsx
      <DeskActivityRail threadId={threadId} />
```

- [ ] **Step 6: Run, expect PASS**

Run: `npm test && npx tsc -b`
Expected: all PASS, `tsc` exit 0. If `tsc` rejects `onEvent`'s parameter type, keep the `as unknown as AgUiEvent` cast and type the callback parameter as `{ event: unknown }`; do not add `any`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/desk/activity.ts frontend/src/desk/activity.test.ts frontend/src/desk/DeskActivityRail.tsx frontend/src/desk/DeskView.tsx
git commit -m "feat(frontend): Market Desk live activity rail"
```

---

### Task 6: Approval cards

**Files:**
- Create: `frontend/src/desk/approvals.ts`, `frontend/src/desk/ApprovalPanel.tsx`, `frontend/src/desk/useDeskInterrupt.tsx`
- Modify: `frontend/src/desk/DeskView.tsx` (call the hook)
- Test: `frontend/src/desk/approvals.test.ts`, `frontend/src/desk/ApprovalPanel.test.tsx`

**Interfaces:**
- Consumes: `MARKET_DESK_AGENT_ID` (Task 4).
- Produces:

```ts
// approvals.ts
export type DecisionType = "approve" | "edit" | "reject";
export interface ActionRequest { name: string; args: Record<string, unknown>; description?: string }
export type Decision =
  | { type: "approve" }
  | { type: "edit"; edited_action: { name: string; args: Record<string, unknown> } }
  | { type: "reject"; message?: string };
export interface PendingApproval { requests: ActionRequest[]; allowed: DecisionType[][] }
export const EDITABLE_FIELDS: Record<string, string[]>;
export function readApproval(interrupt: unknown): PendingApproval;
// ApprovalPanel.tsx
export function ApprovalPanel(props: { approval: PendingApproval; onSubmit: (d: Decision[]) => void; onCancel: () => void }): JSX.Element;
// useDeskInterrupt.tsx
export function useDeskInterrupt(): void;
```

- [ ] **Step 1: Write the failing tests**

`src/desk/approvals.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { readApproval } from "./approvals";

const email = { name: "send_email", args: { recipient: "a@x.com", subject: "Hi", body: "B" } };

function interrupt(raw: unknown) {
  return { id: "i1", reason: "langgraph:interrupt", metadata: { langgraph: { raw } } };
}

describe("readApproval", () => {
  it("reads action requests and their allowed decisions", () => {
    const got = readApproval(interrupt({
      action_requests: [email],
      review_configs: [{ action_name: "send_email", allowed_decisions: ["approve", "reject"] }],
    }));
    expect(got.requests).toEqual([email]);
    expect(got.allowed).toEqual([["approve", "reject"]]);
  });

  it("defaults to all three decisions when no config matches", () => {
    const got = readApproval(interrupt({ action_requests: [email] }));
    expect(got.allowed).toEqual([["approve", "edit", "reject"]]);
  });

  it("returns no requests for a malformed interrupt", () => {
    expect(readApproval(null).requests).toEqual([]);
    expect(readApproval(interrupt({ foo: 1 })).requests).toEqual([]);
    expect(readApproval(interrupt({ action_requests: [{ nope: true }] })).requests).toEqual([]);
  });
});
```

`src/desk/ApprovalPanel.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalPanel } from "./ApprovalPanel";
import type { PendingApproval } from "./approvals";

const ALL = ["approve", "edit", "reject"] as const;
const email = { name: "send_email", args: { recipient: "a@x.com", subject: "Hi", body: "Body" } };
const file = { name: "write_file", args: { path: "notes.md", content: "text" } };
const memory = { name: "save_memory", args: { key: "risk", value: "low" } };
const other = { name: "mystery_tool", args: { x: 1 } };

function setup(approval: PendingApproval) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  render(<ApprovalPanel approval={approval} onSubmit={onSubmit} onCancel={onCancel} />);
  return { onSubmit, onCancel, user: userEvent.setup() };
}

describe("ApprovalPanel", () => {
  it.each([
    [email, ["recipient", "subject", "body"]],
    [file, ["path", "content"]],
    [memory, ["key", "value"]],
  ])("shows the fields of %s", (req, fields) => {
    setup({ requests: [req], allowed: [[...ALL]] });
    for (const f of fields) expect(screen.getByLabelText(f)).toBeInTheDocument();
  });

  it("shows raw JSON and no Edit for an unknown tool", () => {
    setup({ requests: [other], allowed: [[...ALL]] });
    expect(screen.getByText(/"x": 1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("Approve submits an approve decision", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(onSubmit).toHaveBeenCalledWith([{ type: "approve" }]);
  });

  it("Edit then Send edited submits the edited args", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const subject = screen.getByLabelText("subject");
    await user.clear(subject);
    await user.type(subject, "Weekly report");
    await user.click(screen.getByRole("button", { name: "Send edited" }));
    expect(onSubmit).toHaveBeenCalledWith([
      { type: "edit", edited_action: { name: "send_email", args: { ...email.args, subject: "Weekly report" } } },
    ]);
  });

  it("Reject without a reason submits a bare reject", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.click(screen.getByRole("button", { name: "Confirm reject" }));
    expect(onSubmit).toHaveBeenCalledWith([{ type: "reject" }]);
  });

  it("Reject with a reason carries the message", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.type(screen.getByLabelText("reason"), "not now");
    await user.click(screen.getByRole("button", { name: "Confirm reject" }));
    expect(onSubmit).toHaveBeenCalledWith([{ type: "reject", message: "not now" }]);
  });

  it("waits for every request, then submits decisions in request order", async () => {
    const { user, onSubmit } = setup({ requests: [email, file], allowed: [[...ALL], [...ALL]] });
    const approves = screen.getAllByRole("button", { name: "Approve" });
    await user.click(approves[1]); // decide the second one first
    expect(onSubmit).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.click(screen.getByRole("button", { name: "Confirm reject" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith([{ type: "reject" }, { type: "approve" }]);
  });

  it("submits once even when clicked twice", () => {
    const { onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    const approve = screen.getByRole("button", { name: "Approve" });
    // fireEvent (not user-event): dispatches even if the button was already
    // removed by the first click, which is exactly the race we guard against.
    fireEvent.click(approve);
    fireEvent.click(approve);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("hides buttons the review config does not allow", () => {
    setup({ requests: [email], allowed: [["approve", "reject"]] });
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("renders a cancel-only card when there are no requests", async () => {
    const { user, onCancel, onSubmit } = setup({ requests: [], allowed: [] });
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

Run: `npm test -- approvals ApprovalPanel`
Expected: FAIL — cannot resolve `./approvals` / `./ApprovalPanel`.

- [ ] **Step 3: Implement `approvals.ts`**

```ts
// Reading HumanInTheLoopMiddleware interrupts as surfaced by ag-ui-langgraph:
// interrupt.metadata.langgraph.raw = {action_requests, review_configs}.

export type DecisionType = "approve" | "edit" | "reject";

export interface ActionRequest {
  name: string;
  args: Record<string, unknown>;
  description?: string;
}

export type Decision =
  | { type: "approve" }
  | { type: "edit"; edited_action: { name: string; args: Record<string, unknown> } }
  | { type: "reject"; message?: string };

export interface PendingApproval {
  requests: ActionRequest[];
  allowed: DecisionType[][];
}

export const EDITABLE_FIELDS: Record<string, string[]> = {
  send_email: ["recipient", "subject", "body"],
  write_file: ["path", "content"],
  save_memory: ["key", "value"],
};

const ALL: DecisionType[] = ["approve", "edit", "reject"];

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function readApproval(interrupt: unknown): PendingApproval {
  const raw = isRecord(interrupt) && isRecord(interrupt.metadata) && isRecord(interrupt.metadata.langgraph)
    ? interrupt.metadata.langgraph.raw
    : undefined;
  if (!isRecord(raw) || !Array.isArray(raw.action_requests)) return { requests: [], allowed: [] };

  const requests = raw.action_requests.filter(
    (r): r is ActionRequest => isRecord(r) && typeof r.name === "string" && isRecord(r.args),
  );
  const configs = Array.isArray(raw.review_configs) ? raw.review_configs.filter(isRecord) : [];
  const allowed = requests.map((r) => {
    const cfg = configs.find((c) => c.action_name === r.name);
    const list = Array.isArray(cfg?.allowed_decisions)
      ? cfg.allowed_decisions.filter((d): d is DecisionType => ALL.includes(d as DecisionType))
      : [];
    return list.length ? list : [...ALL];
  });
  return { requests, allowed };
}
```

- [ ] **Step 4: Implement `ApprovalPanel.tsx`**

```tsx
import { useRef, useState } from "react";
import { EDITABLE_FIELDS, type ActionRequest, type Decision, type DecisionType, type PendingApproval } from "./approvals";

interface Props {
  approval: PendingApproval;
  onSubmit: (decisions: Decision[]) => void;
  onCancel: () => void;
}

const btn = "rounded border px-3 py-1 font-mono text-xs transition-colors disabled:opacity-40";

export function ApprovalPanel({ approval, onSubmit, onCancel }: Props) {
  const [decisions, setDecisions] = useState<(Decision | undefined)[]>(() => approval.requests.map(() => undefined));
  const submitted = useRef(false);

  function decide(index: number, decision: Decision) {
    if (submitted.current) return;
    const next = [...decisions];
    next[index] = decision;
    setDecisions(next);
    if (next.every((d) => d !== undefined)) {
      submitted.current = true;
      onSubmit(next as Decision[]);
    }
  }

  if (approval.requests.length === 0) {
    return (
      <div className="rounded-xl border border-terminal-warn/40 bg-terminal-panel p-3 font-mono text-xs text-terminal-text">
        <p className="mb-2">The agent paused with a request this console can't display.</p>
        <button
          type="button"
          className={`${btn} border-terminal-danger/50 text-terminal-danger`}
          onClick={() => {
            if (submitted.current) return;
            submitted.current = true;
            onCancel();
          }}
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {approval.requests.map((req, i) => (
        <RequestCard
          key={i}
          request={req}
          allowed={approval.allowed[i] ?? ["approve", "edit", "reject"]}
          decided={decisions[i]}
          onDecide={(d) => decide(i, d)}
        />
      ))}
    </div>
  );
}

function RequestCard({ request, allowed, decided, onDecide }: {
  request: ActionRequest;
  allowed: DecisionType[];
  decided: Decision | undefined;
  onDecide: (d: Decision) => void;
}) {
  const fields = EDITABLE_FIELDS[request.name];
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries((fields ?? []).map((f) => [f, String(request.args[f] ?? "")])),
  );
  const can = (d: DecisionType) => allowed.includes(d);
  const locked = decided !== undefined;

  return (
    <div className="rounded-xl border border-terminal-warn/40 bg-terminal-panel p-3 font-mono text-xs text-terminal-text">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-semibold text-terminal-warn">{request.name}</span>
        {locked && <span className="text-terminal-muted">{decided.type}</span>}
      </div>

      {fields ? (
        <div className="flex flex-col gap-1.5">
          {fields.map((f) => {
            const multiline = f === "body" || f === "content";
            const common = {
              id: `${request.name}-${f}`,
              "aria-label": f,
              value: values[f],
              readOnly: !editing || locked,
              onChange: (e: { target: { value: string } }) => setValues({ ...values, [f]: e.target.value }),
              className: "w-full rounded border border-terminal-border bg-terminal-bg px-2 py-1 text-terminal-text read-only:opacity-80",
            };
            return (
              <label key={f} className="flex flex-col gap-0.5">
                <span className="text-[10px] uppercase text-terminal-muted">{f}</span>
                {multiline ? <textarea rows={4} {...common} /> : <input {...common} />}
              </label>
            );
          })}
        </div>
      ) : (
        <pre className="overflow-x-auto rounded bg-terminal-bg p-2 text-[11px]">{JSON.stringify(request.args, null, 2)}</pre>
      )}

      {rejecting && !locked && (
        <label className="mt-2 flex flex-col gap-0.5">
          <span className="text-[10px] uppercase text-terminal-muted">reason (optional)</span>
          <input
            aria-label="reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="rounded border border-terminal-border bg-terminal-bg px-2 py-1"
          />
        </label>
      )}

      {!locked && (
        <div className="mt-2 flex gap-2">
          {can("approve") && !editing && !rejecting && (
            <button type="button" className={`${btn} border-terminal-accent/50 text-terminal-accent`} onClick={() => onDecide({ type: "approve" })}>
              Approve
            </button>
          )}
          {can("edit") && fields && !editing && !rejecting && (
            <button type="button" className={`${btn} border-terminal-border text-terminal-text`} onClick={() => setEditing(true)}>
              Edit
            </button>
          )}
          {editing && (
            <button
              type="button"
              className={`${btn} border-terminal-accent/50 text-terminal-accent`}
              onClick={() => onDecide({ type: "edit", edited_action: { name: request.name, args: { ...request.args, ...values } } })}
            >
              Send edited
            </button>
          )}
          {can("reject") && !editing && !rejecting && (
            <button type="button" className={`${btn} border-terminal-danger/50 text-terminal-danger`} onClick={() => setRejecting(true)}>
              Reject
            </button>
          )}
          {rejecting && (
            <button
              type="button"
              className={`${btn} border-terminal-danger/50 text-terminal-danger`}
              onClick={() => onDecide(reason.trim() ? { type: "reject", message: reason.trim() } : { type: "reject" })}
            >
              Confirm reject
            </button>
          )}
        </div>
      )}
    </div>
  );
}
```

Note: `locked` removes the buttons after a card is decided, and `submitted` blocks a second `onSubmit`; together they cover the double-click case.

- [ ] **Step 5: Run, expect PASS**

Run: `npm test -- approvals ApprovalPanel`
Expected: 3 + 12 PASS.

- [ ] **Step 6: CopilotKit glue** — create `src/desk/useDeskInterrupt.tsx`:

```tsx
import { useInterrupt } from "@copilotkit/react-core/v2";
import { MARKET_DESK_AGENT_ID } from "./constants";
import { ApprovalPanel } from "./ApprovalPanel";
import { readApproval } from "./approvals";

// Renders HITL approval cards inside CopilotChat and resumes the graph with
// HumanInTheLoopMiddleware's {decisions: [...]} payload.
export function useDeskInterrupt(): void {
  useInterrupt({
    agentId: MARKET_DESK_AGENT_ID,
    render: ({ interrupt, resolve, cancel }) => (
      <ApprovalPanel
        approval={readApproval(interrupt)}
        onSubmit={(decisions) => void resolve({ decisions })}
        onCancel={() => void cancel()}
      />
    ),
  });
}
```

In `DeskView.tsx`, import it and call `useDeskInterrupt();` as the first line of `DeskBody` (it must run inside `CopilotKitProvider`).

- [ ] **Step 7: Full frontend check**

Run: `npm test && npx tsc -b && npm run build`
Expected: all tests PASS, type-check and build succeed.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/desk
git commit -m "feat(frontend): Market Desk approval cards (approve / edit / reject)"
```

---

### Task 7: Live pass (one run, end of branch)

**Files:** none changed unless a bug is found (then: fix with a regression test, separate commit).

- [ ] **Step 1: Start the stack** (two background shells from `market-intelligence-agent/`, with `COPILOT_ENABLED=true` in `.env`):

```bash
uv run uvicorn app.api.server:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev
```

Check: `curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:8000/copilot/market-desk -H "content-type: application/json" -d "{}"` returns `422` (route exists, body invalid) — not `404`.

- [ ] **Step 2: Playwright-driven browser run** on `http://localhost:5173` (Market Desk is the default mode):
  1. Ask "What is the total value of Sarah Levi's portfolio?" (a client from `customers.db`; pick any name from `SELECT name FROM clients LIMIT 1` if that one doesn't exist). Expected: the rail shows **PORTFOLIO** and at least one tool row with a duration, the answer streams into the chat, the rail ends with a **done · N tokens** row, and no `{"next": ...}` JSON appears in the chat.
  2. Ask "Email that client a one-line summary of their portfolio." Expected: an approval card for `send_email` with recipient / subject / body; click **Reject** → **Confirm reject**. The rail shows **awaiting approval**, then the run continues; no email is sent (backend log shows no SES/simulated send).
  3. Toggle **Classic** in the header: the old console appears and works; reload: Classic is remembered. Toggle back.
  4. Check the browser console for `Agent 'default' not found` — must be absent.
- [ ] **Step 3:** Save 2 screenshots (desk answer, approval card) under the scratchpad and report results in plain words. If CopilotKit's stylesheet visibly breaks the Tailwind layout, note it — fixing it is a follow-up, not a blocker.
- [ ] **Step 4:** Update memory (`project_copilotkit_roadmap.md`: sub-project 1 status) and stop. Do NOT push, do NOT open a PR unless the user asks.
