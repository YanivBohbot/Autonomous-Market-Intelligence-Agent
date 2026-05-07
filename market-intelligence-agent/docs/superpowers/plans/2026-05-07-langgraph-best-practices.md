# LangGraph Best-Practices Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Market Intelligence Agent's LangGraph implementation in line with current LangGraph best practices verified against `/langchain-ai/langgraph` Context7 docs.

**Architecture:** Four focused refactors — (1) switch `messages` reducer to `add_messages` (kills the orphan-tool-call hack), (2) centralize `TOOLS` list, (3) hoist LLM/embedding/Pinecone/Tavily clients to module scope, (4) replace legacy `interrupt_before=["tools"]` with dynamic `interrupt()` + `Command(resume=...)`. Plus a cosmetic `START` cleanup. Each task is independently shippable with tests.

**Out of scope (intentionally dropped after review):**
- Batch grader — sequential is fine for k=3.
- Explicit `recursion_limit` — default of 25 is sufficient.
- `AsyncSqliteSaver` — sync `SqliteSaver` + `asyncio.to_thread` already works correctly.

**Tech Stack:** Python 3.12, LangGraph, LangChain, LangChain-OpenAI, Pinecone, Tavily, FastAPI, pytest.

---

## File Structure

**Modify:**
- `app/agent/state.py` — swap reducer
- `app/agent/nodes/generate.py` — module-level LLM, drop `_sanitize_messages` hack
- `app/agent/nodes/grader.py` — module-level LLM, batched grading
- `app/agent/nodes/rag.py` — module-level embeddings + vectorstore
- `app/agent/nodes/research.py` — module-level Tavily client
- `app/agent/graph.py` — use centralized TOOLS, switch HITL pattern, use `START`
- `app/api/routers/approve.py` — adapt to `Command(resume=...)`
- `app/api/routers/stream.py` — pass `recursion_limit` config

**Create:**
- `app/agent/tools/__init__.py` — exports `TOOLS = [send_email_tool, crm_tool]`
- `tests/unit/test_state_reducer.py`
- `tests/unit/test_grader_batch.py`
- `tests/unit/test_graph_recursion_limit.py`
- `tests/unit/test_hitl_interrupt.py`

---

## Task 1: Switch `messages` reducer to `add_messages`

**Why:** Per LangGraph docs, `add_messages` merges by message ID — appends new, replaces same-ID, supports `RemoveMessage`. `operator.add` blindly concatenates and is the root cause of the orphan-tool-call bug currently patched by `_sanitize_messages` in `generate.py`.

**Files:**
- Modify: `app/agent/state.py`
- Modify: `app/agent/nodes/generate.py` (remove sanitize helper)
- Test: `tests/unit/test_state_reducer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_state_reducer.py
from langchain_core.messages import HumanMessage, AIMessage
from app.agent.state import AgentState
from langgraph.graph.message import add_messages


def test_state_uses_add_messages_reducer():
    # AgentState.messages must use add_messages, not operator.add
    annotations = AgentState.__annotations__["messages"]
    # Annotated[list[AnyMessage], add_messages] -> reducer in __metadata__
    assert add_messages in annotations.__metadata__


def test_add_messages_replaces_by_id():
    base = [HumanMessage(content="hi", id="1")]
    update = [HumanMessage(content="hi again", id="1")]
    merged = add_messages(base, update)
    assert len(merged) == 1
    assert merged[0].content == "hi again"
```

- [ ] **Step 2: Run test to verify it fails**

```
cd market-intelligence-agent
pytest tests/unit/test_state_reducer.py -v
```
Expected: FAIL on `test_state_uses_add_messages_reducer` (currently `operator.add`).

- [ ] **Step 3: Update `app/agent/state.py`**

```python
from typing import Annotated, List, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    question: str
    documents: List[str]
```

- [ ] **Step 4: Remove `_sanitize_messages` hack from `generate.py`**

In `app/agent/nodes/generate.py` delete lines 12–31 (the `_sanitize_messages` function) and replace the call site `msgs.extend(_sanitize_messages(messages))` with `msgs.extend(messages)`.

- [ ] **Step 5: Run tests, verify pass and no regressions**

```
pytest tests/unit/ -v
```
Expected: PASS for new tests, no regression in existing `test_grader.py` / `test_stream.py`.

- [ ] **Step 6: Commit**

```bash
git add app/agent/state.py app/agent/nodes/generate.py tests/unit/test_state_reducer.py
git commit -m "refactor(state): use add_messages reducer; drop orphan tool-call sanitizer"
```

---

## Task 2: Centralize `TOOLS` list

**Why:** `[send_email_tool, crm_tool]` is duplicated in `graph.py:25` and `generate.py:56`. Drift risk. DRY.

**Files:**
- Create: `app/agent/tools/__init__.py`
- Modify: `app/agent/graph.py`
- Modify: `app/agent/nodes/generate.py`

- [ ] **Step 1: Create `app/agent/tools/__init__.py`**

```python
from app.agent.tools.emails import send_email_tool
from app.agent.tools.mcp_clients.mcp_client import crm_tool

TOOLS = [send_email_tool, crm_tool]

__all__ = ["TOOLS", "send_email_tool", "crm_tool"]
```

- [ ] **Step 2: Update `app/agent/graph.py`**

Replace lines 8–9 and 25:
```python
from app.agent.tools import TOOLS
# ...
workflow.add_node("tools", ToolNode(TOOLS))
```
Remove the now-unused individual tool imports.

- [ ] **Step 3: Update `app/agent/nodes/generate.py`**

Replace tool imports and `bind_tools` call:
```python
from app.agent.tools import TOOLS
# ...
llm_with_tools = llm.bind_tools(TOOLS)
```

- [ ] **Step 4: Run full test suite**

```
pytest tests/ -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools/__init__.py app/agent/graph.py app/agent/nodes/generate.py
git commit -m "refactor(tools): centralize TOOLS list to single source of truth"
```

---

## Task 3: Hoist LLM/embedding/Tavily/Pinecone clients to module scope

**Why:** Each node currently rebuilds expensive clients (HTTP pools, embeddings, vector store handles) per invocation. Module-scope instantiation is the LangGraph idiom and saves latency + connection thrash.

**Files:**
- Modify: `app/agent/nodes/generate.py`
- Modify: `app/agent/nodes/grader.py`
- Modify: `app/agent/nodes/rag.py`
- Modify: `app/agent/nodes/research.py`

- [ ] **Step 1: Update `app/agent/nodes/grader.py`**

```python
import logging
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from app.core.config import settings
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


class GradeDocument(BaseModel):
    binary_score: str = Field(description="'yes' or 'no'")


_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
_grader = _llm.with_structured_output(GradeDocument)


def grade_documents(state: AgentState) -> dict:
    logger.info("GRADER: Scoring %d documents", len(state["documents"]))
    question = state["question"]
    documents = state["documents"]
    system_prompt = "Does the document answer the question? Answer 'yes' or 'no'."
    filtered_docs = []
    for doc in documents:
        res = _grader.invoke(f"Question: {question}\nDoc: {doc}\n{system_prompt}")
        if res.binary_score == "yes":
            filtered_docs.append(doc)
    logger.info("GRADER: Kept %d/%d documents", len(filtered_docs), len(documents))
    return {"documents": filtered_docs}
```

- [ ] **Step 2: Update `app/agent/nodes/rag.py`**

```python
import logging
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from app.core.config import settings
from app.agent.state import AgentState

logger = logging.getLogger(__name__)

_embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
_vectorstore = PineconeVectorStore(
    index_name=settings.PINECONE_INDEX_NAME, embedding=_embeddings
)


def retrieve_internal_documentation(state: AgentState) -> dict:
    logger.info("RAG: Starting internal document search")
    docs = _vectorstore.similarity_search(state["question"], k=settings.RAG_TOP_K)
    content = [f"[INTERNAL Resource] {d.page_content}" for d in docs]
    logger.info("RAG: Retrieved %d chunks", len(content))
    return {"documents": content}
```

(If `RAG_TOP_K` does not exist in `settings`, add it as `RAG_TOP_K: int = 3` in `app/core/config.py` in the same commit.)

- [ ] **Step 3: Update `app/agent/nodes/research.py`**

```python
import logging
from tavily import TavilyClient
from app.core.config import settings
from app.agent.state import AgentState

logger = logging.getLogger(__name__)

_tavily = TavilyClient(api_key=settings.TAVILY_API_KEY)


def web_search(state: AgentState) -> dict:
    logger.info("WEB_SEARCH: Querying Tavily")
    response = _tavily.search(
        query=state["question"], max_results=3, search_depth="advanced"
    )
    web_results = [
        f"[SOURCE WEB: {r['url']}] {r['content']}" for r in response["results"]
    ]
    logger.info("WEB_SEARCH: Got %d results", len(web_results))
    return {"documents": web_results}
```

- [ ] **Step 4: Update `app/agent/nodes/generate.py`**

At module scope (after imports):
```python
_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True)
_llm_with_tools = _llm.bind_tools(TOOLS)
```
Replace the two in-function `ChatOpenAI(...)` constructions with `_llm` and `_llm_with_tools`.

- [ ] **Step 5: Run all tests**

```
pytest tests/ -v
```
Expected: PASS. Existing `test_grader.py` mocks `ChatOpenAI` — verify it still patches the right symbol; if the test imported `ChatOpenAI` from `grader.py`, patch path may need updating to `app.agent.nodes.grader._grader` or similar.

- [ ] **Step 6: Commit**

```bash
git add app/agent/nodes/ app/core/config.py
git commit -m "perf(nodes): hoist LLM/embeddings/Tavily/Pinecone clients to module scope"
```

---

## Task 4: Parallelize the grader with `.batch()`

**Why:** Currently `grader.py` invokes the LLM serially per document. `Runnable.batch()` runs them concurrently — `k=3` becomes ~1× latency instead of 3×.

**Files:**
- Modify: `app/agent/nodes/grader.py`
- Test: `tests/unit/test_grader_batch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_grader_batch.py
from unittest.mock import MagicMock, patch
from app.agent.nodes import grader as grader_mod


def test_grader_uses_batch():
    state = {"question": "q", "documents": ["d1", "d2", "d3"]}
    with patch.object(grader_mod, "_grader") as mock:
        mock.batch.return_value = [
            grader_mod.GradeDocument(binary_score="yes"),
            grader_mod.GradeDocument(binary_score="no"),
            grader_mod.GradeDocument(binary_score="yes"),
        ]
        result = grader_mod.grade_documents(state)
    mock.batch.assert_called_once()
    assert result == {"documents": ["d1", "d3"]}
```

- [ ] **Step 2: Run test, verify failure**

```
pytest tests/unit/test_grader_batch.py -v
```
Expected: FAIL — `_grader.invoke` is called per doc, not `.batch`.

- [ ] **Step 3: Refactor `grade_documents` to use `.batch()`**

```python
def grade_documents(state: AgentState) -> dict:
    logger.info("GRADER: Scoring %d documents", len(state["documents"]))
    question = state["question"]
    documents = state["documents"]
    system_prompt = "Does the document answer the question? Answer 'yes' or 'no'."
    prompts = [f"Question: {question}\nDoc: {d}\n{system_prompt}" for d in documents]
    if not prompts:
        return {"documents": []}
    grades = _grader.batch(prompts)
    filtered_docs = [doc for doc, g in zip(documents, grades) if g.binary_score == "yes"]
    logger.info("GRADER: Kept %d/%d documents", len(filtered_docs), len(documents))
    return {"documents": filtered_docs}
```

- [ ] **Step 4: Run tests**

```
pytest tests/unit/ -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/nodes/grader.py tests/unit/test_grader_batch.py
git commit -m "perf(grader): batch document grading for parallel LLM calls"
```

---

## Task 5: Add `recursion_limit` to invocations

**Why:** The `tools → generate → tools` cycle has no guard against runaway loops. LangGraph default is 25 — explicit lower limit is safer.

**Files:**
- Modify: `app/api/routers/stream.py`
- Modify: `app/api/routers/approve.py`
- Test: `tests/unit/test_graph_recursion_limit.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_graph_recursion_limit.py
from app.api.routers.stream import _build_config


def test_stream_config_includes_recursion_limit():
    config = _build_config(thread_id="t1")
    assert config["recursion_limit"] == 10
    assert config["configurable"]["thread_id"] == "t1"
```

- [ ] **Step 2: Run, verify failure (helper does not exist)**

```
pytest tests/unit/test_graph_recursion_limit.py -v
```
Expected: FAIL — ImportError.

- [ ] **Step 3: Add `_build_config` helper in `app/api/routers/stream.py`**

Top of file, after imports:
```python
RECURSION_LIMIT = 10


def _build_config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }
```
Replace `config = {"configurable": {"thread_id": request.thread_id}}` with `config = _build_config(request.thread_id)`.

- [ ] **Step 4: Apply same helper in `approve.py`**

```python
from app.api.routers.stream import _build_config
# ...
config = _build_config(request.thread_id)
```

- [ ] **Step 5: Run tests**

```
pytest tests/ -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/stream.py app/api/routers/approve.py tests/unit/test_graph_recursion_limit.py
git commit -m "feat(safety): cap agent runs with recursion_limit=10"
```

---

## Task 6: Use `START` constant in graph wiring

**Why:** Modern LangGraph idiom is `add_edge(START, "node")` instead of `set_entry_point`. Cosmetic but aligns with all docs.

**Files:**
- Modify: `app/agent/graph.py`

- [ ] **Step 1: Update imports and entry-point wiring**

```python
from langgraph.graph import StateGraph, START, END
# ...
workflow.add_edge(START, "rag")  # replaces workflow.set_entry_point("rag")
```

- [ ] **Step 2: Run tests**

```
pytest tests/ -v
```
Expected: PASS (behavior identical).

- [ ] **Step 3: Commit**

```bash
git add app/agent/graph.py
git commit -m "style(graph): use START constant for entry-point edge"
```

---

## Task 7: Migrate HITL from `interrupt_before` to dynamic `interrupt()`

**Why:** Per current LangGraph docs the canonical HITL pattern is the dynamic `interrupt()` function inside a node, resumed with `Command(resume=...)`. It supports per-action approval payloads, structured action requests (`HumanInterrupt`), and cleaner edit/accept/reject flows. `interrupt_before=["tools"]` is the legacy breakpoint mechanism.

**This is the largest task — split into TDD-sized steps.**

**Files:**
- Modify: `app/agent/graph.py`
- Modify: `app/api/routers/approve.py`
- Test: `tests/unit/test_hitl_interrupt.py`

- [ ] **Step 1: Write the failing test for an approval node**

```python
# tests/unit/test_hitl_interrupt.py
from langgraph.types import Command
from app.agent.graph import agent_app


def test_graph_pauses_on_tool_call_via_interrupt():
    config = {
        "configurable": {"thread_id": "hitl-test-1"},
        "recursion_limit": 10,
    }
    # Seed an AIMessage with tool_calls into state, then run
    from langchain_core.messages import AIMessage
    seed = {
        "question": "send report",
        "documents": [],
        "messages": [AIMessage(
            content="",
            tool_calls=[{"name": "send_email", "args": {"recipient": "x@y", "subject": "s", "body": "b"}, "id": "tc1"}],
        )],
    }
    # Manually drive into approval node by injecting state
    agent_app.update_state(config, seed, as_node="generate")
    result = agent_app.invoke(None, config)
    assert "__interrupt__" in result


def test_graph_resumes_with_command_approve():
    config = {
        "configurable": {"thread_id": "hitl-test-2"},
        "recursion_limit": 10,
    }
    # Setup as above, then resume
    # ... (test scaffold; full body filled at implementation time)
```

- [ ] **Step 2: Run, verify failure**

```
pytest tests/unit/test_hitl_interrupt.py -v
```
Expected: FAIL — graph still uses `interrupt_before`, no approval node.

- [ ] **Step 3: Add an `approval` node in `app/agent/graph.py`**

```python
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import AIMessage
from app.agent.state import AgentState
from app.agent.nodes.rag import retrieve_internal_documentation
from app.agent.nodes.research import web_search
from app.agent.nodes.grader import grade_documents
from app.agent.nodes.generate import generate_answer
from app.agent.tools import TOOLS
from app.agent.memory.checkpointer import create_checkpointer


def approval_node(state: AgentState) -> dict:
    """Pause graph; surface pending tool calls to the human; resume with decision."""
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    # Per docs, action_request is a single dict and interrupt() is list-wrapped.
    # We surface the first tool call (the only one in single-action flows).
    tc = tool_calls[0]
    request = {
        "action_request": {"action": tc["name"], "args": tc["args"]},
        "config": {
            "allow_ignore": False,
            "allow_respond": False,
            "allow_edit": False,
            "allow_accept": True,
        },
        "description": f"Approve or reject {tc['name']}({tc['args']})",
    }
    response = interrupt([request])[0]
    decision = response if isinstance(response, str) else response.get("type", "reject")
    # decision is whatever the resumer passed via Command(resume=...)
    if decision == "approve":
        return {}
    # Reject: replace AIMessage tool_calls with cancellation ToolMessages elsewhere
    from langchain_core.messages import ToolMessage
    cancel_msgs = [
        ToolMessage(content="Action cancelled by user.", tool_call_id=tc["id"], name=tc["name"])
        for tc in tool_calls
    ]
    return {"messages": cancel_msgs}


def decide_next_step(state: AgentState):
    return "generate" if len(state["documents"]) > 0 else "web_search"


def route_after_generate(state: AgentState):
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "approval"
    return END


def route_after_approval(state: AgentState):
    last = state["messages"][-1]
    # If last message is a cancellation ToolMessage, skip tools
    from langchain_core.messages import ToolMessage
    if isinstance(last, ToolMessage):
        return "generate"
    return "tools"


workflow = StateGraph(AgentState)
workflow.add_node("rag", retrieve_internal_documentation)
workflow.add_node("grader", grade_documents)
workflow.add_node("web_search", web_search)
workflow.add_node("generate", generate_answer)
workflow.add_node("approval", approval_node)
workflow.add_node("tools", ToolNode(TOOLS))

workflow.add_edge(START, "rag")
workflow.add_edge("rag", "grader")
workflow.add_conditional_edges("grader", decide_next_step, {"generate": "generate", "web_search": "web_search"})
workflow.add_edge("web_search", "generate")
workflow.add_conditional_edges("generate", route_after_generate, {"approval": "approval", END: END})
workflow.add_conditional_edges("approval", route_after_approval, {"tools": "tools", "generate": "generate"})
workflow.add_edge("tools", "generate")

agent_app = workflow.compile(checkpointer=create_checkpointer())
# Note: NO interrupt_before — interrupt() inside approval_node handles HITL
```

- [ ] **Step 4: Update `app/api/routers/approve.py` to use `Command(resume=...)`**

```python
import asyncio
import logging
from fastapi import APIRouter
from langgraph.types import Command
from app.agent.graph import agent_app
from app.api.models.models import ChatResponse, ApproveRequest
from app.api.routers._helpers import get_action_description
from app.api.routers.stream import _build_config

logger = logging.getLogger(__name__)
router = APIRouter()


def _safe_content(state: dict) -> str:
    if "messages" not in state or not state["messages"]:
        return "Aucune réponse générée."
    content = state["messages"][-1].content
    if content is None:
        return ""
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict) and "text" in c)
    return str(content)


@router.post("/approve", response_model=ChatResponse)
async def approve_endpoint(request: ApproveRequest):
    config = _build_config(request.thread_id)
    snapshot = agent_app.get_state(config)
    if not snapshot.next:
        return {"response": "⚠️ Session expirée ou terminée.", "status": "completed", "next_step": None}

    decision = "approve" if request.approved else "reject"
    logger.info("HITL decision=%s for thread %s", decision, request.thread_id)
    final_state = await asyncio.to_thread(agent_app.invoke, Command(resume=decision), config)

    snapshot = agent_app.get_state(config)
    if snapshot.next:
        last = final_state["messages"][-1]
        return {
            "response": f"⏸️ NOUVELLE ACTION REQUISE : {get_action_description(last)}",
            "status": "interrupted",
            "next_step": str(snapshot.next),
        }
    return {"response": _safe_content(final_state), "status": "completed", "next_step": None}
```

- [ ] **Step 5: Update `stream.py` interrupt detection**

`stream.py` already uses `snapshot.next` — works the same with dynamic interrupt. Verify by running the integration test.

- [ ] **Step 6: Run full test suite**

```
pytest tests/ -v
```
Expected: PASS for new HITL tests; existing approve/stream tests may need minor updates (decision string instead of bool path).

- [ ] **Step 7: Manual smoke test**

```
uvicorn app.api.server:app --reload
```
- POST `/stream` with a query that triggers `send_email`.
- Verify SSE emits `interrupted` event.
- POST `/approve` with `approved=true` → tool runs.
- POST `/approve` with `approved=false` → cancellation message returned.

- [ ] **Step 8: Commit**

```bash
git add app/agent/graph.py app/api/routers/approve.py tests/unit/test_hitl_interrupt.py
git commit -m "feat(hitl): migrate to dynamic interrupt()+Command(resume) HITL pattern"
```

---

---

## Task 8: Modernize `SqliteSaver` lifecycle (latest docs alignment)

**Why:** Latest LangGraph docs (`/langchain-ai/langgraph` Context7, checkpoint-sqlite README) show the canonical pattern is `SqliteSaver.from_conn_string(path)` used as a context manager (or `AsyncSqliteSaver` for async apps). Current `checkpointer.py` uses raw `sqlite3.connect(...)` which works but bypasses documented setup hooks and connection management. Since FastAPI endpoints are async (`asyncio.to_thread(agent_app.invoke, ...)`), `AsyncSqliteSaver` is the right primitive.

**Files:**
- Modify: `app/agent/memory/checkpointer.py`
- Modify: `app/api/server.py` (lifespan to manage saver context)
- Modify: `app/agent/graph.py` (defer compile to runtime)

- [ ] **Step 1: Refactor `checkpointer.py` to expose async factory**

```python
# app/agent/memory/checkpointer.py
import os
from contextlib import asynccontextmanager
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.core.config import settings


@asynccontextmanager
async def checkpointer_context(db_path: str | None = None):
    path = db_path or settings.CHECKPOINT_DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        yield saver
```

- [ ] **Step 2: Move graph compilation behind a builder**

`graph.py` exposes a `build_agent_app(checkpointer)` factory instead of a module-level `agent_app`:

```python
def build_agent_app(checkpointer):
    return workflow.compile(checkpointer=checkpointer)
```

- [ ] **Step 3: Wire FastAPI lifespan in `server.py`**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.agent.memory.checkpointer import checkpointer_context
from app.agent.graph import build_agent_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with checkpointer_context() as saver:
        app.state.agent_app = build_agent_app(saver)
        yield


app = FastAPI(lifespan=lifespan)
```

- [ ] **Step 4: Update routers to read from `app.state`**

Both `stream.py` and `approve.py`: replace `from app.agent.graph import agent_app` with `request.app.state.agent_app` (FastAPI request dependency).

- [ ] **Step 5: Remove `asyncio.to_thread` in `approve.py`** — async saver allows direct `await agent_app.ainvoke(...)`.

- [ ] **Step 6: Run full test + smoke test**

```
pytest tests/ -v
uvicorn app.api.server:app --reload
```
Expected: PASS; checkpoints persist across restarts; no "database is locked" errors.

- [ ] **Step 7: Commit**

```bash
git add app/agent/memory/checkpointer.py app/agent/graph.py app/api/server.py app/api/routers/
git commit -m "refactor(checkpoint): use AsyncSqliteSaver with FastAPI lifespan"
```

---

## Self-Review Checklist (executed before handoff)

- **Spec coverage:** All 6 audit findings (reducer, module-level clients, TOOLS dedup, batch grader, recursion_limit, dynamic interrupt) plus the `START` cleanup are addressed in Tasks 1–7. ✅
- **Placeholder scan:** All code blocks contain real implementations; one test scaffold note in Task 7 Step 1 is explicit ("filled at implementation time" — flagged, acceptable for a stretch HITL test).
- **Type consistency:** `TOOLS`, `_llm`, `_grader`, `_vectorstore`, `_embeddings`, `_tavily`, `_build_config`, `RECURSION_LIMIT` used consistently across tasks. ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-07-langgraph-best-practices.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
