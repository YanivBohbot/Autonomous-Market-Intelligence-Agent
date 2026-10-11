# Multi-Agent Cutover Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the validated cutover behavior onto the modernized product branch so `/stream`, AgentCore, CopilotKit Research, and the later Research voice feature all use one compiled multi-agent graph with correct nested HITL handling.

**Architecture:** Keep the modernized branch as the source of truth. Reimplement the small cutover contracts with tests instead of merging the divergent cutover branch. FastAPI compiles one `build_multi_agent_app` instance, wraps that instance for AG-UI, and exposes it directly to the legacy SSE and AgentCore adapters. Nested specialist interrupts are inspected recursively and resumed with HumanInTheLoopMiddleware's `{"decisions": [...]}` payload.

**Tech Stack:** Python 3.12, FastAPI, LangGraph, LangChain HumanInTheLoopMiddleware, AG-UI, CopilotKit v2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-multi-agent-voice-research-design.md` (Delivery Dependency) and `docs/superpowers/specs/2026-09-15-multi-agent-api-cutover-design.md` (historical evidence only).

## Global Constraints

- Do not merge or cherry-pick `worktree-multi-agent-api-cutover`; it predates the product UI, client data, reports, and attachment work.
- Preserve `/copilot/market-desk`, uploads, generated-report attachment selection, and all modernized frontend files.
- Preserve `app.state.voice_agent_app` for `/classic` until the dependent voice plan is complete.
- Do not delete `app/agent/graph.py`; shared single-agent helpers and Classic voice still import it.
- Use official multi-agent HITL decisions. A boolean approval expands to one decision per pending action.
- Do not add or remove tools, so `docs/TOOLS.md` is unchanged.
- Run Python commands from the application root with the project-local UV cache and the main checkout virtual environment.

## Review Focus

- A pending tool call must be read from the paused specialist snapshot, never from stale top-level messages.
- `app.state.agent_app` and `app.state.market_desk_agent.graph` must be the same object.
- Existing `/stream`, `/approve`, and `/invocations` wire shapes remain backward compatible.
- No modern UI or data endpoint may disappear during the port.

---

### Task 1: Add recursive specialist-state inspection

**Files:**
- Create: `tests/unit/test_api_helpers.py`
- Modify: `app/api/routers/_helpers.py`

**Interfaces:**
- Produces `PendingGraphInterrupt(interrupt_id, value, last_message)`.
- Produces `pending_interrupt_from_snapshot(snapshot)` and `pending_action_count(pending)` for every transport adapter.

- [ ] **Step 1: Write the failing recursive-state tests**

Create snapshots with `langgraph.types.StateSnapshot`: one top-level snapshot containing a task whose `state` is another snapshot, and one direct snapshot. Assert that the helper returns the nested interrupt id, its raw `action_requests`, and the nested `AIMessage` with the pending tool call. Add an empty-state case returning `None`.

```python
def test_pending_interrupt_comes_from_nested_specialist():
    pending = pending_interrupt_from_snapshot(_parent_with_email_interrupt())
    assert pending is not None
    assert pending.interrupt_id == "interrupt-email-1"
    assert pending.value["action_requests"][0]["name"] == "send_email"
    assert pending.last_message.tool_calls[0]["name"] == "send_email"


def test_pending_action_count_defaults_safely():
    assert pending_action_count(PendingGraphInterrupt("i", {}, None)) == 1
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `uv run pytest tests/unit/test_api_helpers.py -v`

Expected: collection fails because the new helper symbols do not exist.

- [ ] **Step 3: Implement the recursive helper**

```python
from dataclasses import dataclass
from typing import Any

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
        return PendingGraphInterrupt(str(interrupt.id), value, messages[-1] if messages else None)
    return None


def pending_action_count(pending: PendingGraphInterrupt) -> int:
    requests = pending.value.get("action_requests")
    return len(requests) if isinstance(requests, list) and requests else 1
```

Keep `get_action_description`; add a raw-action fallback when `last_message` is absent.

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: `uv run pytest tests/unit/test_api_helpers.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/_helpers.py tests/unit/test_api_helpers.py
git commit -m "feat(api): inspect nested multi-agent interrupts"
```

---

### Task 2: Stream nested specialist output through `/stream`

**Files:**
- Modify: `tests/unit/test_stream.py`
- Modify: `app/api/routers/stream.py`

**Interfaces:**
- Consumes LangGraph `astream(..., stream_mode=["updates", "messages"], subgraphs=True)` three-tuples.
- Preserves SSE events `node`, `token`, `screenshot`, `interrupted`, `done`, and `error`.

- [ ] **Step 1: Convert the fake stream to the three-tuple contract**

Make `_FakeAgentApp.astream` accept `subgraphs=False`, assert it becomes `True`, and yield `(namespace, mode, chunk)`. Change token metadata from `generate` to `agent`, add a `synthesize` token case, and construct the interrupted snapshot with a nested HumanInTheLoop interrupt.

```python
def astream(self, inputs, config, stream_mode, subgraphs=False):
    assert subgraphs is True
    async def gen():
        for namespace, update in self._updates:
            yield namespace, "updates", update
        for namespace, token, metadata in self._tokens:
            yield namespace, "messages", (token, metadata)
    return gen()
```

Assert `send_email` is described from the nested specialist and that `done` is not emitted after an interrupt.

- [ ] **Step 2: Run the stream tests and confirm RED**

Run: `uv run pytest tests/unit/test_stream.py -v`

Expected: failures show that `/stream` does not pass `subgraphs=True` and still unpacks two-tuples.

- [ ] **Step 3: Implement nested streaming**

Add `_STREAMABLE_NODES = {"agent", "synthesize"}`. Change the loop to:

```python
async for _namespace, mode, chunk in agent_app.astream(
    inputs,
    config,
    stream_mode=["updates", "messages"],
    subgraphs=True,
):
```

Keep node and screenshot extraction. Emit message chunks only when `meta["langgraph_node"]` belongs to `_STREAMABLE_NODES`. After streaming, call `await agent_app.aget_state(config, subgraphs=True)`, use `pending_interrupt_from_snapshot`, and emit `interrupted` when a pending interrupt exists.

- [ ] **Step 4: Run focused regression tests**

Run: `uv run pytest tests/unit/test_stream.py tests/unit/test_api_helpers.py -v`

Expected: all tests pass, including screenshot and error frames.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/stream.py tests/unit/test_stream.py
git commit -m "feat(stream): surface multi-agent specialist runs"
```

---

### Task 3: Resume official HITL payloads in legacy adapters

**Files:**
- Create: `tests/unit/test_approve.py`
- Modify: `tests/unit/test_agentcore_contract.py`
- Modify: `app/api/routers/approve.py`
- Modify: `app/api/routers/agentcore.py`

**Interfaces:**
- Consumes `PendingGraphInterrupt.value["action_requests"]`.
- Produces `Command(resume={"decisions": [...]})` with exactly one decision per request.

- [ ] **Step 1: Write failing adapter tests**

Use a fake graph that records the received `Command`. Cover approve, reject, expired state, and a second nested interrupt. For AgentCore cover an invalid verdict defaulting to reject.

```python
assert fake.command.resume == {
    "decisions": [{"type": "approve"}, {"type": "approve"}]
}
```

For reject, assert every item is `{"type": "reject", "message": "Rejected by user."}`. Also assert both adapters call `aget_state(config, subgraphs=True)` before and after resume.

- [ ] **Step 2: Run the adapter tests and confirm RED**

Run: `uv run pytest tests/unit/test_approve.py tests/unit/test_agentcore_contract.py -v`

Expected: the fake observes the old string resume value and nested actions cannot be described.

- [ ] **Step 3: Implement one decision-expansion helper in `_helpers.py`**

```python
def boolean_decisions(pending: PendingGraphInterrupt, approved: bool) -> dict[str, list[dict[str, str]]]:
    decision = {"type": "approve"} if approved else {
        "type": "reject",
        "message": "Rejected by user.",
    }
    return {"decisions": [dict(decision) for _ in range(pending_action_count(pending))]}
```

Both routers must obtain the current nested pending interrupt, return the existing expired response when absent, invoke `Command(resume=boolean_decisions(...))`, then inspect the post-resume nested snapshot for another pending action. Preserve all response models and status strings.

- [ ] **Step 4: Run focused HITL suites**

Run: `uv run pytest tests/unit/test_approve.py tests/unit/test_agentcore_contract.py tests/unit/test_multi_agent_hitl.py -v`

Expected: all tests pass and the multi-agent email tool still executes only after approval.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/_helpers.py app/api/routers/approve.py app/api/routers/agentcore.py tests/unit/test_approve.py tests/unit/test_agentcore_contract.py
git commit -m "fix(hitl): resume nested multi-agent actions safely"
```

---

### Task 4: Compile and share one multi-agent graph

**Files:**
- Create: `tests/unit/test_server_wiring.py`
- Modify: `tests/unit/test_copilot_wiring.py`
- Modify: `app/api/routers/copilot.py`
- Modify: `app/api/server.py`

**Interfaces:**
- Changes `build_market_desk_agent(graph)` to wrap an already compiled graph.
- Changes `attach_market_desk(app, graph)` and `setup_market_desk(app, graph)` accordingly.
- Produces identity invariant `app.state.market_desk_agent.graph is app.state.agent_app`.

- [ ] **Step 1: Write the failing identity tests**

In `test_server_wiring.py`, enter the real lifespan with the memory checkpointer and assert the multi-agent node set includes `supervisor`, `rag_agent`, `finance_agent`, `portfolio_agent`, `browser_agent`, `memory_agent`, `filesystem_agent`, and `email_agent`. When Copilot is enabled, assert graph object identity. Update Copilot fixtures to compile their test graph once and pass it to `attach_market_desk`.

- [ ] **Step 2: Run wiring tests and confirm RED**

Run: `uv run pytest tests/unit/test_server_wiring.py tests/unit/test_copilot_wiring.py tests/unit/test_copilot_endpoint.py -v`

Expected: signature and identity assertions fail because Copilot currently compiles a second graph.

- [ ] **Step 3: Refactor the AG-UI wrapper**

```python
def build_market_desk_agent(graph) -> LangGraphAgent:
    return MarketDeskAgent(
        name=MARKET_DESK_AGENT_NAME,
        graph=graph,
        emit_subagent_events=True,
        emit_interrupt_outcome=True,
        enable_legacy_on_interrupt_event=False,
        config={"recursion_limit": RECURSION_LIMIT},
    )


def attach_market_desk(app: FastAPI, graph) -> None:
    app.state.market_desk_agent = build_market_desk_agent(graph)
```

Remove the graph builder import from `copilot.py`.

- [ ] **Step 4: Cut the lifespan over once**

```python
agent_graph = build_multi_agent_app(checkpointer, store)
app.state.agent_app = agent_graph
app.state.voice_agent_app = build_voice_agent_app(checkpointer, store)
setup_market_desk(app, agent_graph)
```

Keep the lazy AG-UI import so the AgentCore image still imports when Copilot dependencies are absent.

- [ ] **Step 5: Run wiring and endpoint regressions**

Run: `uv run pytest tests/unit/test_server_wiring.py tests/unit/test_copilot_wiring.py tests/unit/test_copilot_endpoint.py tests/unit/test_stream.py tests/unit/test_approve.py -v`

Expected: all tests pass and the graph identity assertion is true.

- [ ] **Step 6: Commit**

```bash
git add app/api/server.py app/api/routers/copilot.py tests/unit/test_server_wiring.py tests/unit/test_copilot_wiring.py tests/unit/test_copilot_endpoint.py
git commit -m "feat(server): share the multi-agent graph across transports"
```

---

### Task 5: Preserve routing parity, update architecture docs, and validate cutover

**Files:**
- Modify: `tests/unit/test_multi_agent_supervisor_routing.py`
- Modify: `app/agent/prompts/specialist_agent_prompts.py`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Clarifies that open-ended web-backed research belongs to `rag_agent`; `browser_agent` requires a concrete site or URL.
- Documents `/stream` and AgentCore as multi-agent transports while Classic voice remains temporarily on `voice_agent_app`.

- [ ] **Step 1: Add a failing prompt-contract test**

Patch the supervisor router, call `supervisor_node`, inspect the first `SystemMessage`, and assert it contains both rules:

```python
assert "open-ended" in routing_prompt
assert "concrete URL or named website" in routing_prompt
```

- [ ] **Step 2: Run the routing test and confirm RED**

Run: `uv run pytest tests/unit/test_multi_agent_supervisor_routing.py -v`

Expected: the current prompt lacks the explicit disambiguation.

- [ ] **Step 3: Update only the two specialist descriptions**

State that `rag_agent` owns general knowledge, open-ended lookup, news, weather, and its own web-search fallback. State that `browser_agent` is only for a concrete URL, named website, or already-open page.

- [ ] **Step 4: Update repository architecture text**

Remove claims that `/stream` is single-agent or that multi-agent mode is exclusive to Copilot. Record the one-graph identity and official decision payload. Mark `docs/superpowers/plans/2026-09-15-multi-agent-api-cutover.md` as superseded by this reconciliation plan without deleting the historical document.

- [ ] **Step 5: Run the complete cutover validation**

Run:

```bash
uv run pytest tests/unit/test_api_helpers.py tests/unit/test_stream.py tests/unit/test_approve.py tests/unit/test_agentcore_contract.py tests/unit/test_copilot_wiring.py tests/unit/test_copilot_endpoint.py tests/unit/test_multi_agent_hitl.py tests/unit/test_multi_agent_supervisor_routing.py -v
uv run pytest tests/ -v
```

Expected: focused and complete backend suites pass.

- [ ] **Step 6: Perform live transport smoke tests**

Start FastAPI from this worktree. Verify one finance question and one RAG question through `/stream`, one email or memory interrupt through `/approve`, and one Research turn through `/copilot/market-desk`. Confirm incremental tokens, correct specialist activity, and no duplicate side effect.

- [ ] **Step 7: Commit**

```bash
git add app/agent/prompts/specialist_agent_prompts.py tests/unit/test_multi_agent_supervisor_routing.py AGENTS.md CLAUDE.md docs/superpowers/plans/2026-09-15-multi-agent-api-cutover.md
git commit -m "docs(architecture): record the reconciled multi-agent cutover"
```
