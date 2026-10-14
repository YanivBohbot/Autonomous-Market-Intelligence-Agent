# Research Conversation History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Research gets a conversation history panel (list, reopen, new, semantic search, rename, delete) backed by a durable LangGraph store that also makes `save_memory` facts survive restarts.

**Architecture:** `create_store()` becomes an async context manager (`AsyncSqliteStore` with a vector index locally, `InMemoryStore` otherwise). The graph's `record_question` node upserts a `("conversations",)` store item for every `desk_*` thread. A deterministic `/conversations` router lists/searches/renames/deletes (delete = `checkpointer.adelete_thread` + store delete). React `/research` becomes `ResearchPage` = `ConversationPanel` + `DeskView`, with the open thread in `?c=`.

**Tech Stack:** LangGraph 1.x store API (`AsyncSqliteStore`, `InMemoryStore`, `IndexConfig`), `langgraph.config.get_store`, FastAPI, React 18 + react-router-dom, vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-research-conversation-history-design.md`

## Global Constraints

- All commands from `market-intelligence-agent/` with `uv run`; frontend commands from `frontend/`.
- Branch `feat/conversation-history`. Never `git push`.
- Never stage `app/agent/orchestration/supervisor.py`, `app/agent/tools/portfolio_report.py`, `app/core/config.py` (user WIP). Stage files by explicit path only. **Do not edit `app/core/config.py`** — store env vars are read with `os.environ` in `store.py` (same as `MIA_MEMORY_ID` in `checkpointer.py`).
- UI copy in English: "+ New conversation", "Search conversations…", "Rename", "Delete", "Delete this conversation? This cannot be undone.", "Couldn't load conversations", "Retry", "No conversations yet".
- Index only thread ids starting with `desk_`. Title = first question, whitespace-collapsed, max 60 chars (`…` appended when cut). Keep last 10 questions, each max 300 chars.
- Embeddings: `get_embeddings()` from `app/rag/vectorstore.py` (1536 dims). Unit tests never hit the network: `DeterministicFakeEmbedding`.
- Indexing errors never fail a turn (log + continue).
- Keep `docs/TOOLS.md` / `CLAUDE.md` in sync (project rule).
- After the last task, restart the backend (no `--reload`) and run a live check.

## Review Focus

1. A rename followed by a new question must keep the renamed title — pinned in Task 2 (`test_rename_survives_later_turn`).
2. A nonsense search (`q` unrelated to anything) should not return the whole list in random order — `SEARCH_MIN_SCORE` filter, pinned in Task 2 (`test_search_drops_low_scores`); real threshold checked live in Task 7.
3. `?c=` pointing at a non-`desk_` or garbage id must not open a client thread in Research — pinned in Task 6 (`ignores a non-desk c param`).
4. Deleting the open conversation must not leave the chat on a deleted thread — pinned in Task 5/6 (`deleting the active conversation opens a new one`).
5. The store's sqlite file must survive a restart for `user_facts` — pinned in Task 1 (`test_sqlite_store_persists_across_reopen`).

---

### Task 1: Durable store factory

**Files:**
- Modify: `app/agent/memory/store.py`
- Modify: `app/api/server.py` (lifespan)
- Modify: `app/agent/tools/memory.py` (`save_memory` → `index=False`)
- Test: `tests/unit/test_store_factory.py` (create), `tests/unit/test_server_wiring.py`

**Interfaces:**
- Produces: `create_store(db_path: str | None = None, embeddings: Embeddings | None = None) -> AsyncContextManager[BaseStore]`; `CONVERSATION_INDEX_FIELDS = ["text"]`; `app.state.store`, `app.state.checkpointer` set in lifespan.

Backend choice: `STORE_BACKEND` env (`sqlite` | `memory`); unset → `sqlite` when `settings.CHECKPOINTER_BACKEND == "sqlite"`, else `memory` (so AgentCore, which sets `agentcore`, gets `memory` with no prod/iac change). `STORE_DB_PATH` env, default `data/store.db`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_store_factory.py`:

```python
import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langgraph.store.memory import InMemoryStore

from app.agent.memory import store as store_mod
from app.agent.memory.store import create_store

FAKE = DeterministicFakeEmbedding(size=1536)


@pytest.mark.anyio
async def test_sqlite_store_persists_across_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "sqlite")
    path = str(tmp_path / "store.db")
    async with create_store(path, embeddings=FAKE) as s:
        await s.aput(("user_facts",), "email", {"value": "a@b.c"}, index=False)
    async with create_store(path, embeddings=FAKE) as s:
        item = await s.aget(("user_facts",), "email")
    assert item.value == {"value": "a@b.c"}


@pytest.mark.anyio
async def test_sqlite_store_semantic_search(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "sqlite")
    async with create_store(str(tmp_path / "s.db"), embeddings=FAKE) as s:
        await s.aput(("conversations",), "desk_a", {"text": "NVDA vs AMD"})
        await s.aput(("conversations",), "desk_b", {"text": "Cohen portfolio"})
        hits = await s.asearch(("conversations",), query="NVDA vs AMD", limit=1)
    assert hits[0].key == "desk_a"


@pytest.mark.anyio
async def test_memory_backend(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    async with create_store(embeddings=FAKE) as s:
        assert isinstance(s, InMemoryStore)


@pytest.mark.anyio
async def test_default_backend_follows_checkpointer(monkeypatch):
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setattr(store_mod.settings, "CHECKPOINTER_BACKEND", "agentcore")
    async with create_store(embeddings=FAKE) as s:
        assert isinstance(s, InMemoryStore)


@pytest.mark.anyio
async def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "nope")
    with pytest.raises(ValueError):
        async with create_store(embeddings=FAKE):
            pass
```

Add to `tests/unit/test_server_wiring.py::test_lifespan_shares_one_multi_agent_graph_across_transports`, inside the `async with`:

```python
        assert test_app.state.store is not None
        assert test_app.state.checkpointer is not None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_store_factory.py tests/unit/test_server_wiring.py -v`
Expected: FAIL (`create_store` is not an async context manager / takes no args; `app.state.store` missing).

- [ ] **Step 3: Implement**

`app/agent/memory/store.py`:

```python
"""Store factory — the LangGraph BaseStore passed to workflow.compile(store=...).

Holds cross-thread data: ("user_facts",) for the memory tools and
("conversations",) for the Research history index (vector-indexed on the
item's "text" field, so the history can be searched by meaning).

Backends, selected via `STORE_BACKEND` env (read here, like MIA_MEMORY_ID in
checkpointer.py):
- `sqlite`: `AsyncSqliteStore` in `STORE_DB_PATH` (default data/store.db) —
  durable across restarts. Default when the checkpointer is sqlite (local dev).
- `memory`: `InMemoryStore` — tests and the AgentCore image (default there,
  since its CHECKPOINTER_BACKEND is agentcore).
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langchain_core.embeddings import Embeddings
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from app.core.config import settings

logger = logging.getLogger(__name__)

CONVERSATION_INDEX_FIELDS = ["text"]
EMBEDDING_DIMS = 1536  # text-embedding-3-small


def _backend() -> str:
    configured = os.environ.get("STORE_BACKEND", "").strip().lower()
    if configured:
        return configured
    return "sqlite" if settings.CHECKPOINTER_BACKEND.lower() == "sqlite" else "memory"


def _index(embeddings: Embeddings | None) -> dict:
    if embeddings is None:
        from app.rag.vectorstore import get_embeddings

        embeddings = get_embeddings()
    return {"dims": EMBEDDING_DIMS, "embed": embeddings, "fields": CONVERSATION_INDEX_FIELDS}


@asynccontextmanager
async def create_store(
    db_path: str | None = None, embeddings: Embeddings | None = None
) -> AsyncIterator[BaseStore]:
    backend = _backend()
    if backend == "sqlite":
        # Lazy import: aiosqlite / sqlite-vec are not in the AgentCore image.
        from langgraph.store.sqlite.aio import AsyncSqliteStore

        path = db_path or os.environ.get("STORE_DB_PATH", "data/store.db")
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        logger.info("store backend=sqlite path=%s", path)
        async with AsyncSqliteStore.from_conn_string(path, index=_index(embeddings)) as store:
            await store.setup()
            yield store
        return
    if backend == "memory":
        logger.info("store backend=memory (lost on restart)")
        yield InMemoryStore(index=_index(embeddings))
        return
    raise ValueError(f"Unknown STORE_BACKEND={backend!r} (expected sqlite or memory)")
```

`app/api/server.py` lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with create_checkpointer() as checkpointer, create_store() as store:
        agent_graph = build_multi_agent_app(checkpointer, store)
        app.state.checkpointer = checkpointer
        app.state.store = store
        app.state.agent_app = agent_graph
        ...  # rest unchanged
        yield
```

`app/agent/tools/memory.py` `save_memory`: `await store.aput(USER_FACTS_NS, key, {"value": value}, index=False)` (facts are looked up by key, never embedded).

Check other `create_store()` callers: `grep -rn "create_store" app tests prod` — update any sync call to the async context manager form.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_store_factory.py tests/unit/test_server_wiring.py tests/unit/test_multi_agent_memory_agent.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/memory/store.py app/api/server.py app/agent/tools/memory.py tests/unit/test_store_factory.py tests/unit/test_server_wiring.py
git commit -m "feat(store): durable AsyncSqliteStore with vector index; memory facts survive restarts"
```

---

### Task 2: Conversation index module

**Files:**
- Create: `app/agent/memory/conversations.py`
- Test: `tests/unit/test_conversations_index.py`

**Interfaces:**
- Consumes: a `BaseStore` with index on `["text"]` (Task 1); a `BaseCheckpointSaver` with `adelete_thread`.
- Produces:
  - `NAMESPACE = ("conversations",)`, `RESEARCH_PREFIX = "desk_"`, `SEARCH_MIN_SCORE = 0.25`
  - `is_research_thread(thread_id: str) -> bool`
  - `async record_conversation_turn(store, thread_id: str, question: str, now: datetime | None = None) -> None`
  - `async list_conversations(store, query: str | None = None, limit: int = 50) -> list[dict]` → `[{"id", "title", "created_at", "updated_at"}]`
  - `async rename_conversation(store, thread_id: str, title: str) -> dict | None`
  - `async delete_conversation(store, checkpointer, thread_id: str) -> None`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import datetime, timedelta, timezone

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.store.memory import InMemoryStore

from app.agent.memory import conversations as conv

T0 = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)


def _store():
    return InMemoryStore(index={"dims": 64, "embed": DeterministicFakeEmbedding(size=64), "fields": ["text"]})


@pytest.mark.anyio
async def test_first_turn_creates_item_with_truncated_title():
    s = _store()
    q = "Compare   NVDA and AMD over the last six months, including valuation and momentum please"
    await conv.record_conversation_turn(s, "desk_a", q, now=T0)
    item = (await s.aget(conv.NAMESPACE, "desk_a")).value
    assert item["title"] == "Compare NVDA and AMD over the last six months, including val…"
    assert len(item["title"]) == 61
    assert item["created_at"] == item["updated_at"] == T0.isoformat()
    assert item["questions"] == [" ".join(q.split())]
    assert item["title"] in item["text"]


@pytest.mark.anyio
async def test_later_turn_keeps_title_and_updates():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "First", now=T0)
    await conv.record_conversation_turn(s, "desk_a", "Second", now=T0 + timedelta(hours=1))
    item = (await s.aget(conv.NAMESPACE, "desk_a")).value
    assert item["title"] == "First"
    assert item["created_at"] == T0.isoformat()
    assert item["updated_at"] == (T0 + timedelta(hours=1)).isoformat()
    assert item["questions"] == ["First", "Second"]


@pytest.mark.anyio
async def test_keeps_last_ten_questions():
    s = _store()
    for i in range(12):
        await conv.record_conversation_turn(s, "desk_a", f"q{i}", now=T0)
    assert (await s.aget(conv.NAMESPACE, "desk_a")).value["questions"] == [f"q{i}" for i in range(2, 12)]


@pytest.mark.anyio
async def test_rename_survives_later_turn():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "First", now=T0)
    assert (await conv.rename_conversation(s, "desk_a", "  Chip stocks  "))["title"] == "Chip stocks"
    await conv.record_conversation_turn(s, "desk_a", "Second", now=T0)
    assert (await s.aget(conv.NAMESPACE, "desk_a")).value["title"] == "Chip stocks"


@pytest.mark.anyio
async def test_rename_unknown_returns_none():
    assert await conv.rename_conversation(_store(), "desk_x", "T") is None


@pytest.mark.anyio
async def test_non_research_threads_are_ignored():
    s = _store()
    for tid in ("clients_17", "qa_desk_1", "default_thread", "web_session_x"):
        await conv.record_conversation_turn(s, tid, "Q", now=T0)
    assert await s.asearch(conv.NAMESPACE) == []


@pytest.mark.anyio
async def test_empty_question_ignored():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "   ", now=T0)
    assert await s.aget(conv.NAMESPACE, "desk_a") is None


@pytest.mark.anyio
async def test_list_sorted_by_updated_desc():
    s = _store()
    await conv.record_conversation_turn(s, "desk_old", "Old", now=T0)
    await conv.record_conversation_turn(s, "desk_new", "New", now=T0 + timedelta(days=1))
    rows = await conv.list_conversations(s)
    assert [r["id"] for r in rows] == ["desk_new", "desk_old"]
    assert set(rows[0]) == {"id", "title", "created_at", "updated_at"}


@pytest.mark.anyio
async def test_search_returns_semantic_match_first():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "NVDA vs AMD", now=T0)
    await conv.record_conversation_turn(s, "desk_b", "Cohen portfolio", now=T0)
    item = (await s.aget(conv.NAMESPACE, "desk_a")).value
    rows = await conv.list_conversations(s, query=item["text"])
    assert rows[0]["id"] == "desk_a"


@pytest.mark.anyio
async def test_search_drops_low_scores(monkeypatch):
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "NVDA vs AMD", now=T0)
    monkeypatch.setattr(conv, "SEARCH_MIN_SCORE", 1.01)
    assert await conv.list_conversations(s, query="anything") == []


@pytest.mark.anyio
async def test_blank_query_is_plain_list():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "A", now=T0)
    assert [r["id"] for r in await conv.list_conversations(s, query="  ")] == ["desk_a"]


@pytest.mark.anyio
async def test_delete_removes_checkpoints_and_item():
    s = _store()
    saver = InMemorySaver()
    g = StateGraph(MessagesState)
    g.add_node("n", lambda st: {})
    g.add_edge(START, "n")
    app = g.compile(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "desk_a"}}
    await app.ainvoke({"messages": [HumanMessage("hi")]}, cfg)
    await conv.record_conversation_turn(s, "desk_a", "hi", now=T0)
    await conv.delete_conversation(s, saver, "desk_a")
    assert await saver.aget_tuple(cfg) is None
    assert await s.aget(conv.NAMESPACE, "desk_a") is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_conversations_index.py -v`
Expected: FAIL (`No module named app.agent.memory.conversations`).

- [ ] **Step 3: Implement** `app/agent/memory/conversations.py`

```python
"""Research conversation index in the LangGraph store.

One item per Research thread (`desk_*`) in ("conversations",): title (first
question, renamable), timestamps, the last questions, and `text` -- the
field the store embeds, so the history can be searched by meaning.
Messages themselves stay in the checkpointer."""

from __future__ import annotations

from datetime import datetime, timezone

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

NAMESPACE = ("conversations",)
RESEARCH_PREFIX = "desk_"
TITLE_MAX = 60
QUESTION_MAX = 300
MAX_QUESTIONS = 10
SEARCH_MIN_SCORE = 0.25
_LIST_SCAN = 1000


def is_research_thread(thread_id: str) -> bool:
    return isinstance(thread_id, str) and thread_id.startswith(RESEARCH_PREFIX)


def _clean(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _text(title: str, questions: list[str]) -> str:
    return "\n".join([title, *questions])


def _row(key: str, value: dict) -> dict:
    return {"id": key, "title": value["title"], "created_at": value["created_at"], "updated_at": value["updated_at"]}


async def record_conversation_turn(
    store: BaseStore, thread_id: str, question: str, now: datetime | None = None
) -> None:
    if not is_research_thread(thread_id):
        return
    q = _clean(question, QUESTION_MAX)
    if not q:
        return
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    existing = await store.aget(NAMESPACE, thread_id)
    if existing is None:
        value = {"title": _clean(question, TITLE_MAX), "created_at": stamp, "questions": []}
    else:
        value = dict(existing.value)
    value["questions"] = [*value.get("questions", []), q][-MAX_QUESTIONS:]
    value["updated_at"] = stamp
    value["text"] = _text(value["title"], value["questions"])
    await store.aput(NAMESPACE, thread_id, value)


async def list_conversations(store: BaseStore, query: str | None = None, limit: int = 50) -> list[dict]:
    if query and query.strip():
        hits = await store.asearch(NAMESPACE, query=query.strip(), limit=limit)
        return [_row(h.key, h.value) for h in hits if (h.score or 0) >= SEARCH_MIN_SCORE]
    items = await store.asearch(NAMESPACE, limit=_LIST_SCAN)
    items.sort(key=lambda i: i.value.get("updated_at", ""), reverse=True)
    return [_row(i.key, i.value) for i in items[:limit]]


async def rename_conversation(store: BaseStore, thread_id: str, title: str) -> dict | None:
    existing = await store.aget(NAMESPACE, thread_id)
    if existing is None:
        return None
    value = dict(existing.value)
    value["title"] = _clean(title, 80)
    value["text"] = _text(value["title"], value.get("questions", []))
    await store.aput(NAMESPACE, thread_id, value)
    return _row(thread_id, value)


async def delete_conversation(store: BaseStore, checkpointer: BaseCheckpointSaver, thread_id: str) -> None:
    await checkpointer.adelete_thread(thread_id)
    await store.adelete(NAMESPACE, thread_id)
```


- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_conversations_index.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add app/agent/memory/conversations.py tests/unit/test_conversations_index.py
git commit -m "feat(history): Research conversation index in the LangGraph store"
```

---

### Task 3: Index every Research turn from the graph

**Files:**
- Modify: `app/agent/orchestration/graph.py` (`record_multi_agent_question` + node registration)
- Test: `tests/unit/test_record_question_indexing.py` (create)

**Interfaces:**
- Consumes: `record_conversation_turn` (Task 2); `langgraph.config.get_store()`.
- Produces: `record_multi_agent_question(state, config) -> dict` (sync, unchanged behavior, no indexing) and `arecord_multi_agent_question(state, config) -> dict` (async, same return + indexing). Node `record_question` = `RunnableLambda(record_multi_agent_question, afunc=arecord_multi_agent_question)`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from app.agent.memory import conversations as conv
from app.agent.orchestration import graph as graph_mod
from app.agent.orchestration.state import SupervisorState


def _app(store):
    g = StateGraph(SupervisorState)
    g.add_node(
        "record_question",
        RunnableLambda(graph_mod.record_multi_agent_question, afunc=graph_mod.arecord_multi_agent_question),
    )
    g.add_edge(START, "record_question")
    g.add_edge("record_question", END)
    return g.compile(checkpointer=InMemorySaver(), store=store)


def _store():
    return InMemoryStore(index={"dims": 32, "embed": DeterministicFakeEmbedding(size=32), "fields": ["text"]})


@pytest.mark.anyio
async def test_research_turn_is_indexed():
    store = _store()
    out = await _app(store).ainvoke({"question": "NVDA news?"}, {"configurable": {"thread_id": "desk_t1"}})
    assert out["messages"][-1].content == "NVDA news?"
    assert (await store.aget(conv.NAMESPACE, "desk_t1")).value["title"] == "NVDA news?"


@pytest.mark.anyio
async def test_client_turn_is_not_indexed():
    store = _store()
    await _app(store).ainvoke({"question": "Hi"}, {"configurable": {"thread_id": "clients_3"}})
    assert await store.asearch(conv.NAMESPACE) == []


@pytest.mark.anyio
async def test_index_failure_never_fails_the_turn(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(graph_mod, "record_conversation_turn", boom)
    out = await _app(_store()).ainvoke({"question": "Q"}, {"configurable": {"thread_id": "desk_t2"}})
    assert out["messages"][-1].content == "Q"


@pytest.mark.anyio
async def test_no_store_is_fine():
    g = StateGraph(SupervisorState)
    g.add_node("record_question", RunnableLambda(graph_mod.record_multi_agent_question, afunc=graph_mod.arecord_multi_agent_question))
    g.add_edge(START, "record_question")
    g.add_edge("record_question", END)
    out = await g.compile(checkpointer=InMemorySaver()).ainvoke({"question": "Q"}, {"configurable": {"thread_id": "desk_t3"}})
    assert out["messages"][-1].content == "Q"


def test_graph_registers_async_record_question():
    node = graph_mod._build_workflow().nodes["record_question"].runnable
    assert getattr(node, "afunc", None) is not None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_record_question_indexing.py -v`
Expected: FAIL (`arecord_multi_agent_question` missing).

- [ ] **Step 3: Implement** in `app/agent/orchestration/graph.py`

```python
import logging

from langgraph.config import get_store

from app.agent.memory.conversations import record_conversation_turn

logger = logging.getLogger(__name__)


async def arecord_multi_agent_question(state: SupervisorState, config: RunnableConfig) -> dict:
    """Async twin used by every real transport: same update, plus the
    Research history index (desk_* threads only). Never fails the turn."""
    update = record_multi_agent_question(state, config)
    question = state.get("question")
    thread_id = (config.get("configurable") or {}).get("thread_id")
    if question and thread_id:
        try:
            store = get_store()
            if store is not None:
                await record_conversation_turn(store, thread_id, question)
        except Exception:
            logger.exception("conversation index update failed (thread=%s)", thread_id)
    return update
```

In `_build_workflow()` replace `workflow.add_node("record_question", record_multi_agent_question)` with:

```python
    workflow.add_node(
        "record_question",
        RunnableLambda(record_multi_agent_question, afunc=arecord_multi_agent_question),
    )
```

If `get_store()` raises outside a store-enabled run (rather than returning None), the `try` already covers it; keep the test `test_no_store_is_fine` green either way.

- [ ] **Step 4: Run to verify they pass + graph regressions**

Run: `uv run pytest tests/unit/test_record_question_indexing.py tests/unit/test_multi_agent_graph_structure.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/orchestration/graph.py tests/unit/test_record_question_indexing.py
git commit -m "feat(history): record_question indexes Research turns in the store"
```

---

### Task 4: `/conversations` API

**Files:**
- Create: `app/api/routers/conversations.py`
- Modify: `app/api/server.py` (`app.include_router(conversations_router)`)
- Test: `tests/unit/test_conversations_router.py`

**Interfaces:**
- Consumes: Task 2 functions; `app.state.store`, `app.state.checkpointer` (Task 1).
- Produces: `GET /conversations?q=&limit=` → `list[{id,title,created_at,updated_at}]`; `PATCH /conversations/{thread_id}` body `{"title": str}` → row | 404 | 422; `DELETE /conversations/{thread_id}` → 204 | 400.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.agent.memory import conversations as conv
from app.api.server import app

client = TestClient(app)
T0 = datetime(2026, 10, 14, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _state():
    app.state.store = InMemoryStore(index={"dims": 32, "embed": DeterministicFakeEmbedding(size=32), "fields": ["text"]})
    app.state.checkpointer = InMemorySaver()
    yield


def _seed(tid, q):
    import asyncio

    asyncio.run(conv.record_conversation_turn(app.state.store, tid, q, now=T0))


def test_list():
    _seed("desk_a", "Alpha")
    r = client.get("/conversations")
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == ["desk_a"]


def test_rename_and_404_and_validation():
    _seed("desk_a", "Alpha")
    assert client.patch("/conversations/desk_a", json={"title": "Beta"}).json()["title"] == "Beta"
    assert client.patch("/conversations/desk_zzz", json={"title": "X"}).status_code == 404
    assert client.patch("/conversations/desk_a", json={"title": "   "}).status_code == 422
    assert client.patch("/conversations/desk_a", json={"title": "x" * 81}).status_code == 422


def test_delete():
    _seed("desk_a", "Alpha")
    assert client.delete("/conversations/desk_a").status_code == 204
    assert client.get("/conversations").json() == []
    assert client.delete("/conversations/desk_a").status_code == 204  # idempotent


def test_delete_refuses_non_research_thread():
    assert client.delete("/conversations/clients_17").status_code == 400
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_conversations_router.py -v`
Expected: FAIL (404 on `/conversations`).

- [ ] **Step 3: Implement** `app/api/routers/conversations.py`

```python
"""Research conversation history: list / search / rename / delete.

Deterministic (no LLM). The index lives in the LangGraph store
("conversations",), the messages in the checkpointer; both come from
app.state, set in the server lifespan."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, field_validator

from app.agent.memory.conversations import (
    delete_conversation,
    is_research_thread,
    list_conversations,
    rename_conversation,
)

router = APIRouter()


class RenameRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 1 <= len(v) <= 80:
            raise ValueError("title must be 1-80 characters")
        return v


@router.get("/conversations")
async def get_conversations(request: Request, q: str | None = None, limit: int = 50) -> list[dict]:
    return await list_conversations(request.app.state.store, q, max(1, min(limit, 200)))


@router.patch("/conversations/{thread_id}")
async def patch_conversation(thread_id: str, body: RenameRequest, request: Request) -> dict:
    row = await rename_conversation(request.app.state.store, thread_id, body.title)
    if row is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return row


@router.delete("/conversations/{thread_id}", status_code=204)
async def remove_conversation(thread_id: str, request: Request) -> Response:
    if not is_research_thread(thread_id):
        raise HTTPException(status_code=400, detail="only Research conversations can be deleted")
    await delete_conversation(request.app.state.store, request.app.state.checkpointer, thread_id)
    return Response(status_code=204)
```

`app/api/server.py`: `from app.api.routers.conversations import router as conversations_router` and `app.include_router(conversations_router)`. Add `"PATCH", "DELETE"` to the CORS `allow_methods` list. Check `frontend/vite.config.ts` proxy: add `"/conversations"` to the proxied paths if the proxy is a path list (see `viteProxy.test.ts`; extend that test too).

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_conversations_router.py -v` and `cd frontend && npx vitest run src/viteProxy.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/conversations.py app/api/server.py tests/unit/test_conversations_router.py frontend/vite.config.ts frontend/src/viteProxy.test.ts
git commit -m "feat(history): /conversations list, search, rename, delete"
```

---

### Task 5: Frontend API + ConversationPanel

**Files:**
- Create: `frontend/src/research/conversationsApi.ts`, `frontend/src/research/relativeTime.ts`, `frontend/src/research/ConversationPanel.tsx`
- Test: `frontend/src/research/relativeTime.test.ts`, `frontend/src/research/ConversationPanel.test.tsx`

**Interfaces:**
- Produces:
  - `type Conversation = { id: string; title: string; created_at: string; updated_at: string }`
  - `listConversations(q?: string): Promise<Conversation[]>`, `renameConversation(id: string, title: string): Promise<Conversation>`, `deleteConversation(id: string): Promise<void>`
  - `relativeTime(iso: string, now?: Date): string` → `"just now" | "5m ago" | "2h ago" | "3d ago" | "Oct 1"`
  - `ConversationPanel(props: { activeId: string; refreshKey: number; onSelect(id: string): void; onNew(): void; onDeleted(id: string): void })`

- [ ] **Step 1: Write the failing tests**

`relativeTime.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { relativeTime } from "./relativeTime";

const now = new Date("2026-10-14T12:00:00Z");
describe("relativeTime", () => {
  it.each([
    ["2026-10-14T11:59:40Z", "just now"],
    ["2026-10-14T11:55:00Z", "5m ago"],
    ["2026-10-14T10:00:00Z", "2h ago"],
    ["2026-10-11T12:00:00Z", "3d ago"],
  ])("%s -> %s", (iso, out) => expect(relativeTime(iso, now)).toBe(out));
  it("falls back to a short date after a week", () => {
    expect(relativeTime("2026-10-01T12:00:00Z", now)).toMatch(/Oct/);
  });
});
```

`ConversationPanel.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConversationPanel } from "./ConversationPanel";
import * as api from "./conversationsApi";

vi.mock("./conversationsApi");
const rows = [
  { id: "desk_a", title: "NVDA vs AMD", created_at: "2026-10-14T10:00:00Z", updated_at: "2026-10-14T10:00:00Z" },
  { id: "desk_b", title: "Cohen review", created_at: "2026-10-13T10:00:00Z", updated_at: "2026-10-13T10:00:00Z" },
];

function setup(activeId = "desk_a") {
  const props = { activeId, refreshKey: 0, onSelect: vi.fn(), onNew: vi.fn(), onDeleted: vi.fn() };
  render(<ConversationPanel {...props} />);
  return props;
}

describe("ConversationPanel", () => {
  beforeEach(() => {
    vi.mocked(api.listConversations).mockResolvedValue(rows);
    vi.mocked(api.renameConversation).mockImplementation(async (id, title) => ({ ...rows[0], id, title }));
    vi.mocked(api.deleteConversation).mockResolvedValue();
  });

  it("lists conversations and marks the active one", async () => {
    setup();
    expect(await screen.findByText("NVDA vs AMD")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /NVDA vs AMD/ })).toHaveAttribute("aria-current", "true");
  });

  it("selects and starts new conversations", async () => {
    const p = setup();
    await userEvent.click(await screen.findByRole("button", { name: /Cohen review/ }));
    expect(p.onSelect).toHaveBeenCalledWith("desk_b");
    await userEvent.click(screen.getByRole("button", { name: "+ New conversation" }));
    expect(p.onNew).toHaveBeenCalled();
  });

  it("searches with the typed query", async () => {
    setup();
    await userEvent.type(screen.getByRole("searchbox", { name: "Search conversations" }), "chips");
    await waitFor(() => expect(api.listConversations).toHaveBeenLastCalledWith("chips"));
  });

  it("renames inline", async () => {
    setup();
    await screen.findByText("NVDA vs AMD");
    await userEvent.click(screen.getAllByRole("button", { name: "Rename" })[0]);
    const box = screen.getByRole("textbox", { name: "Conversation title" });
    await userEvent.clear(box);
    await userEvent.type(box, "Chips{Enter}");
    expect(api.renameConversation).toHaveBeenCalledWith("desk_a", "Chips");
  });

  it("deletes after confirmation and reports it", async () => {
    const p = setup();
    await screen.findByText("NVDA vs AMD");
    await userEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    expect(screen.getByText("Delete this conversation? This cannot be undone.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(api.deleteConversation).toHaveBeenCalledWith("desk_a"));
    expect(p.onDeleted).toHaveBeenCalledWith("desk_a");
  });

  it("shows an error with Retry", async () => {
    vi.mocked(api.listConversations).mockRejectedValueOnce(new Error("down"));
    setup();
    expect(await screen.findByText("Couldn't load conversations")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("NVDA vs AMD")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    vi.mocked(api.listConversations).mockResolvedValue([]);
    setup();
    expect(await screen.findByText("No conversations yet")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/research`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

`conversationsApi.ts`:

```ts
import { API_BASE } from "../lib/api";

export type Conversation = { id: string; title: string; created_at: string; updated_at: string };

export async function listConversations(q?: string, base = API_BASE): Promise<Conversation[]> {
  const qs = q && q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
  const res = await fetch(`${base}/conversations${qs}`);
  if (!res.ok) throw new Error(`conversations ${res.status}`);
  return res.json();
}

export async function renameConversation(id: string, title: string, base = API_BASE): Promise<Conversation> {
  const res = await fetch(`${base}/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`rename ${res.status}`);
  return res.json();
}

export async function deleteConversation(id: string, base = API_BASE): Promise<void> {
  const res = await fetch(`${base}/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`delete ${res.status}`);
}
```

`relativeTime.ts`:

```ts
export function relativeTime(iso: string, now: Date = new Date()): string {
  const s = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
```

`ConversationPanel.tsx` — behavior to implement (Tailwind tokens as in `AppLayout`: `border-terminal-border`, `bg-terminal-panel`, `text-terminal-muted`, `text-brand-blue`, active row `bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300`):

```tsx
import { useCallback, useEffect, useState } from "react";
import { deleteConversation, listConversations, renameConversation, type Conversation } from "./conversationsApi";
import { relativeTime } from "./relativeTime";

type Props = {
  activeId: string;
  refreshKey: number;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDeleted: (id: string) => void;
};

export function ConversationPanel({ activeId, refreshKey, onSelect, onNew, onDeleted }: Props) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Conversation[] | null>(null);
  const [error, setError] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const load = useCallback(async (q: string) => {
    try {
      setItems(await listConversations(q));
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => void load(query), query ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, query, refreshKey, attempt]);

  async function commitRename(id: string) {
    const title = draft.trim();
    setEditing(null);
    if (!title) return;
    const row = await renameConversation(id, title);
    setItems((cur) => cur?.map((c) => (c.id === id ? { ...c, title: row.title } : c)) ?? cur);
  }

  async function confirmDelete(id: string) {
    setConfirming(null);
    await deleteConversation(id);
    setItems((cur) => cur?.filter((c) => c.id !== id) ?? cur);
    onDeleted(id);
  }

  return (
    <aside aria-label="Conversations" className="flex w-64 shrink-0 flex-col border-r border-terminal-border bg-terminal-panel">
      <div className="space-y-2 border-b border-terminal-border p-3">
        <button type="button" onClick={onNew} className="w-full rounded-xl border border-terminal-border px-3 py-2 text-xs font-semibold text-terminal-muted hover:border-brand-blue/50 hover:text-brand-blue">
          + New conversation
        </button>
        <input
          type="search"
          aria-label="Search conversations"
          placeholder="Search conversations…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full rounded-lg border border-terminal-border bg-terminal-bg px-2 py-1.5 text-xs"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {error && (
          <div className="p-2 text-xs text-terminal-muted">
            <p>Couldn't load conversations</p>
            <button type="button" onClick={() => setAttempt((n) => n + 1)} className="mt-1 font-semibold text-brand-blue">Retry</button>
          </div>
        )}
        {!error && items?.length === 0 && <p className="p-2 text-xs text-terminal-muted">No conversations yet</p>}
        <ul className="space-y-1">
          {items?.map((c) => (
            <li key={c.id} className="group relative">
              {editing === c.id ? (
                <input
                  aria-label="Conversation title"
                  autoFocus
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void commitRename(c.id);
                    if (e.key === "Escape") setEditing(null);
                  }}
                  onBlur={() => void commitRename(c.id)}
                  className="w-full rounded-lg border border-brand-blue px-2 py-1.5 text-xs"
                />
              ) : (
                <button
                  type="button"
                  aria-current={c.id === activeId ? "true" : undefined}
                  onClick={() => onSelect(c.id)}
                  className={`w-full rounded-lg px-2 py-1.5 text-left text-xs ${c.id === activeId ? "bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300" : "text-terminal-text hover:bg-surface-soft"}`}
                >
                  <span className="block truncate font-medium">{c.title}</span>
                  <span className="block text-[10px] text-terminal-muted">{relativeTime(c.updated_at)}</span>
                </button>
              )}
              {editing !== c.id && (
                <div className="absolute right-1 top-1 hidden gap-1 group-hover:flex group-focus-within:flex">
                  <button type="button" onClick={() => { setDraft(c.title); setEditing(c.id); }} className="rounded px-1 text-[10px] text-terminal-muted hover:text-terminal-text">Rename</button>
                  <button type="button" onClick={() => setConfirming(c.id)} className="rounded px-1 text-[10px] text-terminal-muted hover:text-terminal-warn">Delete</button>
                </div>
              )}
              {confirming === c.id && (
                <div role="alertdialog" className="mt-1 rounded-lg border border-terminal-warn/40 bg-terminal-warn/10 p-2 text-[11px]">
                  <p>Delete this conversation? This cannot be undone.</p>
                  <div className="mt-1 flex gap-2">
                    <button type="button" aria-label="Confirm delete" onClick={() => void confirmDelete(c.id)} className="font-semibold text-terminal-warn">Delete</button>
                    <button type="button" onClick={() => setConfirming(null)} className="text-terminal-muted">Cancel</button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
```

(If `getAllByRole("button", { name: "Delete" })` also matches the confirm button, the `aria-label="Confirm delete"` keeps them distinct — confirm button's accessible name is "Confirm delete".)

- [ ] **Step 4: Run to verify they pass**

Run: `cd frontend && npx vitest run src/research`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/research
git commit -m "feat(history): ConversationPanel with search, rename, delete"
```

---

### Task 6: ResearchPage, URL thread, shell cleanup

**Files:**
- Create: `frontend/src/research/ResearchPage.tsx`, `frontend/src/research/ResearchPage.test.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/App.test.tsx`, `frontend/src/layout/AppLayout.tsx`, `frontend/src/layout/AppLayout.test.tsx`, `frontend/src/desk/DeskView.tsx`, `frontend/src/desk/DeskView.test.tsx`, `frontend/src/voice/useVoiceHistoryRefresh.ts` only if needed

**Interfaces:**
- Consumes: `ConversationPanel` (Task 5), `newThreadId()` from `lib/api`.
- Produces: `DeskView` prop `onTurnFinished?: () => void` (called on AG-UI `onRunFinalized` and after a voice history refresh); `ResearchPage` default route element; `AppLayout` with no props.

- [ ] **Step 1: Write the failing tests**

`ResearchPage.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

vi.mock("../desk/DeskView", () => ({
  DeskView: ({ threadId }: { threadId: string }) => <div data-testid="desk">{threadId}</div>,
}));
vi.mock("./ConversationPanel", () => ({
  ConversationPanel: (p: { onSelect(id: string): void; onNew(): void; onDeleted(id: string): void; activeId: string }) => (
    <div>
      <button onClick={() => p.onSelect("desk_b")}>pick b</button>
      <button onClick={p.onNew}>new</button>
      <button onClick={() => p.onDeleted(p.activeId)}>delete active</button>
      <button onClick={() => p.onDeleted("desk_other")}>delete other</button>
    </div>
  ),
}));

import { ResearchPage } from "./ResearchPage";

function Loc() {
  return <div data-testid="loc">{useLocation().search}</div>;
}
function renderAt(url: string) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes><Route path="/research" element={<><ResearchPage /><Loc /></>} /></Routes>
    </MemoryRouter>,
  );
}

describe("ResearchPage", () => {
  it("opens the conversation named in ?c", () => {
    renderAt("/research?c=desk_a");
    expect(screen.getByTestId("desk")).toHaveTextContent("desk_a");
  });

  it("creates a desk_ id when ?c is missing and writes it to the URL", () => {
    renderAt("/research");
    const id = screen.getByTestId("desk").textContent!;
    expect(id).toMatch(/^desk_/);
    expect(screen.getByTestId("loc")).toHaveTextContent(`?c=${id}`);
  });

  it("ignores a non-desk c param", () => {
    renderAt("/research?c=clients_17");
    expect(screen.getByTestId("desk").textContent).toMatch(/^desk_/);
    expect(screen.getByTestId("desk").textContent).not.toBe("clients_17");
  });

  it("switches and starts new conversations", async () => {
    renderAt("/research?c=desk_a");
    await userEvent.click(screen.getByText("pick b"));
    expect(screen.getByTestId("desk")).toHaveTextContent("desk_b");
    await userEvent.click(screen.getByText("new"));
    expect(screen.getByTestId("desk").textContent).not.toBe("desk_b");
  });

  it("deleting the active conversation opens a new one; deleting another keeps it", async () => {
    renderAt("/research?c=desk_a");
    await userEvent.click(screen.getByText("delete other"));
    expect(screen.getByTestId("desk")).toHaveTextContent("desk_a");
    await userEvent.click(screen.getByText("delete active"));
    expect(screen.getByTestId("desk").textContent).not.toBe("desk_a");
  });
});
```

`AppLayout.test.tsx`: replace the "shows the session id and calls onNewSession…" test with:

```tsx
  it("no longer shows a session box or a New session button", () => {
    renderAt("/data");
    expect(screen.queryByRole("button", { name: /new session/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Session")).not.toBeInTheDocument();
  });
```

and change every `<AppLayout threadId="t1" onNewSession={...} />` in that file to `<AppLayout />`.

`App.test.tsx`: in the `/research` route assertions (or a new test), assert the desk-view text matches `/^desk_/` (the `vi.mock("./desk/DeskView")` stays; ResearchPage renders the mocked DeskView; mock `./research/ConversationPanel` to a stub `() => null` at the top).

`DeskView.test.tsx`: add a test that `onTurnFinished` is called when the agent's subscriber fires `onRunFinalized` — extend the existing `useAgent` mock to return an `agent` with `subscribe: vi.fn((s) => { capturedSubscriber = s; return { unsubscribe: vi.fn() }; })`, render `<DeskView threadId="desk_x" onTurnFinished={spy} />`, call `capturedSubscriber.onRunFinalized({})`, expect `spy` called once. Follow the file's existing mock style (read `DeskView.test.tsx` lines 1–120 first).

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/research src/App.test.tsx src/layout src/desk/DeskView.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

`ResearchPage.tsx`:

```tsx
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DeskView } from "../desk/DeskView";
import { newThreadId } from "../lib/api";
import { ConversationPanel } from "./ConversationPanel";

const newResearchId = () => `desk_${newThreadId()}`;

export function ResearchPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("c");
  const fallback = useMemo(newResearchId, [requested]);
  const threadId = requested && requested.startsWith("desk_") ? requested : fallback;
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (requested !== threadId) setParams({ c: threadId }, { replace: true });
  }, [requested, threadId, setParams]);

  const open = useCallback((id: string) => setParams({ c: id }), [setParams]);
  const startNew = useCallback(() => open(newResearchId()), [open]);
  const onDeleted = useCallback((id: string) => { if (id === threadId) startNew(); }, [threadId, startNew]);
  const onTurnFinished = useCallback(() => setRefreshKey((n) => n + 1), []);

  return (
    <div className="flex min-h-0 flex-1">
      <ConversationPanel activeId={threadId} refreshKey={refreshKey} onSelect={open} onNew={startNew} onDeleted={onDeleted} />
      <DeskView key={threadId} threadId={threadId} voiceEnabled onTurnFinished={onTurnFinished} />
    </div>
  );
}
```

`App.tsx`: remove the `threadId` state, `onNewSession`, `newThreadId` and `DeskView` imports; route `/research` → `<ResearchPage />`; `<AppLayout />` with no props.

`AppLayout.tsx`: remove `AppLayoutProps`, the props, the "Session" box and the "+ New session" button (lines ~165–172); keep "Profile settings".

`DeskView.tsx`: add `onTurnFinished?: () => void` to `DeskViewProps`, pass it to `DeskBody`, and inside `DeskBody`:

```tsx
  const { agent: chatAgent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
  useEffect(() => {
    if (!onTurnFinished || !chatAgent?.subscribe) return;
    const sub = chatAgent.subscribe({ onRunFinalized: () => { onTurnFinished(); } });
    return () => sub.unsubscribe();
  }, [chatAgent, onTurnFinished]);
```

and in the `setMessages` callback used by `useVoiceHistoryRefresh`, call `onTurnFinished?.()` after `agent.setMessages(...)` so voice turns refresh the list too. Update the stale comment "Remounted per thread by App (key={threadId}), so New session starts clean." → "Remounted per thread by ResearchPage (key={threadId})."

- [ ] **Step 4: Run to verify they pass + full frontend suite + typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/research frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/layout/AppLayout.tsx frontend/src/layout/AppLayout.test.tsx frontend/src/desk/DeskView.tsx frontend/src/desk/DeskView.test.tsx
git commit -m "feat(history): Research page with conversation panel; thread in ?c=, session box removed"
```

---

### Task 7: Docs, full suites, live check

**Files:**
- Modify: `CLAUDE.md`, `docs/TOOLS.md`

- [ ] **Step 1: Docs**

`CLAUDE.md`:
- "Optional with defaults": add `STORE_BACKEND` (sqlite when the checkpointer is sqlite, else memory) and `STORE_DB_PATH` (data/store.db).
- API routers list: `conversations.py` — `GET /conversations?q=` (semantic search over the store index), `PATCH`/`DELETE /conversations/{thread_id}` (delete = `adelete_thread` + store item; `desk_*` only).
- Multi-agent section: `record_question` is async and indexes `desk_*` turns in the store `("conversations",)`.
- Console line: `/research?c=<thread_id>`; Research has a conversation panel.

`docs/TOOLS.md`: in the `save_memory` / `recall_memory` / `list_memories` entries, state the store is now durable locally (`AsyncSqliteStore`, `data/store.db`) and `save_memory` writes with `index=False`.

- [ ] **Step 2: Full suites**

Run: `uv run pytest tests/ -q > <workspace>/pytest.txt 2>&1; tail -5 <workspace>/pytest.txt` and `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all green (≥ 694 + new backend, ≥ 318 + new frontend).

- [ ] **Step 3: Commit docs**

```bash
git add CLAUDE.md docs/TOOLS.md
git commit -m "docs: durable store, conversations API, Research history"
```

- [ ] **Step 4: Live check** (restart backend without `--reload`; Vite already on :5173)

Using `desk_` threads created in the browser (they are new Research conversations, not real client threads):
1. Ask "Compare NVDA and AMD" → appears in the panel with that title.
2. "+ New conversation", ask "What is in Cohen's portfolio?" → second entry on top.
3. Reload → same conversation still open (`?c=` kept), messages shown.
4. Click the first one → its messages and cards come back.
5. Search "semiconductors" → NVDA/AMD conversation found; search "zzzz qqq" → empty or near-empty. If good matches fall below `SEARCH_MIN_SCORE=0.25` or junk passes, adjust the constant from the observed scores (log them once), ledger the ruling, re-run Task 2 tests.
6. Rename, then ask another question → title kept.
7. Delete the open one → a new empty conversation opens; entry gone.
8. Restart backend → list still there; `save_memory` fact (approve HITL) still recalled.
Delete the live-check conversations from the panel afterwards.
