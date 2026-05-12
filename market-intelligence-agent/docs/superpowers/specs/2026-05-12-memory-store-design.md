# Memory Store — Design Spec

**Subsystem #4 of the agentic-expansion roadmap.** Adds cross-thread "user facts" memory using LangGraph's native `Store` API, so the agent can remember durable facts the user has stated (email, investment horizon, exclusion lists, etc.) across sessions and threads.

## Why

Today the agent only has *per-thread* memory via the `AsyncSqliteSaver` checkpointer. Within a thread it remembers what was said; across threads it forgets everything. Users currently have to re-type their email every time they ask the agent to send a report, re-state their preferences in every conversation. Memory store closes that gap.

## Decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Scope | Explicit user facts only (LLM saves only when the user has directly stated a durable fact). Agent-derived observations and session summaries deferred. |
| 2 | Access pattern | Tool-only via `InjectedStore` — the LangGraph-documented canonical pattern. No automatic injection node. |
| 3 | Tool surface | Three tools: `save_memory(key, value)`, `recall_memory(key)`, `list_memories()`. |
| 4 | HITL | `save_memory` is gated (side-effect that survives sessions). `recall_memory` and `list_memories` are read-only, bypass `approval_node`. |
| 5 | Backend | `langgraph.store.memory.InMemoryStore` for v1. Volatile (lost on server restart). `AsyncSqliteStore` upgrade deferred to a follow-up subsystem when durability matters. |
| 6 | Namespace | Single bucket `("user_facts",)`. Single-user portfolio agent — multi-user namespacing (`("user_facts", user_id)`) deferred. |

## Architecture

LangGraph's `Store` is a *first-class compile-time argument* to `workflow.compile(...)`, distinct from the checkpointer. The graph holds a reference to it; `ToolNode` injects it into any tool annotated with `Annotated[Any, InjectedStore()]`. The LLM never sees the store object — it only sees the tool schema (`key: str`, `value: str`) just like every other tool.

The graph topology is unchanged. `approval_node`'s existing HITL semantics extend to `save_memory` for free, because `READ_ONLY_TOOLS` is the single source of truth for "what bypasses the interrupt".

The lifespan integration mirrors what we built for the checkpointer in `fix/async-checkpointer`: `app.state.agent_app` is built inside the FastAPI lifespan with both `checkpointer` and `store` passed in.

## Components

| File | Change |
|---|---|
| `app/agent/tools/memory.py` | **NEW.** Three native LangChain `@tool` functions: `save_memory_tool`, `recall_memory_tool`, `list_memories_tool`. All async, all use `Annotated[Any, InjectedStore()]`. |
| `app/agent/memory/store.py` | **NEW.** Factory `create_store()` returning `InMemoryStore()`. Wrapped so the FastAPI lifespan can swap backends (e.g. to `AsyncSqliteStore` later) without touching `server.py`. |
| `app/agent/graph.py` | Update `build_agent_app(checkpointer)` to `build_agent_app(checkpointer, store)` and pass `store` through to `workflow.compile(...)`. |
| `app/api/server.py` | In lifespan, instantiate `store = create_store()` and pass to `build_agent_app(checkpointer, store)`. |
| `app/agent/tools/__init__.py` | Import the 3 new tool symbols, append to `TOOLS`, add `recall_memory` and `list_memories` to `READ_ONLY_TOOLS` (NOT `save_memory`). |
| `app/agent/prompts/system.py` | Add a "🧠 MEMORY GUIDELINES" section explaining when to save / recall / list, with naming conventions for keys. |
| `docs/TOOLS.md`, `CLAUDE.md`, `README.md` | Documentation sync per the project rule. |

### Tool implementations

```python
# app/agent/tools/memory.py
from typing import Annotated, Any
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedStore

USER_FACTS_NS = ("user_facts",)


@tool
async def save_memory(
    key: str,
    value: str,
    store: Annotated[Any, InjectedStore()],
) -> str:
    """Persist a durable user fact across sessions. Use short snake_case keys
    (e.g. 'email', 'investment_horizon'). Call only when the user has stated
    a fact about themselves they would want remembered next time."""
    await store.aput(USER_FACTS_NS, key, {"value": value})
    return f"Saved {key}={value}"


@tool
async def recall_memory(
    key: str,
    store: Annotated[Any, InjectedStore()],
) -> str:
    """Look up a previously saved user fact by key."""
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

### Store factory

```python
# app/agent/memory/store.py
"""Store factory — produces the BaseStore passed to workflow.compile(store=...).

InMemoryStore is volatile (lost on server restart). Migrating to AsyncSqliteStore
later means changing this single function; nothing in graph.py or server.py
needs to know about the backend.
"""
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore


def create_store() -> BaseStore:
    return InMemoryStore()
```

### Lifespan integration

```python
# app/api/server.py (excerpt)
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with create_checkpointer() as checkpointer:
        store = create_store()
        app.state.agent_app = build_agent_app(checkpointer, store)
        yield
```

### Updated `READ_ONLY_TOOLS`

Adds `recall_memory` and `list_memories` (not `save_memory`):

```python
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
```

Final tool count: **14** (was 11). Read-only: **11** (was 9). Gated: **3** — `send_email`, `write_file`, `save_memory`.

## Data flow — SAVE (HITL-gated)

```
User: "By the way, my email is yaniv@example.com — remember that."
  → rag → grader → generate
  → tool_call: save_memory(key="email", value="yaniv@example.com")
  → approval_node sees save_memory ∉ READ_ONLY_TOOLS → interrupt()
  → /stream emits `event: interrupted` with the approval payload
  → user clicks Approve in Streamlit
  → /approve POST → graph resumes
  → ToolNode invokes save_memory; InjectedStore passes the lifespan-owned store
  → store.aput(("user_facts",), "email", {"value": "yaniv@example.com"})
  → generate produces final answer: "Got it — I'll remember your email."
```

## Data flow — RECALL (no HITL, fast)

```
User: "Send a summary of NVDA's week to my usual email."
  → rag → grader → generate
  → parallel tool_calls:
      1. recall_memory(key="email")        [RO — bypasses approval]
      2. yfinance_get_price_history("NVDA", "1w")  [RO — bypasses approval]
  → ToolNode runs both: store.aget(...) returns "yaniv@example.com"
  → generate emits tool_call: send_email(to="yaniv@example.com", ...)
  → approval_node sees send_email ∉ READ_ONLY_TOOLS → interrupt
  → user approves → email sent
```

The user never types their email again after the first save. Every action that *uses* the email is still HITL-gated because `send_email` itself is still gated — memory access doesn't bypass the existing safety story; it just removes friction.

## Error handling

- **`recall_memory(unknown_key)`**: returns the string `"No memory for key 'foo'"`. The LLM treats this as "fact not stored, ask the user" via the existing `ERROR_RECOVERY_PROMPT`. No exception.
- **`save_memory` collision**: `store.aput(namespace, key, value)` is last-write-wins. The LLM's natural behavior is to overwrite when the user states a fresh value. No code needed.
- **`InMemoryStore` server restart**: memory is empty. Existing graph behavior is unaffected — the agent will discover (via `list_memories` or a failed `recall_memory`) that it doesn't know the user's preferences yet and ask. Documented in the system prompt.
- **No new HITL failure modes**: `save_memory` cancellation routes through the existing atomic-batch reject path — same as any other gated tool today.

## Documentation deliverables

Per the project rule in `CLAUDE.md`, every tool addition must update `docs/TOOLS.md` with a *what* and *why* entry. The three new rows:

| Tool | Why we have it |
|---|---|
| `save_memory` | Cross-thread durability for facts the user has explicitly stated. Without it, the user re-types their email, preferences, and exclusions every session. |
| `recall_memory` | The matching read side. Lets the agent look up a previously-saved fact before a tool call that needs it (e.g. fetch the user's email before composing a `send_email`). |
| `list_memories` | Discovery. Lets the agent enumerate everything it knows about the user at the start of a complex query — avoids guessing key names. |

Plus tools-table refresh in `CLAUDE.md`; README mention of the cross-thread memory capability.

## System prompt addition

A new "🧠 MEMORY GUIDELINES" section after the BROWSER GUIDELINES:

- Save only durable facts the user has stated about themselves or their preferences. Don't save transient context, opinions, or one-off questions.
- Use short snake_case keys: `email`, `investment_horizon`, `excluded_assets`, `default_recipient`. Avoid long keys, spaces, or punctuation.
- Before sending an email or proposing an action that needs user-specific data, check `recall_memory` first. Ask only if it returns "No memory for…".
- Call `list_memories` at the start of complex tasks to know what's already on file.
- Memory is volatile in this release — if the server restarts, the agent starts fresh. Acknowledge this when the user expects continuity that doesn't exist.
