# Memory Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add cross-thread "user facts" memory via LangGraph's native `Store` API, exposing 3 native LangChain tools (`save_memory` gated, `recall_memory` + `list_memories` read-only) backed by `InMemoryStore` for v1.

**Architecture:** Add a `store` factory (`InMemoryStore` for v1) wired into the existing FastAPI lifespan alongside the checkpointer; pass it to `workflow.compile(store=...)`; tools access it via `InjectedStore`. The graph topology is unchanged; `approval_node` extends to `save_memory` automatically through the existing `READ_ONLY_TOOLS` allowlist.

**Tech Stack:** Python 3.12, `langgraph` (already installed — `langgraph.store.memory.InMemoryStore`, `langgraph.prebuilt.InjectedStore`), `langchain-core`. No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-05-12-memory-store-design.md`

**User preferences carried in:**
- Tests are deferred. Each task ends with the **regression gate** (`uv run pytest tests/ -v`) which must keep the current count of **18 passed, 1 failed** (`test_health_returns_ok` is the pre-existing fail and is unrelated). No new tests are added.
- Prompts and user-facing strings in English.
- Atomic-batch HITL semantics preserved (no changes to `approval_node`).
- Every tool added to `TOOLS` gets an entry in `docs/TOOLS.md` (project rule in `CLAUDE.md`).

**File structure (target):**

```
market-intelligence-agent/
├── app/
│   ├── agent/
│   │   ├── memory/
│   │   │   └── store.py             # CREATE — create_store() factory returning InMemoryStore
│   │   ├── tools/
│   │   │   ├── __init__.py          # MODIFY — wire 3 new tools, refresh READ_ONLY_TOOLS
│   │   │   └── memory.py            # CREATE — save_memory / recall_memory / list_memories @tool funcs
│   │   ├── graph.py                 # MODIFY — build_agent_app accepts and passes `store`
│   │   └── prompts/system.py        # MODIFY — MEMORY GUIDELINES section + roster entries
│   └── api/server.py                # MODIFY — lifespan instantiates store and passes to build_agent_app
├── docs/TOOLS.md                    # MODIFY — append 3 entries
├── CLAUDE.md                        # MODIFY — refresh tools table
└── README.md                        # MODIFY — mention cross-thread memory capability
```

**Tool-name decisions:** all three are native LangChain `@tool`-decorated functions (no MCP). Names exposed to the LLM:

| Name | Read-only? | What it does |
|---|---|---|
| `save_memory` | **no — gated** | `store.aput(("user_facts",), key, {"value": value})` |
| `recall_memory` | yes | `store.aget(("user_facts",), key)` |
| `list_memories` | yes | `store.asearch(("user_facts",))` |

Final tool count: **14** (was 11). `READ_ONLY_TOOLS` size: **11** (was 9). Gated/side-effect: **3** — `send_email`, `write_file`, `save_memory`.

---

## Task 1: Create the store factory

**Files:**
- Create: `market-intelligence-agent/app/agent/memory/store.py`

- [ ] **Step 1: Create `store.py`**

Create `market-intelligence-agent/app/agent/memory/store.py` with exactly:

```python
"""Store factory — produces the BaseStore passed to workflow.compile(store=...).

InMemoryStore is volatile (lost on server restart). Migrating to AsyncSqliteStore
later means changing this single function; nothing in graph.py or server.py needs
to know about the backend.
"""

from __future__ import annotations

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore


def create_store() -> BaseStore:
    """Return the long-term memory store used for cross-thread user facts."""
    return InMemoryStore()
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. Nothing imports the new module yet, so pytest is unaffected.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/memory/store.py
git commit -m "feat(memory-store): add create_store() factory returning InMemoryStore"
```

---

## Task 2: Update `graph.py` to accept and pass `store`

**Files:**
- Modify: `market-intelligence-agent/app/agent/graph.py`

The current `build_agent_app(checkpointer)` factory needs an optional `store` parameter. Default `None` keeps existing callers (`tests/unit/test_hitl_interrupt.py`) working — `workflow.compile(store=None)` is valid and just means no store is wired.

- [ ] **Step 1: Add the BaseStore import**

In `market-intelligence-agent/app/agent/graph.py`, locate the import that begins `from langgraph.checkpoint.base import BaseCheckpointSaver`. Update the langgraph imports block to:

```python
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore
from langgraph.types import interrupt
```

- [ ] **Step 2: Update the `build_agent_app` signature and body**

Locate the existing `build_agent_app` function near the bottom of the file:

```python
def build_agent_app(checkpointer: BaseCheckpointSaver):
    """Compile the workflow with the supplied checkpointer.

    Compilation is deferred from module load so the FastAPI lifespan can open an
    `AsyncSqliteSaver` (which requires a running event loop) and pass it in.
    Tests can pass an `InMemorySaver` for isolation.
    """
    return workflow.compile(checkpointer=checkpointer)
```

Replace it with:

```python
def build_agent_app(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
):
    """Compile the workflow with the supplied checkpointer and optional store.

    Compilation is deferred from module load so the FastAPI lifespan can open an
    `AsyncSqliteSaver` (which requires a running event loop) and pass it in.
    The `store` is the cross-thread long-term memory (LangGraph's BaseStore API).
    Tests that only inspect graph structure can omit the store.
    """
    return workflow.compile(checkpointer=checkpointer, store=store)
```

- [ ] **Step 3: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. The structural tests in `test_hitl_interrupt.py` call `build_agent_app(InMemorySaver())` without a `store` — the new default `store=None` keeps them green.

- [ ] **Step 4: Commit**

```bash
git add market-intelligence-agent/app/agent/graph.py
git commit -m "feat(memory-store): build_agent_app accepts optional store"
```

---

## Task 3: Wire the store into the FastAPI lifespan

**Files:**
- Modify: `market-intelligence-agent/app/api/server.py`

- [ ] **Step 1: Update `server.py` to instantiate and pass the store**

Open `market-intelligence-agent/app/api/server.py`. Replace its entire contents with:

```python
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import FastAPI

from app.agent.graph import build_agent_app
from app.agent.memory.checkpointer import create_checkpointer
from app.agent.memory.store import create_store
from app.api.routers.approve import router as approve_router
from app.api.routers.health import router as health_router
from app.api.routers.stream import router as stream_router
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.LOG_LEVEL)


def _get_version() -> str:
    try:
        return _pkg_version("market-intelligence-agent")
    except PackageNotFoundError:
        return "0.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with create_checkpointer() as checkpointer:
        store = create_store()
        app.state.agent_app = build_agent_app(checkpointer, store)
        yield


app = FastAPI(
    title="Market Intelligence Agent API", version=_get_version(), lifespan=lifespan
)
app.include_router(health_router)
app.include_router(approve_router)
app.include_router(stream_router)
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. The unit tests in `tests/unit/test_stream.py` mock `agent_app` via `app.state.agent_app = fake`, so they continue to override whatever the lifespan would have produced.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/api/server.py
git commit -m "feat(memory-store): wire InMemoryStore into FastAPI lifespan"
```

---

## Task 4: Create the three memory tools

**Files:**
- Create: `market-intelligence-agent/app/agent/tools/memory.py`

- [ ] **Step 1: Create `memory.py`**

Create `market-intelligence-agent/app/agent/tools/memory.py` with exactly:

```python
"""Long-term user-facts memory — three native LangChain tools backed by the
LangGraph `BaseStore` injected at graph compile time.

`save_memory` is a side-effect (gated by approval_node). `recall_memory` and
`list_memories` are read-only and slot into READ_ONLY_TOOLS. All three are
async and operate on the single namespace `("user_facts",)`. The single-bucket
choice fits the single-user portfolio agent; multi-tenant namespacing is a
future-subsystem concern.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedStore

logger = logging.getLogger(__name__)

USER_FACTS_NS = ("user_facts",)


@tool
async def save_memory(
    key: str,
    value: str,
    store: Annotated[Any, InjectedStore()],
) -> str:
    """Persist a durable user fact across sessions. Use short snake_case keys
    (e.g. 'email', 'investment_horizon'). Call only when the user has stated a
    fact about themselves they would want remembered next time."""
    await store.aput(USER_FACTS_NS, key, {"value": value})
    logger.info("save_memory: %s=%s", key, value)
    return f"Saved {key}={value}"


@tool
async def recall_memory(
    key: str,
    store: Annotated[Any, InjectedStore()],
) -> str:
    """Look up a previously-saved user fact by key."""
    item = await store.aget(USER_FACTS_NS, key)
    if item is None:
        return f"No memory for key {key!r}"
    return str(item.value.get("value", ""))


@tool
async def list_memories(store: Annotated[Any, InjectedStore()]) -> list[str]:
    """List every user fact in memory as 'key = value' strings."""
    items = await store.asearch(USER_FACTS_NS)
    return [f"{i.key} = {i.value.get('value', '')}" for i in items]


save_memory_tool = save_memory
recall_memory_tool = recall_memory
list_memories_tool = list_memories
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. Nothing imports the new module yet, so pytest is unaffected.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/memory.py
git commit -m "feat(memory-store): add save_memory, recall_memory, list_memories tools"
```

---

## Task 5: Wire memory tools into `TOOLS` and `READ_ONLY_TOOLS`

**Files:**
- Modify: `market-intelligence-agent/app/agent/tools/__init__.py`

- [ ] **Step 1: Replace `__init__.py`**

Replace the entire contents of `market-intelligence-agent/app/agent/tools/__init__.py` with:

```python
from app.agent.tools.emails import send_email_tool
from app.agent.tools.memory import (
    save_memory_tool,
    recall_memory_tool,
    list_memories_tool,
)
from app.agent.tools.mcp_clients.mcp_client import crm_tool
from app.agent.tools.mcp_clients.yfinance_client import (
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
)
from app.agent.tools.mcp_clients.filesystem_client import (
    fs_read_file_tool,
    fs_list_dir_tool,
    fs_write_file_tool,
)
from app.agent.tools.mcp_clients.browser_client import (
    browser_navigate_tool,
    browser_snapshot_tool,
    browser_screenshot_tool,
)

TOOLS = [
    send_email_tool,
    crm_tool,
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
    fs_read_file_tool,
    fs_list_dir_tool,
    fs_write_file_tool,
    browser_navigate_tool,
    browser_snapshot_tool,
    browser_screenshot_tool,
    save_memory_tool,
    recall_memory_tool,
    list_memories_tool,
]

READ_ONLY_TOOLS: set[str] = {
    "read_query",
    "yfinance_get_ticker_info",
    "yfinance_get_price_history",
    "yfinance_get_ticker_news",
    "read_text_file",
    "list_directory",
    "browser_navigate",
    "browser_snapshot",
    "browser_take_screenshot",
    "recall_memory",
    "list_memories",
}

__all__ = [
    "TOOLS",
    "READ_ONLY_TOOLS",
    "send_email_tool",
    "crm_tool",
    "yf_quote_tool",
    "yf_history_tool",
    "yf_news_tool",
    "fs_read_file_tool",
    "fs_list_dir_tool",
    "fs_write_file_tool",
    "browser_navigate_tool",
    "browser_snapshot_tool",
    "browser_screenshot_tool",
    "save_memory_tool",
    "recall_memory_tool",
    "list_memories_tool",
]
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. The new tools are native (no MCP subprocess), so this only adds three Python imports — pytest is unaffected. The `test_stream.py` tests still pass because they mock `agent_app` via `app.state.agent_app`.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/__init__.py
git commit -m "feat(memory-store): expose 3 memory tools, extend READ_ONLY_TOOLS"
```

---

## Task 6: Update the system prompt for memory awareness

**Files:**
- Modify: `market-intelligence-agent/app/agent/prompts/system.py`

- [ ] **Step 1: Update the tool roster in `SYSTEM_PROMPT`**

Open `market-intelligence-agent/app/agent/prompts/system.py`. Locate the "Browser (read-only, headless Chromium via @playwright/mcp):" subsection (added by subsystem #3, with `browser_take_screenshot` numbered `10`). After the `browser_take_screenshot` entry and **before** the "Side effects (require human approval):" subsection, insert this new subsection:

```
Memory (gated save, read-only recall/list):
11. `recall_memory` — look up a previously-saved user fact by `key: str`. Returns the value, or "No memory for…" if nothing was saved under that key.
12. `list_memories` — return every user fact in memory as a list of `"key = value"` strings. Use at the start of complex queries to know what's already on file.
13. `save_memory` — persist a durable user fact (args: `key: str`, `value: str`). Side-effect — requires human approval. Use short snake_case keys: `email`, `investment_horizon`, `excluded_assets`.
```

Then renumber the existing "Side effects" entry that came after — change `send_email` from `11` to `14`.

- [ ] **Step 2: Add the 🧠 MEMORY GUIDELINES section**

In the same file, locate the "🌐 BROWSER GUIDELINES" section. After its last bullet, append:

```
🧠 MEMORY GUIDELINES
- Save only durable facts the user has stated about themselves or their preferences. Don't save transient context, opinions, or one-off questions.
- Use short snake_case keys: `email`, `investment_horizon`, `excluded_assets`, `default_recipient`. Avoid long keys, spaces, or punctuation.
- Before sending an email or proposing an action that needs user-specific data, check `recall_memory` first. Ask the user only if it returns "No memory for…".
- Call `list_memories` at the start of complex tasks to know what's already on file.
- Memory is volatile in this release — if the server restarts, the agent starts fresh. Acknowledge this when the user expects continuity that doesn't exist.
```

- [ ] **Step 3: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. System prompt is a string constant; no test asserts its content.

- [ ] **Step 4: Commit**

```bash
git add market-intelligence-agent/app/agent/prompts/system.py
git commit -m "feat(memory-store): system prompt — memory tools + 🧠 MEMORY GUIDELINES"
```

---

## Task 7: Update `docs/TOOLS.md`, `CLAUDE.md`, and `README.md`

**Files:**
- Modify: `market-intelligence-agent/docs/TOOLS.md`
- Modify: `market-intelligence-agent/CLAUDE.md`
- Modify: `market-intelligence-agent/README.md`

- [ ] **Step 1: Append 3 rows to the summary table in `docs/TOOLS.md`**

Open `market-intelligence-agent/docs/TOOLS.md`. Locate the summary table — it currently ends with row 11 (`browser_take_screenshot`). After that row, append:

```markdown
| 12 | `recall_memory` | read-only | LangGraph BaseStore (in-memory v1) | key | Look up a previously-saved user fact by key. Returns the value or "No memory for…". | The read side of cross-thread memory. Lets the agent fetch a fact (email, preference) before a tool call that needs it, without re-asking the user. |
| 13 | `list_memories` | read-only | same | (none) | Return every user fact currently in memory as `"key = value"` strings. | Discovery. The agent uses this to know what's on file before guessing keys — same pattern as `list_directory` for files. |
| 14 | `save_memory` | side-effect | same | key, content | Persist a durable user fact under namespace `("user_facts",)`. Gated by HITL approval. | The write side of cross-thread memory. Without it, the user re-types their email and preferences every session. Gated because "the agent learning new facts about you" is a real side-effect users should consent to. |
```

Then update the `READ_ONLY_TOOLS` line directly below the table — locate:

```
`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot"}` — the allowlist consulted by `approval_node` to skip the HITL interrupt for safe reads.
```

Replace it with:

```
`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot", "recall_memory", "list_memories"}` — the allowlist consulted by `approval_node` to skip the HITL interrupt for safe reads.
```

- [ ] **Step 2: Append 3 per-tool detail sub-sections to `docs/TOOLS.md`**

Locate the "## Per-tool details" section. After the existing `### 11. browser_take_screenshot` sub-section, append:

```markdown
### 12. `recall_memory`
- **File:** `app/agent/tools/memory.py`
- **What:** Looks up a user fact in the LangGraph store under namespace `("user_facts",)` by `key`. Returns the stored string, or the literal `"No memory for 'key'"` if absent.
- **Why:** Before composing a `send_email` (or any action that needs user-specific data), the agent calls this to avoid re-asking the user for facts they've already stated. Read-only, no HITL gate — the user has already approved the underlying *save*.

### 13. `list_memories`
- **File:** same as `recall_memory`
- **What:** Returns every fact in the `("user_facts",)` namespace as a flat list `["email = yaniv@…", "investment_horizon = long-term", …]`.
- **Why:** Discovery — same role `list_directory` plays for files. Lets the agent see what's on file before guessing key names, and gives a coherent "what do you know about me" answer.

### 14. `save_memory`
- **File:** same as `recall_memory`
- **What:** Persists `{key: value}` under namespace `("user_facts",)` via `store.aput(...)`. Last-write-wins for collisions. Gated by `approval_node`.
- **Why:** The write side of cross-thread memory. Saves the user from re-stating facts every session. Gated because creating durable knowledge *about* the user is a side-effect users should consent to — same trust posture as `send_email` and `write_file`. The Streamlit modal surfaces the proposed `{key, value}` pair before any disk write.

> **Persistence note:** the v1 backend is `langgraph.store.memory.InMemoryStore` — facts are lost on server restart. Migrating to `AsyncSqliteStore` is a single-function change in `app/agent/memory/store.py`; deferred to a follow-up subsystem when durability matters.
```

- [ ] **Step 3: Update `CLAUDE.md`**

Open `market-intelligence-agent/CLAUDE.md`. Locate the tools table — it currently ends with row `browser_take_screenshot`. After that row, append:

```markdown
| `recall_memory` | `app/agent/tools/memory.py` | read-only | Look up a user fact in LangGraph's BaseStore by key. |
| `list_memories` | same | read-only | Return every user fact in memory as `key = value` strings. |
| `save_memory` | same | side-effect | Persist `{key: value}` under namespace `("user_facts",)`. Gated by `approval_node`. |
```

Then update the `READ_ONLY_TOOLS` paragraph directly below the table. Locate:

```
`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot"}` is the allowlist consulted by `approval_node` to skip the interrupt for safe reads.
```

Replace it with:

```
`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot", "recall_memory", "list_memories"}` is the allowlist consulted by `approval_node` to skip the interrupt for safe reads.
```

- [ ] **Step 4: Update `README.md`**

Open `market-intelligence-agent/README.md`. Locate the paragraph (added by subsystem #3) about the headless browser. After that paragraph, append:

```markdown
The agent also has cross-thread memory for durable user facts via LangGraph's `BaseStore` (`save_memory`, `recall_memory`, `list_memories`). Tell the agent "remember my email is …" once and it can use that fact in future sessions without you re-stating it. The v1 backend is `InMemoryStore` (lost on server restart); persistent `AsyncSqliteStore` is a planned follow-up.
```

- [ ] **Step 5: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**.

- [ ] **Step 6: Commit**

```bash
git add market-intelligence-agent/docs/TOOLS.md \
        market-intelligence-agent/CLAUDE.md \
        market-intelligence-agent/README.md
git commit -m "docs(memory-store): tools registry, CLAUDE.md table, README memory section"
```

---

## Self-review notes

**Spec coverage check:**
- Decision 1 (explicit user facts only) → encoded in system prompt (Task 6) and per-tool details (Task 7). ✓
- Decision 2 (tool-only via `InjectedStore`) → Task 4. ✓
- Decision 3 (three tools: save / recall / list) → Tasks 4, 5. ✓
- Decision 4 (HITL: save gated, recall + list read-only) → Task 5's `READ_ONLY_TOOLS` membership. ✓
- Decision 5 (`InMemoryStore` for v1) → Task 1's factory + Task 3's lifespan. Persistence-note recorded in Task 7's TOOLS.md update. ✓
- Decision 6 (single namespace `("user_facts",)`) → Task 4's `USER_FACTS_NS` constant. ✓
- Architecture (factory + lifespan + InjectedStore + unchanged topology) → Tasks 1, 2, 3, 4, 5. ✓
- Documentation deliverables → Task 7. ✓
- Error handling (return strings, no exceptions; last-write-wins) → Task 4 tool bodies. ✓

**Type / name consistency:**
- Tool names `save_memory`, `recall_memory`, `list_memories` — used identically in `memory.py`, `__init__.py`'s `READ_ONLY_TOOLS`, system prompt, `docs/TOOLS.md`, `CLAUDE.md`. ✓
- Public symbols `save_memory_tool`, `recall_memory_tool`, `list_memories_tool` — used identically in `memory.py` exports and `__init__.py`'s `TOOLS` list + `__all__`. ✓
- `create_store` defined in Task 1, imported in Task 3. ✓
- `build_agent_app(checkpointer, store=None)` — signature consistent between Task 2 (definition) and Task 3 (call site). ✓
- Namespace `("user_facts",)` — consistent across `memory.py` (`USER_FACTS_NS`) and per-tool details prose. ✓

**Placeholder scan:** none. Every step has either complete code or an exact command.
