# Single-agent graph → `create_agent` + middleware — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the single-agent graph (`app/agent/graph.py`, `app/voice/graph.py`) on `create_agent` + official middleware, the same way the 7 multi-agent specialists already were, so it shares `base_middleware()` instead of duplicating retry/fallback/summarization logic by hand.

**Architecture:** One new shared factory, `build_single_agent()`, returns a single `create_agent(...)` call carrying every tool and all middleware (including a new `ErrorRecoveryMiddleware` and the official `HumanInTheLoopMiddleware`). Text mode wraps it in a thin outer `StateGraph` (`record_question → single_agent → END`, mirroring the multi-agent supervisor's subgraph-node pattern). Voice mode compiles it directly with no wrapping graph. `app/api/routers/approve.py` and `app/voice/hitl.py` are updated for the new `Command(resume={"decisions": [...]})` shape; `app/api/routers/stream.py` is updated for the new internal node names so token streaming and the `interrupted` SSE event keep working.

**Tech Stack:** LangChain 1.4.2 (`create_agent`, `AgentMiddleware`, `HumanInTheLoopMiddleware`), LangGraph 1.2.12 (`StateGraph`, subgraph-as-node), pytest + `anyio`.

**Spec:** `docs/superpowers/specs/2026-10-02-single-agent-create-agent-migration-design.md`

## Global Constraints

- The external `POST /approve` HTTP contract (`ApproveRequest.approved: bool`, `ChatResponse`) does not change — translation happens inside `approve.py` only.
- Atomic-batch-reject (today: any reject cancels every tool call in the batch, read-only included) is explicitly **dropped**, not replicated. The official `HumanInTheLoopMiddleware` auto-approves non-interrupted tool calls regardless of the decision on interrupted ones in the same batch — this is correct, expected, new behavior, not a bug to fix.
- `ERROR_RECOVERY_PROMPT`'s exact current behavior (full non-tool-bound model call with only `[SystemMessage(ERROR_RECOVERY_PROMPT), HumanMessage(error text)]`, dropping the rest of history) must be preserved exactly via a new middleware.
- One shared agent factory (`build_single_agent()`), not two parallel `create_agent` calls for text and voice.
- `uv run pytest tests/ -q` must be green after every task, not just at the end.
- **Two different node names matter, not one — confirmed empirically before this plan was finalized, do not re-derive or second-guess them:**
  - **Unwrapped** (`build_single_agent()` compiled directly — voice mode): a pending HITL approval shows as `snapshot.next == ("HumanInTheLoopMiddleware.after_model",)`. Verified with a throwaway script building exactly this shape with `FakeToolModel` and a `send_email`-like tool gated by `HumanInTheLoopMiddleware`.
  - **Wrapped** (`single_agent` added as a subgraph node under `app/agent/graph.py`'s outer `StateGraph` — text mode): the SAME pending approval shows as `snapshot.next == ("single_agent",)` instead — the outer graph reports the wrapping node's name, not the inner middleware's. Verified the same way, with the subgraph embedded in a two-node outer `StateGraph` exactly like `app/agent/graph.py`'s real structure.
  - Streamed message metadata (`meta.get("langgraph_node")`) follows the same rule: tokens from inside the wrapped subgraph are tagged `"single_agent"` at the outer level, never the subgraph's internal node names (`"model"`).
  - `approve.py` needs **no node-name check at all** — it only tests `snapshot.next` for truthiness (paused vs not), never a specific name.

## Review Focus

- **Token streaming goes silently dark.** `stream.py`'s `meta.get("langgraph_node") == "generate"` filter must be updated to the real node name `single_agent`'s internal model node uses — if missed, the final answer still arrives (via the `done` event) but word-by-word streaming silently stops with no error anywhere. Task 7 tests this explicitly with a fake token stream.
- **The `interrupted` SSE event silently never fires.** `stream.py`'s `"approval" in snapshot.next` must be updated to the confirmed HITL node name — if missed, a paused side-effect tool call never tells the frontend it's waiting. Task 7 tests this.
- **Voice can never detect a pending approval.** `app/voice/hitl.py`'s `is_interrupted()` has the identical failure mode as stream.py's, independently — it's a separate code path that talks to the graph directly. Task 5 tests this.
- **Error recovery regresses silently.** If `ErrorRecoveryMiddleware`'s trigger condition is even slightly off (wrong `status` check, wrong message position), the model would just see the normal system prompt on a tool error instead of `ERROR_RECOVERY_PROMPT` — no exception, just a worse answer nobody notices in CI. Task 2 tests the exact trigger condition and the exact request shape sent to the model.
- **Mixed-batch reject changes behavior with no test pinning the new behavior.** Since this plan deliberately drops the atomic-reject rule, there must be a test proving the *new* behavior (a read-only call in the same batch executes despite the side-effect call being rejected) exists on purpose — not just the absence of a test for the old rule. Task 2 includes this test.

---

### Task 1: `build_single_agent()` factory (minimal)

**Files:**
- Create: `app/agent/single_agent.py`
- Test: `tests/unit/test_single_agent.py`

**Interfaces:**
- Consumes: `app.agent.middleware.base_middleware`, `app.agent.middleware.specialist_model`, `app.agent.middleware.strip_tool_images`, `app.agent.tools.TOOLS`, `app.agent.tools.is_read_only`, `app.agent.prompts.system.SYSTEM_PROMPT`.
- Produces: `build_single_agent() -> CompiledStateGraph` — a function taking no required arguments (checkpointer/store are optional, added in Task 4). Later tasks (3, 4) call this directly.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_single_agent.py
from app.agent.single_agent import build_single_agent
from app.agent.tools import TOOLS, is_read_only


def test_build_single_agent_registers_every_tool():
    agent = build_single_agent()
    nodes = agent.get_graph().nodes
    # create_agent's own internal model-calling node, confirmed empirically
    # (FakeToolModel + a trivial create_agent call) while writing this plan.
    assert "model" in nodes


def test_build_single_agent_interrupts_only_on_side_effect_tools():
    agent = build_single_agent()
    # Walk the compiled graph's own middleware list isn't directly exposed,
    # so assert via the HITL config the factory built it from instead.
    from app.agent.single_agent import _interrupt_on
    side_effect_names = {t.name for t in TOOLS if not is_read_only(t.name)}
    assert set(_interrupt_on) == side_effect_names
    assert all(v is True for v in _interrupt_on.values())


def test_build_single_agent_has_a_hitl_node():
    agent = build_single_agent()
    nodes = agent.get_graph().nodes
    # Confirmed empirically while writing this plan: HumanInTheLoopMiddleware
    # always registers this exact node name on the STANDALONE create_agent
    # graph, regardless of which tools/agent it's attached to. This is the
    # name voice mode sees (app/voice/graph.py compiles build_single_agent()
    # directly, unwrapped) -- NOT what the wrapped text-mode graph reports
    # once single_agent becomes a subgraph node under app/agent/graph.py's
    # outer StateGraph in Task 3 (that case reports "single_agent" instead,
    # used by stream.py in Task 7). Two different names, two different
    # call sites -- see Global Constraints.
    assert "HumanInTheLoopMiddleware.after_model" in nodes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_single_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agent.single_agent'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/agent/single_agent.py
"""The single-agent `create_agent` build: one agent with every tool, built
the same way the multi-agent specialists are (see
docs/superpowers/specs/2026-09-24-multi-agent-create-agent-design.md and
2026-10-02-single-agent-create-agent-migration-design.md)."""

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from app.agent.middleware import base_middleware, specialist_model, strip_tool_images
from app.agent.prompts.system import SYSTEM_PROMPT
from app.agent.tools import TOOLS, is_read_only

# This one graph bundles send_email, save_memory, write_file, and
# save_portfolio_report together (no per-specialist split like multi-agent),
# so it needs real addresses to work -- same reasoning as
# email_agent/portfolio_agent/memory_agent/filesystem_agent's
# base_middleware(check_email=False).
_interrupt_on = {t.name: True for t in TOOLS if not is_read_only(t.name)}


def build_single_agent(
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
):
    """checkpointer/store are None when this is added as a subgraph node
    under an outer StateGraph (text mode, app/agent/graph.py) -- the
    subgraph inherits the parent's checkpointer the same way multi-agent
    specialists do. Voice mode (app/voice/graph.py) has no outer graph, so
    it passes its own checkpointer/store directly."""
    return create_agent(
        model=specialist_model(),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            *base_middleware(check_email=False),
            strip_tool_images,
            HumanInTheLoopMiddleware(interrupt_on=_interrupt_on),
        ],
        checkpointer=checkpointer,
        store=store,
        name="single_agent",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_single_agent.py -v`
Expected: PASS, all 3 tests. If either node-name assertion fails, your installed `langchain`/`langgraph` version names these nodes differently than the versions this plan was written against (`langchain==1.4.2`, `langgraph==1.2.12` — check `uv.lock`); run
`uv run python -c "from app.agent.single_agent import build_single_agent; print(sorted(build_single_agent().get_graph().nodes))"`
to see the real names on your install and update both this test and the forward references in Tasks 5 and 7 accordingly — don't guess a fix.

- [ ] **Step 5: Commit**

```bash
git add app/agent/single_agent.py tests/unit/test_single_agent.py
git commit -m "feat(agent): add build_single_agent() factory (create_agent, no ErrorRecoveryMiddleware yet)"
```

---

### Task 2: `ErrorRecoveryMiddleware` + mixed-batch-reject regression test

**Files:**
- Modify: `app/agent/single_agent.py`
- Test: `tests/unit/test_single_agent.py`

**Interfaces:**
- Consumes: `app.agent.prompts.system.ERROR_RECOVERY_PROMPT`, `langchain_core.messages.{SystemMessage,HumanMessage,ToolMessage}`, `langchain.agents.middleware.AgentMiddleware`, `ModelRequest`.
- Produces: `ErrorRecoveryMiddleware` class, importable from `app.agent.single_agent`, added to `build_single_agent()`'s middleware list.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_single_agent.py (append)
import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from app.agent.single_agent import ErrorRecoveryMiddleware
from app.agent.prompts.system import ERROR_RECOVERY_PROMPT
from tests.unit.fake_chat import FakeToolModel


@pytest.mark.anyio
async def test_error_recovery_middleware_swaps_prompt_and_messages_on_tool_error():
    model = FakeToolModel([AIMessage(content="recovered")])
    agent = create_agent(
        model=model, tools=[], system_prompt="normal prompt",
        middleware=[ErrorRecoveryMiddleware()],
    )
    history = [
        HumanMessage("do the thing"),
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "x", "args": {}}]),
        ToolMessage(content="boom", tool_call_id="c1", name="x", status="error"),
    ]
    result = await agent.ainvoke({"messages": history})
    assert result["messages"][-1].content == "recovered"
    sent = model.seen[0]
    assert sent[0].content == ERROR_RECOVERY_PROMPT
    assert len(sent) == 2
    assert sent[1].content == "Technical error: boom"


@pytest.mark.anyio
async def test_error_recovery_middleware_passes_through_on_success():
    model = FakeToolModel([AIMessage(content="normal answer")])
    agent = create_agent(
        model=model, tools=[], system_prompt="normal prompt",
        middleware=[ErrorRecoveryMiddleware()],
    )
    history = [HumanMessage("hi")]
    result = await agent.ainvoke({"messages": history})
    assert result["messages"][-1].content == "normal answer"
    sent = model.seen[0]
    assert sent[0].content == "normal prompt"
    assert sent[1].content == "hi"


@pytest.mark.anyio
async def test_mixed_batch_reject_does_not_cancel_the_read_only_call():
    """Pins the NEW, deliberate behavior (atomic-batch-reject is dropped,
    see the spec's decision 2): a read-only call in the same AIMessage as a
    rejected side-effect call still executes."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from app.agent.single_agent import build_single_agent

    calls = []

    @tool("read_only_probe")
    def read_only_probe() -> str:
        """Read-only."""
        calls.append("read_only_probe")
        return "ok"

    @tool("side_effect_probe")
    def side_effect_probe() -> str:
        """Side-effect."""
        calls.append("side_effect_probe")
        return "done"

    import app.agent.single_agent as mod
    model = FakeToolModel([
        AIMessage(content="", tool_calls=[
            {"id": "ro", "name": "read_only_probe", "args": {}},
            {"id": "se", "name": "side_effect_probe", "args": {}},
        ]),
        AIMessage(content="finished"),
    ])
    from langchain.agents import create_agent
    from langchain.agents.middleware import HumanInTheLoopMiddleware
    agent = create_agent(
        model=model, tools=[read_only_probe, side_effect_probe], system_prompt="s",
        middleware=[HumanInTheLoopMiddleware(interrupt_on={"side_effect_probe": True})],
        checkpointer=InMemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "t1"}}
    await agent.ainvoke({"messages": [HumanMessage("go")]}, cfg)
    await agent.ainvoke(
        Command(resume={"decisions": [{"type": "reject", "message": "no"}]}), cfg
    )
    assert "read_only_probe" in calls
    assert "side_effect_probe" not in calls
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_single_agent.py -v -k "error_recovery"`
Expected: FAIL — `ImportError: cannot import name 'ErrorRecoveryMiddleware'`

The third test (`test_mixed_batch_reject_does_not_cancel_the_read_only_call`) should already PASS once written — it tests the official middleware's existing behavior directly, not new code. Run it alone to confirm: `uv run pytest tests/unit/test_single_agent.py -v -k mixed_batch`. If it fails, that's new information about `HumanInTheLoopMiddleware`'s actual behavior — stop and re-read `.venv/Lib/site-packages/langchain/agents/middleware/human_in_the_loop.py` before continuing (don't guess a fix).

- [ ] **Step 3: Implement `ErrorRecoveryMiddleware`**

```python
# app/agent/single_agent.py (add imports and class, before build_single_agent)
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.agent.prompts.system import ERROR_RECOVERY_PROMPT


class ErrorRecoveryMiddleware(AgentMiddleware):
    """Replicates generate.py's old behavior exactly: when the last message
    is an error ToolMessage, the model sees ONLY `[ERROR_RECOVERY_PROMPT,
    "Technical error: <content>"]` -- not the normal system prompt, not the
    rest of the conversation, and no tools (there is nothing to call while
    explaining an error)."""

    def _maybe_override(self, request: ModelRequest) -> ModelRequest:
        if not request.messages:
            return request
        last = request.messages[-1]
        if isinstance(last, ToolMessage) and getattr(last, "status", None) == "error":
            return request.override(
                system_message=SystemMessage(content=ERROR_RECOVERY_PROMPT),
                messages=[HumanMessage(content=f"Technical error: {last.content}")],
                tools=[],
            )
        return request

    def wrap_model_call(self, request: ModelRequest, handler) -> Any:
        return handler(self._maybe_override(request))

    async def awrap_model_call(self, request: ModelRequest, handler) -> Any:
        return await handler(self._maybe_override(request))
```

Then add it to `build_single_agent()`'s middleware list, right after `strip_tool_images` and before `HumanInTheLoopMiddleware` (it must see the raw tool-error state before HITL's own `after_model` hook runs on the *next* AIMessage — ordering relative to HITL doesn't actually matter since they trigger on different message shapes, but keep it grouped with the other single-agent-specific additions for readability):

```python
        middleware=[
            *base_middleware(check_email=False),
            strip_tool_images,
            ErrorRecoveryMiddleware(),
            HumanInTheLoopMiddleware(interrupt_on=_interrupt_on),
        ],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_single_agent.py -v`
Expected: PASS, all 6 tests (3 from Task 1, 3 new).

- [ ] **Step 5: Run the full suite to check nothing else broke**

Run: `uv run pytest tests/ -q`

- [ ] **Step 6: Commit**

```bash
git add app/agent/single_agent.py tests/unit/test_single_agent.py
git commit -m "feat(agent): add ErrorRecoveryMiddleware, pin new mixed-batch-reject behavior"
```

---

### Task 3: Rewrite `app/agent/graph.py` as a thin wrapper; delete `generate.py`

**Files:**
- Modify: `app/agent/graph.py` (full rewrite)
- Delete: `app/agent/nodes/generate.py`
- Modify: `tests/unit/test_graph_structure.py`
- Delete: `tests/unit/test_generate_answer.py`
- Modify: `tests/unit/test_hitl_interrupt.py` (full rewrite)
- Modify: `tests/unit/test_tool_output_image_stripping.py` (fix import)

**Interfaces:**
- Consumes: `app.agent.single_agent.build_single_agent`.
- Produces: `app.agent.graph.record_question` (kept, unchanged — still imported directly by `app/agent/multi_agent/graph.py`), `app.agent.graph.build_agent_app(checkpointer, store=None)` (signature unchanged — `app/api/server.py` needs no changes).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_graph_structure.py (replace entirely)
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import build_agent_app


def _build():
    return build_agent_app(InMemorySaver())


def test_graph_compiles():
    _build()


def test_graph_has_exactly_the_expected_nodes():
    nodes = set(_build().get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"record_question", "single_agent"}


def test_record_question_is_still_exported_for_the_multi_agent_graph():
    # app/agent/multi_agent/graph.py imports record_question from here.
    from app.agent.graph import record_question
    assert callable(record_question)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_graph_structure.py -v`
Expected: FAIL — current node set is `{"record_question", "pii_guard", "generate", "approval", "tools"}`, not `{"record_question", "single_agent"}`.

- [ ] **Step 3: Rewrite `app/agent/graph.py`**

```python
# app/agent/graph.py (full file)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.store.base import BaseStore
from langchain_core.messages import HumanMessage
from app.agent.state import AgentState
from app.agent.single_agent import build_single_agent


def record_question(state: AgentState) -> dict:
    """Persist the user's turn as a HumanMessage so it shows up in checkpointed
    history. Without this, state.question is only used by the RAG/web nodes
    and never reaches state.messages, so cross-turn recall ("what did I ask
    before?") is impossible — the LLM only sees its own past responses."""
    q = state.get("question")
    if not q:
        return {}
    return {"messages": [HumanMessage(content=q)]}


workflow = StateGraph(AgentState)
workflow.add_node("record_question", record_question)
workflow.add_node("single_agent", build_single_agent())

workflow.add_edge(START, "record_question")
workflow.add_edge("record_question", "single_agent")
workflow.add_edge("single_agent", END)


def build_agent_app(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
):
    """Compile the workflow with the supplied checkpointer and optional store.

    Compilation is deferred from module load so the FastAPI lifespan can open an
    `AsyncSqliteSaver` (which requires a running event loop) and pass it in.
    The `store` is the cross-thread long-term memory (LangGraph's BaseStore API).
    Tests that only inspect graph structure can omit the store.

    single_agent is built without its own checkpointer/store, so it inherits
    this compile() call's -- the same pattern app/agent/multi_agent/graph.py
    already uses for its 7 specialist subgraph nodes.
    """
    return workflow.compile(checkpointer=checkpointer, store=store)
```

Note what disappeared entirely and why: `generate_answer` (moved into `single_agent`'s model call + `ErrorRecoveryMiddleware`), `approval_node`/`route_after_approval` (replaced by `HumanInTheLoopMiddleware`), `route_after_generate` (no longer needed — `create_agent` handles its own tool-call-vs-final-answer routing internally), `run_tools`/`_tool_node` (replaced by `create_agent`'s own tool execution + `strip_tool_images` + `tool_errors_to_messages`), `pii_guard`/`route_after_pii_guard` imports (replaced by `SensitiveDataGuard` inside `single_agent`'s middleware, via `base_middleware(check_email=False)`).

- [ ] **Step 4: Delete `app/agent/nodes/generate.py`**

```bash
git rm app/agent/nodes/generate.py
```

- [ ] **Step 5: Delete and rewrite the dependent tests**

```bash
git rm tests/unit/test_generate_answer.py
```

```python
# tests/unit/test_hitl_interrupt.py (replace entirely)
"""Single-agent HITL through the whole graph with the official
HumanInTheLoopMiddleware: side-effect tools pause; approve / reject decide
what runs. Mirrors tests/unit/test_multi_agent_hitl.py's pattern."""
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agent.graph import build_agent_app
from tests.unit.fake_chat import FakeToolModel

SENT = []


async def _run_until_interrupt():
    SENT.clear()
    call = {"id": "e1", "name": "send_email",
            "args": {"recipient": "a@example.com", "subject": "Hi", "body": "Report"}}
    model = FakeToolModel([
        AIMessage(content="", tool_calls=[call]),
        AIMessage(content="Email handled."),
    ])
    with patch("app.agent.single_agent.specialist_model", return_value=model):
        graph = build_agent_app(InMemorySaver())
        cfg = {"configurable": {"thread_id": "hitl-single"}}
        first = await graph.ainvoke({"question": "email the report"}, cfg)
    return graph, cfg, first, call


@pytest.mark.anyio
async def test_send_email_pauses_before_sending():
    graph, cfg, first, call = await _run_until_interrupt()
    assert first["__interrupt__"]
    request = first["__interrupt__"][0].value["action_requests"][0]
    assert request["name"] == "send_email"


@pytest.mark.anyio
async def test_approve_lets_the_turn_finish():
    graph, cfg, first, call = await _run_until_interrupt()
    result = await graph.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg)
    assert result["messages"][-1].content == "Email handled."


@pytest.mark.anyio
async def test_reject_cancels_the_call():
    graph, cfg, first, call = await _run_until_interrupt()
    result = await graph.ainvoke(
        Command(resume={"decisions": [{"type": "reject", "message": "not now"}]}), cfg
    )
    from langchain_core.messages import ToolMessage
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs
    assert tool_msgs[-1].status != "success"
```

Fix `tests/unit/test_tool_output_image_stripping.py`'s import (the `_strip_image_content` re-export from `app.agent.graph` is gone — `app/agent/graph.py` no longer imports `tool_utils` at all):

```python
# tests/unit/test_tool_output_image_stripping.py — change this line:
from app.agent.graph import _strip_image_content
# to:
from app.agent.nodes.tool_utils import strip_image_content as _strip_image_content
```

Delete the now-obsolete `test_run_tools_sanitizes_tool_message_content` test in that same file (it calls `graph_module.run_tools(...)`, which no longer exists — image stripping for the single-agent graph is now covered by `strip_tool_images`, which already has its own tests via the multi-agent suite, e.g. `tests/unit/test_multi_agent_common.py`'s/`tests/unit/test_middleware.py`'s `test_strip_tool_images_keeps_text_and_drops_images`).

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -q`
Expected: PASS. Fix any remaining failures in this step before committing — don't carry broken tests into the next task.

- [ ] **Step 7: Commit**

```bash
git add app/agent/graph.py tests/unit/test_graph_structure.py tests/unit/test_hitl_interrupt.py tests/unit/test_tool_output_image_stripping.py
git rm app/agent/nodes/generate.py tests/unit/test_generate_answer.py
git commit -m "refactor(agent): rewrite app/agent/graph.py as a thin single_agent wrapper"
```

---

### Task 4: Rewrite `app/voice/graph.py`

**Files:**
- Modify: `app/voice/graph.py` (full rewrite)
- Modify: `tests/unit/test_voice_graph_structure.py`

**Interfaces:**
- Consumes: `app.agent.single_agent.build_single_agent`.
- Produces: `app.voice.graph.build_voice_agent_app(checkpointer, store=None)` — signature unchanged, `app/api/server.py` needs no changes.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_voice_graph_structure.py (replace entirely)
from langgraph.checkpoint.memory import InMemorySaver

from app.voice.graph import build_voice_agent_app


def test_voice_graph_compiles():
    build_voice_agent_app(InMemorySaver())


def test_voice_graph_has_no_record_question_node():
    nodes = set(build_voice_agent_app(InMemorySaver()).get_graph().nodes)
    assert "record_question" not in nodes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_voice_graph_structure.py -v`
Expected: FAIL — current graph still has `generate`/`approval`/`tools` nodes and imports from `app.agent.graph` that no longer exist (`approval_node`, `run_tools`), so this will likely fail at import/collection time first.

- [ ] **Step 3: Rewrite `app/voice/graph.py`**

```python
# app/voice/graph.py (full file)
"""Voice-mode agent: the identical build_single_agent() text mode uses,
compiled directly with no wrapping StateGraph -- voice turns don't need
record_question's bookkeeping (voice is driven by the delegation worker,
not the /stream API), and build_single_agent() takes checkpointer/store
directly (create_agent's own support for it), so there is nothing left for
an outer graph to add here."""
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from app.agent.single_agent import build_single_agent


def build_voice_agent_app(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
):
    """Compile the voice-mode graph. Same checkpointer/store as text mode so
    voice and text can share threads if desired (today they use separate
    `thread_id`s)."""
    return build_single_agent(checkpointer=checkpointer, store=store)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_voice_graph_structure.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -q`

- [ ] **Step 6: Commit**

```bash
git add app/voice/graph.py tests/unit/test_voice_graph_structure.py
git commit -m "refactor(voice): compile build_single_agent() directly, no wrapping StateGraph"
```

---

### Task 5: Update `app/voice/hitl.py` for the new resume shape and node name

**Files:**
- Modify: `app/voice/hitl.py:57,75`
- Test: new tests in `tests/unit/test_voice_hitl_classify.py` or a new `tests/unit/test_voice_hitl_resume.py` (create the latter — `test_voice_hitl_classify.py` only tests the unrelated `classify_verdict` function and needs no changes itself)

**Interfaces:**
- Consumes: nothing new.
- Produces: `app.voice.hitl.is_interrupted(agent_app, thread_id)`, `app.voice.hitl.resume_with(agent_app, thread_id, verdict)` — same public signatures, updated internals.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_voice_hitl_resume.py (new file)
from unittest.mock import AsyncMock

import pytest
from langgraph.types import Command

from app.voice.hitl import resume_with


@pytest.mark.anyio
async def test_resume_with_sends_the_decisions_shape():
    agent_app = AsyncMock()
    agent_app.ainvoke.return_value = {"messages": []}
    await resume_with(agent_app, "t1", "approve")
    sent_command = agent_app.ainvoke.call_args[0][0]
    assert isinstance(sent_command, Command)
    assert sent_command.resume == {"decisions": [{"type": "approve"}]}


@pytest.mark.anyio
async def test_resume_with_reject_shape():
    agent_app = AsyncMock()
    agent_app.ainvoke.return_value = {"messages": []}
    await resume_with(agent_app, "t1", "reject")
    sent_command = agent_app.ainvoke.call_args[0][0]
    assert sent_command.resume == {"decisions": [{"type": "reject"}]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_voice_hitl_resume.py -v`
Expected: FAIL — `resume_with` currently sends `Command(resume=verdict)` (a bare string), so `sent_command.resume == {"decisions": [...]}' fails.

- [ ] **Step 3: Update `app/voice/hitl.py`**

Replace line 75 (`return await agent_app.ainvoke(Command(resume=verdict), config)`) with:

```python
    return await agent_app.ainvoke(
        Command(resume={"decisions": [{"type": verdict}]}), config
    )
```

Replace line 57 (`if not snapshot.next or "approval" not in snapshot.next:`) with:

```python
    if not snapshot.next or _HITL_NODE_NAME not in snapshot.next:
```

Add the constant near the top of the file. Voice calls `build_single_agent()` directly with no wrapping `StateGraph` (Task 4), so this is the UNWRAPPED name confirmed in Task 1 — not the `"single_agent"` name Task 7 uses, which only applies to the wrapped text-mode graph:

```python
# HumanInTheLoopMiddleware's own node name on the standalone create_agent
# graph build_single_agent() returns (voice compiles it directly, with no
# wrapping StateGraph -- unlike text mode's app/agent/graph.py, see
# app/agent/single_agent.py's test for how this was confirmed).
_HITL_NODE_NAME = "HumanInTheLoopMiddleware.after_model"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_voice_hitl_resume.py -v`
Expected: PASS.

- [ ] **Step 5: Add one more test for `is_interrupted`'s node-name check**

```python
# tests/unit/test_voice_hitl_resume.py (append)
from types import SimpleNamespace

from app.voice.hitl import _HITL_NODE_NAME, is_interrupted


@pytest.mark.anyio
async def test_is_interrupted_true_when_paused_at_the_hitl_node():
    agent_app = AsyncMock()
    agent_app.aget_state.return_value = SimpleNamespace(
        next=(_HITL_NODE_NAME,),
        values={"messages": []},
    )
    paused, _ = await is_interrupted(agent_app, "t1")
    assert paused is True


@pytest.mark.anyio
async def test_is_interrupted_false_for_an_unrelated_pending_node():
    agent_app = AsyncMock()
    agent_app.aget_state.return_value = SimpleNamespace(
        next=("some_other_node",),
        values={"messages": []},
    )
    paused, _ = await is_interrupted(agent_app, "t1")
    assert paused is False
```

Run: `uv run pytest tests/unit/test_voice_hitl_resume.py -v` — expect PASS.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -q`

- [ ] **Step 7: Commit**

```bash
git add app/voice/hitl.py tests/unit/test_voice_hitl_resume.py
git commit -m "fix(voice): update HITL resume shape and node-name check for create_agent"
```

---

### Task 6: Update `app/api/routers/approve.py`; add `tests/unit/test_approve.py`

**Files:**
- Modify: `app/api/routers/approve.py:45`
- Create: `tests/unit/test_approve.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: no public interface change — `POST /approve` still takes `ApproveRequest` and returns `ChatResponse`, unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_approve.py (new file)
"""Router-level test for /approve's internal translation from
ApproveRequest.approved: bool to the official HumanInTheLoopMiddleware
Command(resume={"decisions": [...]}) shape. Follows tests/unit/test_stream.py's
_FakeAgentApp pattern (app.state.agent_app = fake + TestClient(app))."""
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langgraph.types import Command

from app.api.server import app


class _FakeAgentApp:
    def __init__(self, next_after=()):
        self._next_after = next_after
        self.last_resume = None

    async def aget_state(self, config):
        return SimpleNamespace(next=self._next_after, values={"messages": []})

    async def ainvoke(self, command, config):
        self.last_resume = command
        return {"messages": []}


def test_approve_true_sends_the_approve_decision():
    fake = _FakeAgentApp(next_after=("single_agent",))
    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post("/approve", json={"thread_id": "t1", "approved": True})
    assert response.status_code == 200
    assert isinstance(fake.last_resume, Command)
    assert fake.last_resume.resume == {"decisions": [{"type": "approve"}]}


def test_approve_false_sends_the_reject_decision():
    fake = _FakeAgentApp(next_after=("single_agent",))
    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post("/approve", json={"thread_id": "t1", "approved": False})
    assert response.status_code == 200
    assert fake.last_resume.resume == {"decisions": [{"type": "reject"}]}


def test_approve_on_an_expired_session_returns_completed_without_calling_ainvoke():
    fake = _FakeAgentApp(next_after=())
    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post("/approve", json={"thread_id": "gone", "approved": True})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert fake.last_resume is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_approve.py -v`
Expected: FAIL on the first two tests — `approve.py` currently sends `Command(resume="approve")` (a bare string), not the dict shape.

- [ ] **Step 3: Update `app/api/routers/approve.py`**

Replace line 43-45:
```python
    decision = "approve" if payload.approved else "reject"
    logger.info("HITL decision=%s for thread %s", decision, payload.thread_id)
    final_state = await agent_app.ainvoke(Command(resume=decision), config)
```
with:
```python
    decision = "approve" if payload.approved else "reject"
    logger.info("HITL decision=%s for thread %s", decision, payload.thread_id)
    final_state = await agent_app.ainvoke(
        Command(resume={"decisions": [{"type": decision}]}), config
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_approve.py -v`
Expected: PASS, all 3.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -q`

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/approve.py tests/unit/test_approve.py
git commit -m "fix(api): translate /approve's bool decision to the HumanInTheLoopMiddleware shape"
```

---

### Task 7: Update `app/api/routers/stream.py` for the new node names

**Files:**
- Modify: `app/api/routers/stream.py:106,115`
- Modify: `tests/unit/test_stream.py`

**Interfaces:**
- Consumes: nothing new.

Both values below are the WRAPPED-graph names (text mode's `app/agent/graph.py` adds `single_agent` as a subgraph node under an outer `StateGraph` — see Task 3), confirmed empirically while writing this plan: a message chunk streamed from inside a wrapped subgraph is tagged with the outer node's name (`"single_agent"`), never the subgraph's internal node names, and a pending approval inside that subgraph shows up as `snapshot.next == ("single_agent",)` at the outer level too — NOT `"HumanInTheLoopMiddleware.after_model"`, which is what the UNWRAPPED voice graph reports instead (Task 5). Do not swap these two.

- [ ] **Step 1: Update the two hardcoded node-name checks**

`app/api/routers/stream.py:106`, replace:
```python
                    meta.get("langgraph_node") == "generate"
```
with:
```python
                    meta.get("langgraph_node") == "single_agent"
```

`app/api/routers/stream.py:115`, replace:
```python
        if snapshot.next and "approval" in snapshot.next:
```
with:
```python
        if snapshot.next and "single_agent" in snapshot.next:
```

- [ ] **Step 2: Update `tests/unit/test_stream.py`'s fakes to match**

In `test_stream_happy_path_yields_token_then_done` and
`test_stream_emits_node_events_for_graph_updates` (and any other test in
this file using `{"langgraph_node": "generate"}` in its fake token
metadata, or `next_after=("approval",)`), replace `"generate"` and
`"approval"` with `"single_agent"` in both places. Search the file for both
exact strings first to find every occurrence:

```bash
grep -n '"generate"\|"approval"' tests/unit/test_stream.py
```

Update every match to `"single_agent"`.

- [ ] **Step 3: Run the stream tests**

Run: `uv run pytest tests/unit/test_stream.py -v`
Expected: PASS, every test (they were passing before against the old names — this step just confirms the fakes still match reality after the substitution, not that anything new is being tested).

- [ ] **Step 4: Add one regression test proving the wiring is live, not just the fakes updated**

```python
# tests/unit/test_stream.py (append)
def test_interrupted_event_fires_for_a_pending_single_agent_approval():
    """Regression: this is the exact failure mode the migration risked --
    the interrupted SSE event silently never firing because the node-name
    check didn't match the wrapped single_agent subgraph's reported name."""
    fake = _FakeAgentApp([], next_after=("single_agent",), state_messages=[
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "send_email", "args": {}}])
    ])
    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post("/stream", json={"query": "hi", "thread_id": "t-interrupt"})
    events = _parse_sse(response.text)
    assert any(e == "interrupted" for e, _ in events)
```

Run: `uv run pytest tests/unit/test_stream.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -q`

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/stream.py tests/unit/test_stream.py
git commit -m "fix(api): update /stream's node-name filters for the single_agent subgraph"
```

---

### Task 8: Doc hygiene — stale comments referencing removed functions

**Files:**
- Modify: `app/agent/tools/mcp_clients/filesystem_client.py:8`
- Modify: `app/agent/tools/memory.py:4`
- Modify: `tests/unit/test_wealth_tools_registration.py:50`

**Interfaces:** none — comment/docstring text only, no behavior change.

- [ ] **Step 1: Fix the three stale references**

`app/agent/tools/mcp_clients/filesystem_client.py:8` — change
`fs_write_file_tool (gated by approval_node).` to
`fs_write_file_tool (gated by HumanInTheLoopMiddleware's interrupt_on).`

`app/agent/tools/memory.py:4` — change
`` `save_memory` is a side-effect (gated by approval_node). `` to
`` `save_memory` is a side-effect (gated by HumanInTheLoopMiddleware's interrupt_on). ``

`tests/unit/test_wealth_tools_registration.py:50` — change
`the single-agent graph's approval_node would skip the HITL interrupt` to
`the single-agent graph's HumanInTheLoopMiddleware interrupt_on dict would skip the HITL interrupt`

- [ ] **Step 2: Run the full suite (no behavior change expected, confirms nothing was mis-edited)**

Run: `uv run pytest tests/ -q`
Expected: PASS, same count as before this task.

- [ ] **Step 3: Commit**

```bash
git add app/agent/tools/mcp_clients/filesystem_client.py app/agent/tools/memory.py tests/unit/test_wealth_tools_registration.py
git commit -m "docs: fix comments referencing the removed approval_node"
```

---

### Task 9: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** none — documentation only.

- [ ] **Step 1: Update the "LangGraph state graph" section**

Replace the flow diagram and bullet list (currently describing
`record_question → pii_guard → generate → approval → tools`) with the new
thin-wrapper shape:

```
START → record_question → single_agent (create_agent subgraph) → END
```

Describe `single_agent` as: one `create_agent(...)` carrying every tool,
with middleware `base_middleware(check_email=False)` +
`strip_tool_images` + `ErrorRecoveryMiddleware` (preserves the old
`ERROR_RECOVERY_PROMPT` behavior on a tool error) +
`HumanInTheLoopMiddleware(interrupt_on=...)` (built from every non-read-only
tool in `TOOLS`). Note explicitly that atomic-batch-reject is gone: a
rejected side-effect call no longer cancels read-only calls in the same
batch (matches the multi-agent graph's existing behavior).

- [ ] **Step 2: Update the HITL section**

Update point 2 (`POST /approve`) to note it now internally sends
`Command(resume={"decisions": [{"type": "approve"|"reject"}]})` — the
`ApproveRequest`/`ChatResponse` HTTP contract itself is unchanged. Remove
the line that previously contrasted single-agent's "single global verdict"
contract with multi-agent's per-call one, since both graphs now use the
same official shape (the difference that remains is only that `/approve`
always sends one decision, since the UI only ever asks a single yes/no).

- [ ] **Step 3: Update the Voice mode section**

Note that `build_voice_agent_app` now compiles `build_single_agent()`
directly with no wrapping `StateGraph`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for the single-agent create_agent migration"
```

---

### Task 10: Final full-branch verification

**Files:** none (verification only).

- [ ] **Step 1: Full regression**

Run: `uv run pytest tests/ -q`
Expected: PASS, full suite, zero regressions.

- [ ] **Step 2: Live grounded smoke test**

Run a real conversation through both graphs with a live model — at minimum: a plain question (no tools), a read-only tool call, a side-effect tool call through the full HITL approve flow, and one deliberately-triggered tool error (e.g. ask about a nonexistent client) to confirm `ErrorRecoveryMiddleware` fires with a sensible answer. Use the pattern in `scripts/qa_wealth_db.py` or a throwaway script in the scratchpad directory, not a permanent test file (per this project's QA convention — see `feedback_qa_proportionate`: one live pass, don't chase LLM variance with repeats).

- [ ] **Step 3: Confirm the frontend-facing paths work**

If feasible, start the backend (`uv run uvicorn app.api.server:app --reload`) and drive one `/stream` + `/approve` round trip with `curl` or the Streamlit UI, confirming token streaming and the `interrupted` event both still appear — the exact two behaviors Task 7 was protecting.

- [ ] **Step 4: Report**

Summarize: what changed and the full test count before/after.
