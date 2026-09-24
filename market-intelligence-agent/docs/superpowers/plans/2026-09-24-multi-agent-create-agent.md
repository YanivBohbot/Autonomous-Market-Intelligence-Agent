# Multi-agent specialists on `create_agent` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the 7 multi-agent specialists with LangChain v1 `create_agent` + official middleware, keeping the Router supervisor and one file per specialist.

**Architecture:** Each `app/agent/multi_agent/<name>_agent.py` exposes `build_<name>_agent()` returning `create_agent(...)`. Shared model + middleware live in `multi_agent/common.py`. `multi_agent/graph.py` builds the workflow inside `build_multi_agent_app()` (so tests can patch each module's `specialist_model`), adds every specialist as a subgraph node with a static edge back to `supervisor`. HITL on `send_email` / `write_file` / `save_memory` uses `HumanInTheLoopMiddleware`.

**Tech Stack:** Python 3.12, langchain 1.2.17 (`langchain.agents.create_agent`, `langchain.agents.middleware`), langgraph 1.1.10, langchain-openai, pytest (+ anyio). Run everything from `market-intelligence-agent/` with `uv run`.

**Spec:** `docs/superpowers/specs/2026-09-24-multi-agent-create-agent-design.md`

## Global Constraints

- Only `app/agent/multi_agent/`, its tests, `app/agent/nodes/tool_utils.py` (cleanup) and docs change. Do NOT modify `app/agent/graph.py`, `app/agent/nodes/generate.py`, `app/api/`, `app/voice/`, `app/ui/`, `frontend/`, `prod/`.
- Supervisor (`multi_agent/supervisor.py`) routing logic is unchanged.
- One file per specialist is kept: `rag_agent.py`, `finance_agent.py`, `portfolio_agent.py`, `browser_agent.py`, `email_agent.py`, `filesystem_agent.py`, `memory_agent.py`.
- Every specialist: `create_agent(model=specialist_model(), tools=_TOOLS, system_prompt=<PROMPT>, middleware=[*base_middleware(), ...], name="<name>_agent")`.
- `base_middleware()` order: `today_prompt`, `ModelCallLimitMiddleware(run_limit=10, exit_behavior="end")`, `tool_errors_to_messages`.
- HITL: `HumanInTheLoopMiddleware(interrupt_on={...})` — email: `{"send_email": True}`; filesystem: `{"write_file": True}`; memory: `{"save_memory": True}`. No HITL on the other 4.
- Browser specialist additionally gets `strip_tool_images`.
- Tool lists and system prompts unchanged.
- Unit tests make zero OpenAI calls (fake chat model from `tests/unit/fake_chat.py`).
- Commit messages end with:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01Ef16qzkiyktnMEUerKmyNs`
- Never `git push`.

---

### Task 1: Shared model + middleware (`common.py`) and fake chat model

**Files:**
- Create: `app/agent/multi_agent/common.py`
- Create: `tests/unit/fake_chat.py`
- Test: `tests/unit/test_multi_agent_common.py`

**Interfaces:**
- Produces: `specialist_model() -> ChatOpenAI`; `today_prompt` (AgentMiddleware); `call_limit() -> ModelCallLimitMiddleware`; `tool_errors_to_messages` (AgentMiddleware); `strip_tool_images` (AgentMiddleware); `base_middleware() -> list`.
- Produces (tests): `tests/unit/fake_chat.py::FakeToolModel(responses: list[AIMessage])` with `.seen: list[list[BaseMessage]]` (messages of every model call) and a no-op `bind_tools`.

- [ ] **Step 1: Write the fake chat model helper**

`tests/unit/fake_chat.py`:
```python
"""Offline chat model for create_agent tests: replays scripted AIMessages,
accepts bind_tools, and records the messages of every call."""
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from pydantic import Field


class FakeToolModel(GenericFakeChatModel):
    seen: list = Field(default_factory=list)

    def __init__(self, responses, **kwargs):
        super().__init__(messages=iter(responses), **kwargs)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/test_multi_agent_common.py`:
```python
from datetime import date

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from app.agent.multi_agent.common import (
    base_middleware,
    call_limit,
    specialist_model,
    strip_tool_images,
    today_prompt,
    tool_errors_to_messages,
)
from tests.unit.fake_chat import FakeToolModel


def test_specialist_model_uses_configured_openai_model():
    from app.core.config import settings
    m = specialist_model()
    assert m.model_name == settings.OPENAI_MODEL
    assert m.temperature == 0


def test_call_limit_is_10_per_run_and_ends_gracefully():
    m = call_limit()
    assert isinstance(m, ModelCallLimitMiddleware)
    assert m.run_limit == 10
    assert m.exit_behavior == "end"


def test_base_middleware_order():
    mw = base_middleware()
    assert mw[0] is today_prompt
    assert isinstance(mw[1], ModelCallLimitMiddleware)
    assert mw[2] is tool_errors_to_messages
    assert len(mw) == 3


@pytest.mark.anyio
async def test_today_prompt_appends_todays_date_to_the_static_prompt():
    model = FakeToolModel([AIMessage(content="hi")])
    agent = create_agent(model=model, tools=[], system_prompt="You are X.", middleware=[today_prompt])
    await agent.ainvoke({"messages": [HumanMessage("q")]})
    system_text = model.seen[0][0].content
    assert system_text.startswith("You are X.")
    assert f"Today's date is {date.today().isoformat()}." in system_text


@tool
async def _boom() -> str:
    """Always fails."""
    raise RuntimeError("kaboom")


@pytest.mark.anyio
async def test_tool_errors_become_error_tool_messages_instead_of_crashing():
    model = FakeToolModel([
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "_boom", "args": {}}]),
        AIMessage(content="recovered"),
    ])
    agent = create_agent(model=model, tools=[_boom], system_prompt="S", middleware=[tool_errors_to_messages])
    result = await agent.ainvoke({"messages": [HumanMessage("q")]})
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs[0].status == "error"
    assert "kaboom" in tool_msgs[0].content
    assert result["messages"][-1].content == "recovered"


@tool
async def _shot() -> list:
    """Returns text + image content."""
    return [{"type": "text", "text": "took screenshot"}, {"type": "image", "data": "b64", "mimeType": "image/png"}]


@pytest.mark.anyio
async def test_strip_tool_images_keeps_text_and_drops_images():
    model = FakeToolModel([
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "_shot", "args": {}}]),
        AIMessage(content="done"),
    ])
    agent = create_agent(model=model, tools=[_shot], system_prompt="S", middleware=[strip_tool_images])
    result = await agent.ainvoke({"messages": [HumanMessage("q")]})
    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    parts = tool_msg.content if isinstance(tool_msg.content, list) else [tool_msg.content]
    assert not any(isinstance(p, dict) and p.get("type") in ("image", "image_url") for p in parts)
    assert "took screenshot" in str(tool_msg.content)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_multi_agent_common.py -v`
Expected: collection ERROR `ModuleNotFoundError: No module named 'app.agent.multi_agent.common'`

- [ ] **Step 4: Implement `common.py`**

`app/agent/multi_agent/common.py`:
```python
"""Pieces shared by every multi-agent specialist.

Each specialist file calls `create_agent(...)` itself (one file per agent);
this module only holds what would otherwise be copied 7 times: the model
factory and the middleware every specialist gets.
"""

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRequest,
    dynamic_prompt,
    wrap_tool_call,
)
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI

from app.agent.nodes.tool_utils import strip_image_content
from app.agent.prompts import with_today
from app.core.config import settings

MODEL_CALL_LIMIT = 10


def specialist_model() -> ChatOpenAI:
    return ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True)


@dynamic_prompt
def today_prompt(request: ModelRequest) -> str:
    """Static system_prompt + today's date, computed per call so a
    long-running process never serves a stale date."""
    return with_today(request.system_prompt or "")


def call_limit() -> ModelCallLimitMiddleware:
    """Cap model calls per specialist run so a looping agent can't run up
    OpenAI cost; "end" finishes the run instead of raising."""
    return ModelCallLimitMiddleware(run_limit=MODEL_CALL_LIMIT, exit_behavior="end")


@wrap_tool_call
async def tool_errors_to_messages(request, handler):
    """A failing tool becomes an error ToolMessage the model can read and
    recover from, instead of aborting the run (the thread-poisoning fix the
    single-agent graph gets from ToolNode(handle_tool_errors=True)).
    Async: the MCP tools are async-only."""
    try:
        return await handler(request)
    except Exception as exc:  # noqa: BLE001 — every tool failure goes back to the model
        return ToolMessage(
            content=f"Tool error: {exc}",
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
            status="error",
        )


@wrap_tool_call
async def strip_tool_images(request, handler):
    """OpenAI rejects image parts in tool messages; drop them (browser
    screenshots) and keep the text."""
    result = await handler(request)
    if isinstance(result, ToolMessage):
        result.content = strip_image_content(result.content)
    return result


def base_middleware() -> list:
    return [today_prompt, call_limit(), tool_errors_to_messages]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_multi_agent_common.py -v`
Expected: 7 passed. If `pytest.mark.anyio` tests error with "no backend", check `tests/conftest.py` for the existing `anyio_backend` fixture (it is already used by `tests/unit/test_tool_utils.py`) and follow the same convention.

- [ ] **Step 6: Commit**

```bash
git add app/agent/multi_agent/common.py tests/unit/fake_chat.py tests/unit/test_multi_agent_common.py
git commit -m "feat(multi-agent): shared create_agent model + middleware (date, call limit, tool errors, image strip)"
```

---

### Task 2: Migrate the 4 read-only specialists and rewire the graph

**Files:**
- Modify (rewrite): `app/agent/multi_agent/rag_agent.py`, `finance_agent.py`, `portfolio_agent.py`, `browser_agent.py`
- Modify: `app/agent/multi_agent/graph.py`
- Test (rewrite): `tests/unit/test_multi_agent_rag_agent.py`, `test_multi_agent_finance_agent.py`, `test_multi_agent_portfolio_agent.py`, `test_multi_agent_browser_agent.py`
- Test (update): `tests/unit/test_multi_agent_end_to_end.py`, `tests/unit/test_multi_agent_question_reaches_messages.py`, `tests/unit/test_multi_agent_graph_structure.py`

**Interfaces:**
- Consumes: `specialist_model`, `base_middleware`, `strip_tool_images` from Task 1; `FakeToolModel` from Task 1.
- Produces: `build_rag_agent()`, `build_finance_agent()`, `build_portfolio_agent()`, `build_browser_agent()` → compiled `create_agent` graphs; module-level `_TOOLS` list in each; `graph.py` builds the workflow inside `build_multi_agent_app(checkpointer, store=None)` and exposes `SPECIALISTS: dict[str, Callable]` (node name → builder) for Task 3 to extend.

- [ ] **Step 1: Rewrite the 4 specialist test files (failing)**

`tests/unit/test_multi_agent_finance_agent.py`:
```python
from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent import finance_agent as mod
from app.agent.multi_agent.common import base_middleware


def _kwargs():
    with patch.object(mod, "create_agent") as ca:
        mod.build_finance_agent()
    return ca.call_args.kwargs


def test_tools():
    assert {t.name for t in mod._TOOLS} == {
        "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news"}


def test_create_agent_call():
    kw = _kwargs()
    from app.agent.prompts.specialist_agent_prompts import FINANCE_SYSTEM_PROMPT
    assert kw["system_prompt"] == FINANCE_SYSTEM_PROMPT
    assert kw["tools"] == mod._TOOLS
    assert kw["name"] == "finance_agent"
    assert [type(m) for m in kw["middleware"]] == [type(m) for m in base_middleware()]
    assert not any(isinstance(m, HumanInTheLoopMiddleware) for m in kw["middleware"])


def test_builds_a_real_agent():
    assert "model" in mod.build_finance_agent().get_graph().nodes
```

`tests/unit/test_multi_agent_rag_agent.py`: same as the finance file with `finance`→`rag`, `FINANCE_SYSTEM_PROMPT`→`RAG_SYSTEM_PROMPT`, and
```python
def test_tools():
    assert {t.name for t in mod._TOOLS} == {"search_knowledge_base", "web_search"}
```

`tests/unit/test_multi_agent_portfolio_agent.py`: same with `portfolio`, `PORTFOLIO_SYSTEM_PROMPT`, and
```python
def test_tools():
    names = {t.name.rsplit("___", 1)[-1] for t in mod._TOOLS}
    assert names == {"read_query", "list_tables", "describe_table", "yfinance_get_ticker_info",
                     "portfolio_metrics", "pct_change", "concentration_screen"}
```

`tests/unit/test_multi_agent_browser_agent.py`: same with `browser`, `BROWSER_SYSTEM_PROMPT`, and replace `test_create_agent_call`'s middleware assertion with:
```python
    from app.agent.multi_agent.common import strip_tool_images
    mw = kw["middleware"]
    assert [type(m) for m in mw[:3]] == [type(m) for m in base_middleware()]
    assert mw[3] is strip_tool_images
    assert len(mw) == 4
```
and
```python
def test_tools():
    assert {t.name for t in mod._TOOLS} == {"browser_navigate", "browser_snapshot", "browser_take_screenshot"}
```
Write each of the 4 files in full (no shared helper module) so each test file mirrors its agent file.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_multi_agent_finance_agent.py tests/unit/test_multi_agent_rag_agent.py tests/unit/test_multi_agent_portfolio_agent.py tests/unit/test_multi_agent_browser_agent.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'create_agent'` / `'_TOOLS'`.

- [ ] **Step 3: Rewrite the 4 specialist modules**

`app/agent/multi_agent/finance_agent.py`:
```python
from langchain.agents import create_agent

from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.prompts.specialist_agent_prompts import FINANCE_SYSTEM_PROMPT
from app.agent.tools import yf_history_tool, yf_news_tool, yf_quote_tool

_TOOLS = [yf_quote_tool, yf_history_tool, yf_news_tool]


def build_finance_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=FINANCE_SYSTEM_PROMPT,
        middleware=[*base_middleware()],
        name="finance_agent",
    )
```

`app/agent/multi_agent/rag_agent.py`:
```python
from langchain.agents import create_agent

from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.prompts.specialist_agent_prompts import RAG_SYSTEM_PROMPT
from app.agent.tools import search_knowledge_base_tool, web_search_tool

_TOOLS = [search_knowledge_base_tool, web_search_tool]


def build_rag_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=RAG_SYSTEM_PROMPT,
        middleware=[*base_middleware()],
        name="rag_agent",
    )
```

`app/agent/multi_agent/portfolio_agent.py`:
```python
from langchain.agents import create_agent

from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT
from app.agent.tools import (
    concentration_screen_tool,
    crm_describe_table_tool,
    crm_list_tables_tool,
    crm_tool,
    pct_change_tool,
    portfolio_metrics_tool,
    yf_quote_tool,
)

# Everything a portfolio computation needs lives in this one specialist: the
# supervisor finishes as soon as a specialist returns a plain answer, so
# chaining crm -> finance -> calc across specialists would not work.
_TOOLS = [
    crm_tool,
    crm_list_tables_tool,
    crm_describe_table_tool,
    yf_quote_tool,
    portfolio_metrics_tool,
    pct_change_tool,
    concentration_screen_tool,
]


def build_portfolio_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=PORTFOLIO_SYSTEM_PROMPT,
        middleware=[*base_middleware()],
        name="portfolio_agent",
    )
```

`app/agent/multi_agent/browser_agent.py`:
```python
from langchain.agents import create_agent

from app.agent.multi_agent.common import base_middleware, specialist_model, strip_tool_images
from app.agent.prompts.specialist_agent_prompts import BROWSER_SYSTEM_PROMPT
from app.agent.tools import browser_navigate_tool, browser_screenshot_tool, browser_snapshot_tool

_TOOLS = [browser_navigate_tool, browser_snapshot_tool, browser_screenshot_tool]


def build_browser_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=BROWSER_SYSTEM_PROMPT,
        middleware=[*base_middleware(), strip_tool_images],
        name="browser_agent",
    )
```

- [ ] **Step 4: Rewrite `graph.py`**

The 3 not-yet-migrated specialists (email, filesystem, memory) still return `Command(goto="supervisor", graph=Command.PARENT)`, so they get no static edge yet; Task 3 moves them into `SPECIALISTS`.

`app/agent/multi_agent/graph.py`:
```python
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.store.base import BaseStore

from app.agent.graph import record_question
from app.agent.multi_agent.browser_agent import build_browser_agent
from app.agent.multi_agent.email_agent import build_email_agent
from app.agent.multi_agent.filesystem_agent import build_filesystem_agent
from app.agent.multi_agent.finance_agent import build_finance_agent
from app.agent.multi_agent.memory_agent import build_memory_agent
from app.agent.multi_agent.portfolio_agent import build_portfolio_agent
from app.agent.multi_agent.rag_agent import build_rag_agent
from app.agent.multi_agent.state import SupervisorState
from app.agent.multi_agent.supervisor import supervisor_node

# create_agent specialists: added as subgraph nodes, static edge back to the
# supervisor (they share the `messages` key with SupervisorState).
SPECIALISTS = {
    "rag_agent": lambda: build_rag_agent(),
    "finance_agent": lambda: build_finance_agent(),
    "portfolio_agent": lambda: build_portfolio_agent(),
    "browser_agent": lambda: build_browser_agent(),
}

# Legacy specialists: hand back via Command(graph=Command.PARENT).
_LEGACY_SPECIALISTS = {
    "memory_agent": lambda: build_memory_agent(),
    "filesystem_agent": lambda: build_filesystem_agent(),
    "email_agent": lambda: build_email_agent(),
}


def _build_workflow() -> StateGraph:
    workflow = StateGraph(SupervisorState)
    # record_question converts state["question"] into a HumanMessage — without
    # it the specialists (which read state["messages"]) never see the question.
    workflow.add_node("record_question", record_question)
    workflow.add_node("supervisor", supervisor_node)
    for name, build in SPECIALISTS.items():
        workflow.add_node(name, build())
        workflow.add_edge(name, "supervisor")
    for name, build in _LEGACY_SPECIALISTS.items():
        workflow.add_node(name, build())
    workflow.add_edge(START, "record_question")
    workflow.add_edge("record_question", "supervisor")
    return workflow


def build_multi_agent_app(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
):
    """Build and compile the multi-agent workflow. Specialists are built per
    call (not at import) so tests can patch each module's `specialist_model`.
    NOT wired into the FastAPI lifespan or any router — build and invoke
    directly (ainvoke/astream) in tests or scripts."""
    return _build_workflow().compile(checkpointer=checkpointer, store=store)
```

The lambdas look up `build_<name>_agent` at call time only through the imported name; that is fine because tests patch `specialist_model` inside each specialist module, not the builders.

- [ ] **Step 5: Update the graph-level tests**

`tests/unit/test_multi_agent_graph_structure.py` — keep the 3 existing tests, add:
```python
def test_create_agent_specialists_return_to_supervisor():
    from app.agent.multi_agent.graph import SPECIALISTS
    edges = {(e.source, e.target) for e in _build().get_graph().edges}
    for name in SPECIALISTS:
        assert (name, "supervisor") in edges
```

`tests/unit/test_multi_agent_end_to_end.py` — replace the whole file:
```python
"""End-to-end with every LLM mocked: supervisor routes to a create_agent
specialist, the specialist answers, the static edge brings control back to
the supervisor, which finishes deterministically."""
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import build_multi_agent_app
from app.agent.multi_agent import finance_agent as finance_agent_mod
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision
from tests.unit.fake_chat import FakeToolModel


def test_supervisor_routes_to_finance_then_finishes():
    fake = FakeToolModel([AIMessage(content="AAPL is trading at $200.")])
    with patch.object(finance_agent_mod, "specialist_model", return_value=fake), \
         patch.object(supervisor_mod, "_router") as router_mock:
        router_mock.invoke.return_value = RoutingDecision(next="finance_agent", reasoning="stock question")
        graph = build_multi_agent_app(InMemorySaver())
        result = graph.invoke(
            {"question": "AAPL price?", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0},
            {"configurable": {"thread_id": "t1"}},
        )

    assert result["messages"][-1].content == "AAPL is trading at $200."
    # Deterministic finish: no second routing call after the specialist answered.
    assert router_mock.invoke.call_count == 1
```

`tests/unit/test_multi_agent_question_reaches_messages.py` — replace the whole file:
```python
"""Regression: specialists read state["messages"]; record_question must turn
state["question"] into a HumanMessage they actually receive."""
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import build_multi_agent_app
from app.agent.multi_agent import finance_agent as finance_agent_mod
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision
from tests.unit.fake_chat import FakeToolModel


def test_finance_specialist_sees_the_users_question_as_a_message():
    fake = FakeToolModel([AIMessage(content="AAPL is at $200.")])
    with patch.object(finance_agent_mod, "specialist_model", return_value=fake), \
         patch.object(supervisor_mod, "_router") as router_mock:
        router_mock.invoke.return_value = RoutingDecision(next="finance_agent", reasoning="stock question")
        graph = build_multi_agent_app(InMemorySaver())
        graph.invoke(
            {"question": "What's AAPL trading at?", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0},
            {"configurable": {"thread_id": "t1"}},
        )

    invoked = fake.seen[0]
    assert any(isinstance(m, HumanMessage) and "AAPL" in m.content for m in invoked), invoked
```

- [ ] **Step 6: Run the multi-agent tests, then the full suite**

Run: `uv run pytest tests/unit -k multi_agent -v`
Expected: all pass (email/filesystem/memory tests are still the old ones and still pass).
Run: `uv run pytest tests/ -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/agent/multi_agent tests/unit
git commit -m "refactor(multi-agent): rag/finance/portfolio/browser specialists on create_agent"
```

---

### Task 3: Migrate email, filesystem, memory with `HumanInTheLoopMiddleware`

**Files:**
- Modify (rewrite): `app/agent/multi_agent/email_agent.py`, `filesystem_agent.py`, `memory_agent.py`
- Modify: `app/agent/multi_agent/graph.py` (move the 3 into `SPECIALISTS`, delete `_LEGACY_SPECIALISTS`)
- Test (rewrite): `tests/unit/test_multi_agent_email_agent.py`, `test_multi_agent_filesystem_agent.py`, `test_multi_agent_memory_agent.py`
- Test (create): `tests/unit/test_multi_agent_hitl.py`

**Interfaces:**
- Consumes: Task 1 `common.py`, `FakeToolModel`; Task 2 `graph.SPECIALISTS`.
- Produces: `build_email_agent()`, `build_filesystem_agent()`, `build_memory_agent()`; module `_TOOLS` in each; all 7 specialists in `SPECIALISTS`.

- [ ] **Step 1: Rewrite the 3 specialist test files (failing)**

`tests/unit/test_multi_agent_email_agent.py`:
```python
from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent import email_agent as mod
from app.agent.multi_agent.common import base_middleware


def _kwargs():
    with patch.object(mod, "create_agent") as ca:
        mod.build_email_agent()
    return ca.call_args.kwargs


def test_tools():
    assert {t.name for t in mod._TOOLS} == {"send_email"}


def test_create_agent_call_with_hitl_on_send_email():
    from app.agent.prompts.specialist_agent_prompts import EMAIL_SYSTEM_PROMPT
    kw = _kwargs()
    assert kw["system_prompt"] == EMAIL_SYSTEM_PROMPT
    assert kw["tools"] == mod._TOOLS
    assert kw["name"] == "email_agent"
    mw = kw["middleware"]
    assert [type(m) for m in mw[:3]] == [type(m) for m in base_middleware()]
    assert isinstance(mw[3], HumanInTheLoopMiddleware)
    assert set(mw[3].interrupt_on) == {"send_email"}
    assert len(mw) == 4


def test_builds_a_real_agent_with_hitl_node():
    nodes = mod.build_email_agent().get_graph().nodes
    assert "HumanInTheLoopMiddleware.after_model" in nodes
```

`tests/unit/test_multi_agent_filesystem_agent.py`: same shape with `filesystem`, `FILESYSTEM_SYSTEM_PROMPT`, `name == "filesystem_agent"`,
```python
def test_tools():
    assert {t.name for t in mod._TOOLS} == {"read_text_file", "list_directory", "write_file"}
```
and `assert set(mw[3].interrupt_on) == {"write_file"}`.

`tests/unit/test_multi_agent_memory_agent.py`: same shape with `memory`, `MEMORY_SYSTEM_PROMPT`, `name == "memory_agent"`,
```python
def test_tools():
    assert {t.name for t in mod._TOOLS} == {"save_memory", "recall_memory", "list_memories"}
```
and `assert set(mw[3].interrupt_on) == {"save_memory"}`.

Write each file in full.

- [ ] **Step 2: Write the HITL end-to-end test (failing)**

`tests/unit/test_multi_agent_hitl.py`:
```python
"""HITL through the whole multi-agent graph with the official middleware:
send_email pauses the graph; approve / reject / edit decide what runs."""
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agent.multi_agent import build_multi_agent_app
from app.agent.multi_agent import email_agent as email_mod
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision
from tests.unit.fake_chat import FakeToolModel

SENT = []


@tool("send_email")
async def _fake_send_email(recipient: str, subject: str, body: str) -> str:
    """Fake send."""
    SENT.append({"recipient": recipient, "subject": subject, "body": body})
    return f"sent to {recipient}"


_CALL = {"id": "e1", "name": "send_email",
         "args": {"recipient": "a@example.com", "subject": "Hi", "body": "Report"}}


async def _run_until_interrupt():
    SENT.clear()
    fake = FakeToolModel([AIMessage(content="", tool_calls=[_CALL]), AIMessage(content="Email handled.")])
    patches = [
        patch.object(email_mod, "specialist_model", return_value=fake),
        patch.object(email_mod, "_TOOLS", [_fake_send_email]),
        patch.object(supervisor_mod, "_router"),
    ]
    for p in patches:
        p.start()
    supervisor_mod._router.invoke.return_value = RoutingDecision(next="email_agent", reasoning="email")
    graph = build_multi_agent_app(InMemorySaver())
    cfg = {"configurable": {"thread_id": "hitl"}}
    first = await graph.ainvoke(
        {"question": "email the report", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}, cfg)
    return graph, cfg, first, patches


@pytest.mark.anyio
async def test_send_email_pauses_before_sending():
    graph, cfg, first, patches = await _run_until_interrupt()
    try:
        assert first["__interrupt__"]
        request = first["__interrupt__"][0].value["action_requests"][0]
        assert request["name"] == "send_email"
        assert SENT == []
    finally:
        for p in patches:
            p.stop()


@pytest.mark.anyio
async def test_approve_sends():
    graph, cfg, _, patches = await _run_until_interrupt()
    try:
        result = await graph.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg)
        assert SENT == [_CALL["args"]]
        assert result["messages"][-1].content == "Email handled."
    finally:
        for p in patches:
            p.stop()


@pytest.mark.anyio
async def test_reject_does_not_send():
    graph, cfg, _, patches = await _run_until_interrupt()
    try:
        await graph.ainvoke(Command(resume={"decisions": [{"type": "reject", "message": "not now"}]}), cfg)
        assert SENT == []
    finally:
        for p in patches:
            p.stop()


@pytest.mark.anyio
async def test_edit_sends_the_corrected_email():
    graph, cfg, _, patches = await _run_until_interrupt()
    try:
        edited = {"name": "send_email", "args": {**_CALL["args"], "subject": "Weekly report"}}
        await graph.ainvoke(Command(resume={"decisions": [{"type": "edit", "edited_action": edited}]}), cfg)
        assert SENT == [edited["args"]]
    finally:
        for p in patches:
            p.stop()
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/unit/test_multi_agent_email_agent.py tests/unit/test_multi_agent_filesystem_agent.py tests/unit/test_multi_agent_memory_agent.py tests/unit/test_multi_agent_hitl.py -v`
Expected: FAIL (`_TOOLS` / `create_agent` / `specialist_model` missing on the modules).

- [ ] **Step 4: Rewrite the 3 specialist modules**

`app/agent/multi_agent/email_agent.py`:
```python
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.prompts.specialist_agent_prompts import EMAIL_SYSTEM_PROMPT
from app.agent.tools import send_email_tool

_TOOLS = [send_email_tool]


def build_email_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=EMAIL_SYSTEM_PROMPT,
        middleware=[
            *base_middleware(),
            HumanInTheLoopMiddleware(interrupt_on={"send_email": True}),
        ],
        name="email_agent",
    )
```

`app/agent/multi_agent/filesystem_agent.py`:
```python
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.prompts.specialist_agent_prompts import FILESYSTEM_SYSTEM_PROMPT
from app.agent.tools import fs_list_dir_tool, fs_read_file_tool, fs_write_file_tool

_TOOLS = [fs_read_file_tool, fs_list_dir_tool, fs_write_file_tool]


def build_filesystem_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=FILESYSTEM_SYSTEM_PROMPT,
        middleware=[
            *base_middleware(),
            HumanInTheLoopMiddleware(interrupt_on={"write_file": True}),
        ],
        name="filesystem_agent",
    )
```

`app/agent/multi_agent/memory_agent.py`:
```python
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.prompts.specialist_agent_prompts import MEMORY_SYSTEM_PROMPT
from app.agent.tools import list_memories_tool, recall_memory_tool, save_memory_tool

_TOOLS = [save_memory_tool, recall_memory_tool, list_memories_tool]


def build_memory_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=MEMORY_SYSTEM_PROMPT,
        middleware=[
            *base_middleware(),
            HumanInTheLoopMiddleware(interrupt_on={"save_memory": True}),
        ],
        name="memory_agent",
    )
```

- [ ] **Step 5: Move the 3 into `SPECIALISTS` in `graph.py`**

In `app/agent/multi_agent/graph.py`: add the three entries to `SPECIALISTS`
```python
    "memory_agent": lambda: build_memory_agent(),
    "filesystem_agent": lambda: build_filesystem_agent(),
    "email_agent": lambda: build_email_agent(),
```
delete the `_LEGACY_SPECIALISTS` dict, its comment, and the `for name, build in _LEGACY_SPECIALISTS.items():` loop.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/unit -k "multi_agent" -v`
Expected: all pass, including the 4 HITL tests.
Run: `uv run pytest tests/ -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/agent/multi_agent tests/unit
git commit -m "refactor(multi-agent): email/filesystem/memory on create_agent with HumanInTheLoopMiddleware"
```

---

### Task 4: Cleanup and docs

**Files:**
- Modify: `app/agent/nodes/tool_utils.py` (delete `make_tool_runner` and the now-unused `ToolMessage`/`ToolNode` imports)
- Modify: `tests/unit/test_tool_utils.py` (delete `test_make_tool_runner_sanitizes_tool_message_content`, drop `make_tool_runner` from the import)
- Modify: `app/agent/multi_agent/supervisor.py` — comments only, if any mention `Command.PARENT` or "hands control back"; logic unchanged
- Modify: `CLAUDE.md` (add a "Multi-agent mode" subsection under Architecture)
- Modify: `docs/superpowers/specs/2026-09-24-multi-agent-create-agent-design.md` (Status line → `implemented`)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: nothing new.

- [ ] **Step 1: Confirm `make_tool_runner` is unused outside its test**

Run: `grep -rn "make_tool_runner" app tests --include=*.py`
Expected: only `app/agent/nodes/tool_utils.py` and `tests/unit/test_tool_utils.py`. If anything else references it, stop and keep it.

- [ ] **Step 2: Delete `make_tool_runner` and its test**

In `app/agent/nodes/tool_utils.py` keep only `strip_image_content` (and its docstring); remove `make_tool_runner` and the `ToolMessage` / `ToolNode` imports. In `tests/unit/test_tool_utils.py` remove the `make_tool_runner` import and the `test_make_tool_runner_sanitizes_tool_message_content` test (and any imports that become unused, e.g. `ToolMessage`, `pytest` if nothing else uses it).

- [ ] **Step 3: Grep for stale references**

Run: `grep -rn "Command.PARENT\|_llm_with_tools\|approval_node\|route_after_approval" app/agent/multi_agent tests/unit/test_multi_agent*`
Expected: no matches except comments you now update in `supervisor.py` (reword to "once a specialist returns a plain answer"). Do not change any code in `supervisor.py`.

- [ ] **Step 4: Add the CLAUDE.md subsection**

Insert after the "Human-in-the-Loop (HITL) flow" section of `CLAUDE.md`:
```markdown
### Multi-agent mode (`app/agent/multi_agent/`)

Router pattern: `record_question → supervisor → <specialist> → supervisor → END`. Not wired to the API/UI/voice — build with `build_multi_agent_app(checkpointer)` in tests/scripts.

- One file per specialist (`rag_agent`, `finance_agent`, `portfolio_agent`, `browser_agent`, `email_agent`, `filesystem_agent`, `memory_agent`), each `build_<name>_agent()` → LangChain `create_agent(...)`, added as a subgraph node with a static edge back to `supervisor`.
- `common.py`: `specialist_model()` and `base_middleware()` = `today_prompt` (date in the system prompt), `ModelCallLimitMiddleware(run_limit=10)`, `tool_errors_to_messages` (tool exception → error ToolMessage). Browser also gets `strip_tool_images`.
- HITL uses the official `HumanInTheLoopMiddleware` (email: `send_email`, filesystem: `write_file`, memory: `save_memory`). Resume with `Command(resume={"decisions": [{"type": "approve"} | {"type": "reject", "message": ...} | {"type": "edit", "edited_action": {...}}]})`, one decision per pending call — different from the single-agent `/approve` contract.
```

- [ ] **Step 5: Mark the spec implemented**

In the spec, change `**Status:** approved in brainstorming, awaiting spec review` to `**Status:** implemented`.

- [ ] **Step 6: Full test suite**

Run: `uv run pytest tests/ -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/agent/nodes/tool_utils.py tests/unit/test_tool_utils.py app/agent/multi_agent/supervisor.py CLAUDE.md docs/superpowers/specs/2026-09-24-multi-agent-create-agent-design.md
git commit -m "chore(multi-agent): drop unused make_tool_runner, document create_agent specialists"
```

---

### Task 5: One live pass (controller, not a subagent)

- [ ] **Step 1:** `PYTHONPATH=. uv run python scripts/qa_wealth_db.py` — expect the multi-agent case (routed to `portfolio_agent`, uses `portfolio_metrics`) to pass alongside the 4 single-agent cases.
- [ ] **Step 2:** One HITL check with the real model: run the multi-agent graph on "Send an email to yanivbohbot5@gmail.com with subject 'Test' saying hello", confirm it returns `__interrupt__` with a `send_email` action request, then resume with `{"type": "reject", "message": "test only"}` so nothing is sent.
- [ ] **Step 3:** Report results; no repeated runs to chase LLM variance.
