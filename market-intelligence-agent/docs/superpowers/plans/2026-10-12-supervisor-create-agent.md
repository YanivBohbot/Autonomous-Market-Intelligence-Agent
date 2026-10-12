# Supervisor as `create_agent` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The supervisor's routing LLM call becomes a LangChain `create_agent` with `response_format=RoutingDecision` and the official middleware stack. The credit-card guard moves from a graph node to a `@before_agent` middleware. The Router pattern and the UI stay unchanged.

**Architecture:**
- `supervisor_node` keeps its 5 deterministic Python rules. It calls a module-level `router_agent`, a `create_agent` with no tools, and reads `result["structured_response"]`.
- The agent's middleware does what is hand-written today: card guard, PDF-list prompt, client-context prompt, context editing, model retry and fallback.
- The `input_guard` graph node and the supervisor's `RetryPolicy` are removed.
- `/stream` ignores token and node events coming from inside the supervisor namespace.

**Tech Stack:** Python 3.12, langchain 1.4.x (`create_agent`, `before_agent`, `dynamic_prompt`, `ContextEditingMiddleware`, `ModelRetryMiddleware`), LangGraph, FastAPI SSE, pytest (`uv run pytest`).

**Spec:** `docs/superpowers/specs/2026-10-12-supervisor-create-agent-design.md`

## Global Constraints

- The Router pattern is kept. Specialists remain graph nodes, and nothing changes in specialist files or the frontend.
- The router agent runs inside the `supervisor` node with private state. It is never added as a graph node.
- The routing model keeps `metadata={"emit-messages": False, "emit-tool-calls": False}`.
- The card warning text stays `SENSITIVE_DATA_WARNING` from `app/agent/guardrails/detection.py`, unchanged.
- The 5 routing rules keep their exact behavior: hop limit, forced finish, portfolio→email, sticky save, and FINISH fallback to `rag_agent`.
- Tests never call OpenAI. Run them with `uv run pytest tests/ -q -p no:cacheprovider` from `market-intelligence-agent/`.
- Commit locally after each task, never push. Commit messages end with the Co-Authored-By / Claude-Session lines.

## Review Focus

- **A card in content-block form** (`[{"type": "text", "text": "card 4111 1111 1111 1111"}]`) must still be blocked. The guard uses `detection._text` via `contains_credit_card`. Covered by a test in Task 1.
- **The turn after a blocked one**: the router agent must never see the raw number again, because the masked message replaced it in shared state. Covered in Task 4.
- **A blocked turn on `/stream`** must emit the warning exactly once, not once from the inner guard update and once from the supervisor update. Covered in Task 5.
- **The router model failing after retries**: the error must still surface as today (the Market Desk "router down" test). Covered in Task 3.
- **A clean question that contains an email address** must not be blocked. Only cards are blocked. Covered in Task 1.

---

### Task 1: `block_credit_cards` guard middleware

**Files:**
- Create: `app/agent/guardrails/card_guard.py`
- Test: `tests/unit/test_card_guard.py`

**Interfaces:**
- Produces: `block_credit_cards`, an `AgentMiddleware` built with `@before_agent(can_jump_to=["end"])`. On a card it returns `{"messages": [<latest HumanMessage masked, same id>, AIMessage(SENSITIVE_DATA_WARNING)], "jump_to": "end"}`. Otherwise it returns `None`.

- [ ] **Step 1: Write the failing tests**

```python
"""block_credit_cards: the documented @before_agent guardrail
(docs.langchain.com/oss/python/langchain/guardrails), decorator syntax."""
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.guardrails.card_guard import block_credit_cards
from app.agent.guardrails.detection import SENSITIVE_DATA_WARNING
from tests.unit.fake_chat import FakeToolModel


def _agent(model):
    return create_agent(model=model, tools=[], middleware=[block_credit_cards])


def test_a_card_ends_the_run_before_any_model_call_with_a_masked_question():
    model = FakeToolModel([AIMessage(content="should not run")])
    question = HumanMessage(content="My card is 4111 1111 1111 1111, NVDA price?", id="h1")
    result = _agent(model).invoke({"messages": [question]})
    assert model.seen == []
    masked, warning = result["messages"]
    assert masked.id == "h1" and "4111 1111 1111 1111" not in masked.content and masked.content.endswith("NVDA price?")
    assert warning.content == SENSITIVE_DATA_WARNING


def test_a_card_inside_content_blocks_is_also_blocked():
    model = FakeToolModel([AIMessage(content="should not run")])
    question = HumanMessage(content=[{"type": "text", "text": "card 4111 1111 1111 1111"}], id="h1")
    result = _agent(model).invoke({"messages": [question]})
    assert model.seen == []
    assert result["messages"][-1].content == SENSITIVE_DATA_WARNING


def test_clean_questions_and_email_addresses_pass_through():
    model = FakeToolModel([AIMessage(content="ok")])
    result = _agent(model).invoke({"messages": [HumanMessage("Email margaret@example.com her NVDA weight")]})
    assert len(model.seen) == 1
    assert result["messages"][-1].content == "ok"
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError: app.agent.guardrails.card_guard`)

Run: `uv run pytest tests/unit/test_card_guard.py -q -p no:cacheprovider`

- [ ] **Step 3: Implement `app/agent/guardrails/card_guard.py`**

```python
"""Credit-card guardrail for the supervisor's router agent, written as the
documented deterministic guardrail (`@before_agent(can_jump_to=["end"])`,
docs.langchain.com/oss/python/langchain/guardrails). It runs before the
router's model call, so a card number never reaches OpenAI. It returns the
question masked under the SAME id: the supervisor node copies it into the
shared conversation, where the add_messages reducer replaces the raw one,
so no later turn sends it to a model either."""

from typing import Any

from langchain.agents.middleware import AgentState, before_agent
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from app.agent.guardrails.detection import (
    SENSITIVE_DATA_WARNING,
    contains_credit_card,
    mask_credit_cards_in,
)


@before_agent(can_jump_to=["end"])
def block_credit_cards(state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
    latest = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None)
    if latest is None or not contains_credit_card(latest.content):
        return None
    masked = latest.model_copy(update={"content": mask_credit_cards_in(latest.content)})
    return {"messages": [masked, AIMessage(content=SENSITIVE_DATA_WARNING)], "jump_to": "end"}
```

- [ ] **Step 4: Run, expect PASS** (3 passed)

- [ ] **Step 5: Commit** with `feat(guardrails): credit-card guard as a documented @before_agent middleware`

---

### Task 2: Router agent (`build_router_agent`) and client-context routing prompt

**Files:**
- Modify: `app/agent/multi_agent/supervisor.py`
- Test: `tests/unit/test_router_agent.py`

**Interfaces:**
- Consumes: `block_credit_cards` (Task 1); `fresh_documents_prompt`, `context_editing()`, `model_fallback()`, `model_retry()` from `app/agent/middleware.py`; `ClientContextState` from `app/agent/multi_agent/state.py`.
- Produces:
  - `client_context_routing_prompt`, a `@dynamic_prompt` that appends the client sentence when `state["client_context"]` is set;
  - `build_router_agent(model: BaseChatModel | None = None)`, which returns the compiled agent;
  - `router_agent`, a module attribute equal to `build_router_agent()`.
- With a fake model, `response_format=RoutingDecision` falls back to `ToolStrategy`. The fake must therefore return a tool call named `RoutingDecision`.

- [ ] **Step 1: Write the failing tests**

```python
"""The supervisor's router agent: create_agent + response_format + official
middleware. Fake model only (ToolStrategy: a tool call named RoutingDecision)."""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision, build_router_agent
from tests.unit.fake_chat import FakeToolModel

BIG = "x" * 4000


def _decides(next_agent: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "id": "rd1", "name": "RoutingDecision", "args": {"next": next_agent, "reasoning": "r"}}])


def test_returns_the_structured_decision():
    model = FakeToolModel([_decides("finance_agent")])
    result = build_router_agent(model).invoke({"messages": [HumanMessage("NVDA price?")]})
    assert result["structured_response"] == RoutingDecision(next="finance_agent", reasoning="r")


def test_prompt_lists_the_ingested_documents_live(tmp_path, monkeypatch):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text('["brand-new-upload.pdf"]', encoding="utf-8")
    from app.agent.prompts import specialist_agent_prompts as prompts
    monkeypatch.setattr(prompts, "KB_MANIFEST_PATH", manifest)
    model = FakeToolModel([_decides("rag_agent")])
    build_router_agent(model).invoke({"messages": [HumanMessage("what's in the new upload?")]})
    assert "brand-new-upload.pdf" in model.seen[0][0].content


def test_prompt_mentions_the_active_client_only_when_set():
    model = FakeToolModel([_decides("portfolio_agent"), _decides("rag_agent")])
    agent = build_router_agent(model)
    agent.invoke({"messages": [HumanMessage("who is the client?")],
                  "client_context": "Active client: Jane Doe, segment VIP, risk balanced, advisor Sam."})
    agent.invoke({"messages": [HumanMessage("who is the client?")]})
    assert "Active client: Jane Doe" in model.seen[0][0].content
    assert "prefer portfolio_agent" in model.seen[0][0].content
    assert "Active client" not in model.seen[1][0].content


def test_old_turn_tool_results_reach_the_model_cleared():
    history = []
    for n in range(1, 6):
        call = {"id": f"c{n}", "name": "client_portfolio", "args": {}}
        history += [HumanMessage(f"q{n}"), AIMessage(content="", tool_calls=[call]),
                    ToolMessage(content=f"RESULT{n} {BIG}", tool_call_id=f"c{n}", name="client_portfolio"),
                    AIMessage(content=f"a{n}")]
    model = FakeToolModel([_decides("rag_agent")])
    build_router_agent(model).invoke({"messages": [*history, HumanMessage("q6")]})
    tool_contents = [m.content[:7] for m in model.seen[0] if isinstance(m, ToolMessage)]
    assert tool_contents[:3] == ["[cleare"] * 3


def test_a_card_blocks_the_router_with_no_structured_response():
    model = FakeToolModel([_decides("rag_agent")])
    result = build_router_agent(model).invoke({"messages": [HumanMessage("card 4111 1111 1111 1111", id="h1")]})
    assert model.seen == []
    assert "structured_response" not in result


def test_module_router_agent_is_built():
    assert hasattr(supervisor_mod.router_agent, "invoke")
```

Before writing `test_prompt_lists_the_ingested_documents_live`, check which name `ingested_documents_list()` reads the manifest path from: `grep -n "def ingested_documents_list" -A8 app/agent/prompts/specialist_agent_prompts.py`. Patch that exact module attribute, the same one the existing test `test_routing_prompt_reflects_a_pdf_uploaded_after_process_start` patches in `tests/unit/test_multi_agent_supervisor_routing.py`, and copy its monkeypatch line verbatim.

- [ ] **Step 2: Run, expect FAIL** (`ImportError: build_router_agent`)

Run: `uv run pytest tests/unit/test_router_agent.py -q -p no:cacheprovider`

- [ ] **Step 3: Implement in `supervisor.py`.** Add the code below. Leave `_llm` and `_router` in place for now: Task 3 removes them.

```python
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain_core.language_models import BaseChatModel

from app.agent.guardrails.card_guard import block_credit_cards
from app.agent.middleware import context_editing, fresh_documents_prompt, model_fallback, model_retry
from app.agent.multi_agent.state import ClientContextState

# The routing decision is internal: Market Desk (ag-ui-langgraph streams via
# astream_events) must not render its JSON as chat text.
_ROUTER_MODEL_METADATA = {"emit-messages": False, "emit-tool-calls": False}


@dynamic_prompt
def client_context_routing_prompt(request: ModelRequest) -> str:
    """Without this, the router had no idea a client was even active -- a
    vague client question like "qui est le client" could route to
    memory_agent or another specialist that has never heard of this client."""
    base = request.system_prompt or ""
    client_context = request.state.get("client_context")
    if not client_context:
        return base
    return (
        f"{base}\n\n{client_context} When this client is active and the question "
        'is about them -- even phrased generically ("who is the client", "what\'s their '
        'portfolio worth") -- prefer portfolio_agent, finance_agent, or rag_agent over '
        "memory_agent/filesystem_agent/browser_agent/email_agent, which don't know who this "
        "client is."
    )


def build_router_agent(model: BaseChatModel | None = None):
    """The routing LLM call as a create_agent: structured output via
    response_format, plus the same official middleware the specialists get.
    Invoked inside supervisor_node with a COPY of the conversation; its own
    messages never enter the shared state (except the card guard's)."""
    fallback = model_fallback()
    return create_agent(
        model=model or ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, metadata=_ROUTER_MODEL_METADATA),
        tools=[],
        system_prompt=SUPERVISOR_ROUTING_PROMPT,
        response_format=RoutingDecision,
        state_schema=ClientContextState,
        middleware=[
            block_credit_cards,
            fresh_documents_prompt,
            client_context_routing_prompt,
            context_editing(),
            *([fallback] if fallback is not None else []),
            model_retry(),
        ],
        name="supervisor_router",
    )


router_agent = build_router_agent()
```

`fresh_documents_prompt` substitutes `INGESTED_DOCUMENTS_PLACEHOLDER` into `request.system_prompt`, which is `SUPERVISOR_ROUTING_PROMPT` here. That is the same mechanism `rag_agent` already uses.

- [ ] **Step 4: Run, expect PASS** (6 passed). Also run `tests/unit/test_multi_agent_supervisor_routing.py`; it is still green because the node is unchanged.

- [ ] **Step 5: Commit** with `feat(supervisor): router agent as create_agent with response_format and official middleware`

---

### Task 3: `supervisor_node` calls `router_agent`, and the tests migrate off `_router`

**Files:**
- Modify: `app/agent/multi_agent/supervisor.py` (node body; remove `_llm`, `_router`, the manual `ClearOldTurnToolResults` and `count_tokens_approximately` code, the manual prompt building, and the "Deliberately not the official langgraph-supervisor" comment, which no longer applies)
- Create: `tests/unit/router_fakes.py`
- Modify every test that patches `supervisor_mod._router`:
  - `test_multi_agent_supervisor_routing.py`, `test_copilot_endpoint.py`, `test_multi_agent_end_to_end.py`, `test_multi_agent_hitl.py`
  - `test_client_context_reaches_specialists.py`, `test_multi_agent_question_reaches_messages.py`, `test_context_editing.py`
  - `test_copilot_uploads.py`, `test_data_endpoints.py`, `test_portfolio_narrative.py`, `test_workspace_files.py`, `test_workspace_screenshots.py`
  - Find the exact list with `grep -ln "_router" tests/unit/*.py`. The last five may only mention `_router` in names such as `data_router_module`; do not touch those.

**Interfaces:**
- Consumes: `router_agent` and `build_router_agent` (Task 2).
- Produces: `routed(next_agent: str, reasoning: str = "test") -> dict`, which returns `{"structured_response": RoutingDecision(...), "messages": []}`, in `tests/unit/router_fakes.py`.

- [ ] **Step 1: Write the new node tests** (append them to `test_multi_agent_supervisor_routing.py`)

```python
from tests.unit.router_fakes import routed


def test_node_reads_the_router_agents_structured_response():
    with patch.object(supervisor_mod, "router_agent") as agent:
        agent.invoke.return_value = routed("finance_agent")
        result = supervisor_node(_state(messages=[HumanMessage("NVDA?")]))
    assert result.goto == "finance_agent"
    sent = agent.invoke.call_args.args[0]
    assert sent["messages"][-1].content == "NVDA?"
    assert "client_context" in sent


def test_card_block_copies_the_masked_question_and_warning_then_finalizes():
    from app.agent.guardrails.detection import SENSITIVE_DATA_WARNING
    question = HumanMessage("card 4111 1111 1111 1111", id="h1")
    masked = question.model_copy(update={"content": "card ****-****-****-1111"})
    with patch.object(supervisor_mod, "router_agent") as agent:
        agent.invoke.return_value = {"messages": [masked, AIMessage(SENSITIVE_DATA_WARNING)]}
        result = supervisor_node(_state(messages=[question]))
    assert result.goto == "finalize_turn"
    assert [m.content for m in result.update["messages"]] == ["card ****-****-****-1111", SENSITIVE_DATA_WARNING]
    assert result.update["messages"][0].id == "h1"
```

Create `tests/unit/router_fakes.py`:

```python
"""Fake router_agent results for tests that patch supervisor_mod.router_agent."""
from app.agent.multi_agent.supervisor import RoutingDecision


def routed(next_agent: str, reasoning: str = "test") -> dict:
    return {"structured_response": RoutingDecision(next=next_agent, reasoning=reasoning), "messages": []}
```

- [ ] **Step 2: Run, expect FAIL** (`AttributeError`: the node still calls `_router`)

- [ ] **Step 3: Replace the LLM part of `supervisor_node`.** Everything from `routing_prompt = SUPERVISOR_ROUTING_PROMPT.replace(...)` through `decision = cast(...)` becomes:

```python
    result = router_agent.invoke({
        "messages": list(messages),
        "client_context": state.get("client_context"),
    })
    decision = result.get("structured_response")
    if decision is None:
        # block_credit_cards ended the router run (@before_agent jump_to
        # "end"): carry its masked question (same id, replaces the raw one)
        # and its warning into the shared conversation, then end the turn.
        latest = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        carried = [m for m in result["messages"] if latest is not None and m.id == latest.id]
        return Command(
            goto="finalize_turn",
            update={"messages": [*carried, result["messages"][-1]], "next_agent": None},
        )
```

Leave `next_agent = decision.next` and the rest unchanged. Remove `_llm`, `_router`, the `cast` import if it is unused, and the imports `ClearOldTurnToolResults`, `count_tokens_approximately` and `INGESTED_DOCUMENTS_PLACEHOLDER`/`ingested_documents_list` if they are unused.

- [ ] **Step 4: Migrate the tests mechanically, file by file**
  - `patch.object(supervisor_mod, "_router")` becomes `patch.object(supervisor_mod, "router_agent")`.
  - `X.invoke.return_value = RoutingDecision(next=A, reasoning=B)` becomes `X.invoke.return_value = routed(A, B)`.
  - `X.invoke.side_effect = [RoutingDecision(...), ...]` becomes `[routed(...), ...]`. Exception side effects (`RuntimeError("router down")`) stay as they are.
  - Add `from tests.unit.router_fakes import routed` where it is used.
  - Tests that inspected the router's SystemMessage prompt are now covered by `tests/unit/test_router_agent.py`. Delete them from `test_multi_agent_supervisor_routing.py`: `test_routing_prompt_reflects_a_pdf_uploaded_after_process_start`, `test_routing_prompt_includes_the_active_client_when_present` and `test_routing_prompt_unchanged_when_no_active_client`.
  - `test_router_is_not_given_a_duplicate_question_message` keeps its intent: assert on `call_args.args[0]["messages"]`.
  - In `test_context_editing.py`, replace `test_supervisor_router_gets_old_tool_results_cleared_and_state_is_untouched` with a node-level check. The node passes the original messages, and clearing happens in the agent, which `test_router_agent.py` covers. So the replacement asserts that `agent.invoke.call_args.args[0]["messages"]` keeps `RESULT1` and that `history` is unchanged.

- [ ] **Step 5: Run the affected files, then the full suite. Expect all green.**

Run: `uv run pytest tests/ -q -p no:cacheprovider`

- [ ] **Step 6: Commit** with `refactor(supervisor): route through router_agent; tests fake router_agent`

---

### Task 4: Graph without `input_guard` or `RetryPolicy`

**Files:**
- Modify: `app/agent/multi_agent/graph.py`
- Delete: `app/agent/guardrails/input_guard.py`
- Modify: `app/agent/guardrails/__init__.py` (export `block_credit_cards`, drop `input_guard`, update the docstring)
- Modify: `tests/unit/test_multi_agent_graph_structure.py`, `tests/unit/test_guardrails.py`

**Interfaces:**
- Consumes: `block_credit_cards`, `build_router_agent`, `routed`.
- Produces: the graph edge `record_question → supervisor`, with no `input_guard` node and no retry policy on `supervisor`.

- [ ] **Step 1: Update the structure tests (failing first)**
  - In `test_multi_agent_graph_structure.py`, remove `"input_guard"` from the expected node list.
  - Replace `test_input_guard_sits_between_record_question_and_supervisor` with:

```python
def test_record_question_feeds_the_supervisor_directly():
    edges = {(e.source, e.target) for e in build_multi_agent_app(InMemorySaver()).get_graph().edges}
    assert ("record_question", "supervisor") in edges
    assert not any("input_guard" in edge for edge in edges)


def test_supervisor_has_no_node_retry_policy():
    from app.agent.multi_agent.graph import _build_workflow
    assert not _build_workflow().nodes["supervisor"].retry_policy
```

Match the file's existing imports and its existing graph-building helper. If `InMemorySaver` and `build_multi_agent_app` are already imported, reuse them.

- Rewrite `test_guardrails.py`'s four `input_guard_*` tests as end-to-end graph tests. They patch `supervisor_mod.router_agent` with `build_router_agent(FakeToolModel(...))`, so the real guard runs:

```python
def test_card_is_blocked_before_any_model_call_and_history_keeps_it_masked():
    model = FakeToolModel([])
    with patch.object(supervisor_mod, "router_agent", build_router_agent(model)):
        graph = build_multi_agent_app(InMemorySaver())
        cfg = {"configurable": {"thread_id": "card"}}
        out = graph.invoke({"question": "card 4111 1111 1111 1111 please"}, cfg)
    assert model.seen == []
    assert out["messages"][-1].content == SENSITIVE_DATA_WARNING
    assert "4111 1111 1111 1111" not in out["messages"][-2].content


def test_clean_question_reaches_the_router_model():
    model = FakeToolModel([AIMessage(content="", tool_calls=[{"id": "r", "name": "RoutingDecision",
                                                              "args": {"next": "rag_agent", "reasoning": "r"}}])])
    with patch.object(supervisor_mod, "router_agent", build_router_agent(model)), \
         patch.object(rag_mod, "specialist_model", return_value=FakeToolModel([AIMessage(content="answer")])):
        graph = build_multi_agent_app(InMemorySaver())
        graph.invoke({"question": "What's in the Amazon report?"}, {"configurable": {"thread_id": "clean"}})
    assert len(model.seen) == 1


def test_blocked_card_never_reaches_the_router_on_the_next_turn():
    blocked_model = FakeToolModel([])
    graph_cfg = {"configurable": {"thread_id": "next-turn"}}
    with patch.object(supervisor_mod, "router_agent", build_router_agent(blocked_model)):
        graph = build_multi_agent_app(InMemorySaver())
        graph.invoke({"question": "card 4111 1111 1111 1111"}, graph_cfg)
        next_model = FakeToolModel([AIMessage(content="", tool_calls=[{"id": "r", "name": "RoutingDecision",
                                                                       "args": {"next": "rag_agent", "reasoning": "r"}}])])
        with patch.object(supervisor_mod, "router_agent", build_router_agent(next_model)), \
             patch.object(rag_mod, "specialist_model", return_value=FakeToolModel([AIMessage(content="ok")])):
            graph.invoke({"question": "and NVDA?"}, graph_cfg)
    assert not any("4111 1111 1111 1111" in str(m.content) for m in next_model.seen[0])
```

Use `from app.agent.multi_agent import rag_agent as rag_mod`. Keep the file's existing detection-level tests (`contains_credit_card`, `mask_credit_cards_in`, and so on) untouched. If an existing input_guard test checks something not covered above, port its assertion into one of these three tests rather than dropping it.

- [ ] **Step 2: Run, expect FAIL** (the graph still has `input_guard`)

- [ ] **Step 3: Edit `graph.py`**
  - Remove `from langgraph.types import RetryPolicy` and `from app.agent.guardrails import input_guard`.
  - Remove the `input_guard` `add_node` and its comment.
  - Replace the supervisor `add_node` line and its RetryPolicy comment with `workflow.add_node("supervisor", supervisor_node)`.
  - Replace `workflow.add_edge("record_question", "input_guard")` with `workflow.add_edge("record_question", "supervisor")`.

Delete `app/agent/guardrails/input_guard.py`. In `app/agent/guardrails/__init__.py`, export `block_credit_cards` instead of `input_guard`, and make the docstring say: "Request-level blocking happens in `block_credit_cards`, a @before_agent middleware on the supervisor's router agent."

- [ ] **Step 4: Run the full suite, expect green.** Then run `grep -rn "input_guard" app tests`. It must be empty, apart from comments you fix in Task 6.

- [ ] **Step 5: Commit** with `refactor(graph): drop input_guard node and supervisor RetryPolicy (now middleware)`

---

### Task 5: `/stream` ignores events from inside the supervisor

**Files:**
- Modify: `app/api/routers/stream.py`
- Test: `tests/unit/test_stream.py`

**Interfaces:**
- Produces: `_inside_supervisor(namespace: tuple) -> bool`. `_STATIC_MESSAGE_NODES` contains `"supervisor"` instead of `"input_guard"`.

- [ ] **Step 1: Write the failing tests.** Follow the existing fake-astream pattern in `test_stream.py`, the one `test_stream_emits_input_guard_warning_as_token` uses: a fake `agent_app.astream` that yields `(namespace, mode, chunk)` tuples. Rename that test and change its update key from `"input_guard"` to `"supervisor"`. Then add:

```python
def test_stream_skips_router_tokens_and_node_events_from_inside_the_supervisor():
    # Yields: an inner router token (ns supervisor:...), an inner "model" node
    # update, the supervisor's own routing update, then a specialist token.
    ...  # build the fake exactly like the neighbouring tests do; chunks:
    # (("supervisor:abc",), "messages", (AIMessageChunk(content='{"next":"rag_agent"}'), {"langgraph_node": "model"}))
    # (("supervisor:abc",), "updates", {"model": {"messages": [AIMessage(content='{"next":"rag_agent"}')]}})
    # ((), "updates", {"supervisor": {"next_agent": "rag_agent"}})
    # (("rag_agent:def",), "messages", (AIMessageChunk(content="answer"), {"langgraph_node": "model"}))
    # assert the token events are exactly ["answer"]
    # assert no node event has node == "model" coming from the supervisor namespace


def test_blocked_turn_emits_the_warning_exactly_once():
    # chunks:
    # (("supervisor:abc",), "updates", {"block_credit_cards.before_agent": {"messages": [masked, AIMessage(SENSITIVE_DATA_WARNING)]}})
    # ((), "updates", {"supervisor": {"messages": [masked, AIMessage(SENSITIVE_DATA_WARNING)], "next_agent": None}})
    # assert [token events] == [SENSITIVE_DATA_WARNING]
```

Write both tests with concrete fakes copied from the existing `test_stream_emits_input_guard_warning_as_token` structure. The comments above describe the exact chunks and assertions; turn them into real code, and do not leave `...` in the file.

- [ ] **Step 2: Run, expect FAIL** (the router token is streamed)

- [ ] **Step 3: Implement in `stream.py`**

```python
def _inside_supervisor(namespace) -> bool:
    """Events from the supervisor's own router agent (create_agent run inside
    the supervisor node): its "model" node streams the routing JSON, which
    must never reach the chat."""
    return bool(namespace) and str(namespace[0]).startswith("supervisor:")
```

- Change `async for _namespace, mode, chunk in ...` to `async for namespace, mode, chunk in ...`.
- Make the first statement of the loop body `if _inside_supervisor(namespace): continue`.
- In `_STATIC_MESSAGE_NODES`, replace `"input_guard"` with `"supervisor"`, and update the comment above it: "the supervisor node, which copies the card guard's warning into state, and OpenAIModerationMiddleware's hooks inside a specialist subgraph."

The supervisor's ordinary routing updates carry no `messages` key, so `_static_message_content` returns `None` for them.

- [ ] **Step 4: Run `test_stream.py`, then the full suite. Expect green.**

- [ ] **Step 5: Commit** with `fix(stream): skip router-agent events inside the supervisor; card warning from supervisor`

---

### Task 6: Docs, full verification, live acceptance

**Files:**
- Modify: `CLAUDE.md` ("Multi-agent mode" and the guardrails mentions; remove `input_guard`/`pii_guard` graph-node wording; describe the router agent and its middleware list)
- Modify: `app/agent/middleware.py`, the `mask_credit_cards()` docstring ("behind the graph-level input_guard" becomes "behind the supervisor router's block_credit_cards guard")
- Modify: `app/agent/tools/portfolio_narrative.py`, line 2's docstring mention of the supervisor's `_router`. Reword it to say "the same lightweight raw-call pattern", so it does not name a symbol that no longer exists.

- [ ] **Step 1:** Run `grep -rn "input_guard\|_router\b" app CLAUDE.md docs/TOOLS.md`. Fix every stale mention. Leave historical specs and plans under `docs/superpowers/` alone.
- [ ] **Step 2:** Run `uv run pytest tests/ -q -p no:cacheprovider`, which must be all green, and `cd frontend && npx vitest run`, which must show 298 passed.
- [ ] **Step 3:** Commit with `docs: supervisor router agent and card guard middleware`
- [ ] **Step 4:** Restart the backend without `--reload`.
- [ ] **Step 5: Live acceptance.** Run against `localhost:8000` on fresh `qa_router_*` threads:
  1. Run the core questions: NVDA price, Amazon 2024 net sales, Margaret Collins' portfolio, the concentration screen, "Open https://example.com", the workspace file list, "Remember my horizon is 10 years" (reject it), and the card number. Each must reach the same specialist as before. The card must give exactly one warning token, and the stored history must hold the masked number.
  2. In LangSmith, open one trace. Under `supervisor`, the `supervisor_router` agent must appear with `block_credit_cards.before_agent`, `ContextEditingMiddleware.awrap_model_call` and `ModelRetryMiddleware.awrap_model_call`. The routing `ChatOpenAI` call must use roughly 2k input tokens or fewer.
  3. On `/stream`, no `{"next": ...}` JSON may appear among the token events.
- [ ] **Step 6:** Update the memory file `project_supervisor_handoff_migration_idea.md` with the outcome and the commit hashes.
