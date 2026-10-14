# Research conversation history — design

**Date:** 2026-10-14
**Branch:** `feat/conversation-history` (from `feat/desk-interactive-cards`, whose Research page it builds on)
**Status:** approved in conversation, pending spec review

## Problem

The Research page picks a random thread id on every page load (`frontend/src/App.tsx:14`, `newThreadId()`). A reload opens an empty chat; the previous conversation is still in the checkpointer but nothing can find it again. There is no way to keep several Research conversations apart, reopen one, or delete one.

Separately, the LangGraph store behind `save_memory` / `recall_memory` / `list_memories` is an `InMemoryStore` (`app/agent/memory/store.py`): every saved user fact is lost on server restart.

## Goal

On `/research`, the user can:

- see the list of their past conversations (title, last activity), most recent first;
- reopen one — full messages and cards — and keep asking in it;
- start a new conversation;
- search conversations **by meaning** ("semiconductors" finds "Compare NVDA and AMD…");
- rename and delete a conversation.

A page reload reopens the conversation that was open. The long-term store becomes durable, so saved user facts survive restarts.

## Decisions (from the conversation)

| Topic | Decision |
|---|---|
| Scope | Research only. Client pages keep one fixed thread per client (`clients_<id>`). |
| Title | First question, truncated (~60 chars). Renamable. No LLM call. |
| Placement | Collapsible panel inside the Research page, left of the chat. |
| Delete | Hard delete: checkpoints (`adelete_thread`) + index entry. Irreversible, confirmed in the UI. |
| Existing orphan `desk_*` threads | Not imported. Start from zero. |
| Search | Semantic, via the store's built-in vector index. |
| UI language | English (button "+ New conversation", etc.). |
| Prod (AWS) | Out of scope: AgentCore keeps the `memory` store backend. |

## Architecture

Two LangGraph persistence layers, used as documented:

- **Checkpointer** (unchanged, `AsyncSqliteSaver`, `data/checkpoints.db`): messages and state of one thread.
- **Store** (`BaseStore`, now `AsyncSqliteStore`, `data/store.db`): cross-thread data. It now holds two namespaces:
  - `("user_facts",)` — existing `save_memory` facts (unchanged shape);
  - `("conversations",)` — the Research conversation index (new).

### 1. Durable store — `app/agent/memory/store.py`

`create_store()` becomes an async context manager with a backend switch, mirroring `create_checkpointer()`:

- `STORE_BACKEND=sqlite` (default): `AsyncSqliteStore.from_conn_string(STORE_DB_PATH, index=...)`, then `await store.setup()`. `STORE_DB_PATH` defaults to `data/store.db` (separate file from checkpoints).
- `STORE_BACKEND=memory`: `InMemoryStore(index=...)` — tests and the AgentCore image (no `aiosqlite`/`sqlite-vec` dependency added to prod).

Index config (official `SqliteIndexConfig` / `IndexConfig`): `{"dims": 1536, "embed": get_embeddings(), "fields": ["text"]}` — `get_embeddings()` from `app/rag/vectorstore.py` (`text-embedding-3-small`, 1536 dims). Only items that carry a `text` field are embedded; `user_facts` items are written with `index=False` so the memory tools never pay for embeddings.

`server.py` lifespan enters `create_store()` next to `create_checkpointer()`. Tests that need a store use the `memory` backend with `DeterministicFakeEmbedding` (no network).

Verified in a throwaway spike on this machine (Windows): `AsyncSqliteStore` with an `index` loads `sqlite-vec`, `asearch(query=...)`, plain `asearch` listing and `adelete` all work.

### 2. Conversation index — written by the graph

New module `app/agent/memory/conversations.py`:

```python
NAMESPACE = ("conversations",)
RESEARCH_PREFIX = "desk_"

async def record_conversation_turn(store, thread_id: str, question: str, now: datetime) -> None
async def list_conversations(store, query: str | None, limit: int) -> list[dict]
async def rename_conversation(store, thread_id: str, title: str) -> dict | None
async def delete_conversation(store, checkpointer, thread_id: str) -> bool
```

Item value: `{"title": str, "created_at": iso, "updated_at": iso, "questions": [str, ...], "text": str}`.

- `title` = first question, whitespace-collapsed, cut at 60 chars with `…`; set only on creation. A rename sets it and is never overwritten by later turns.
- `questions` keeps the last 10 user questions (each cut at 300 chars).
- `text` = `title` + the kept questions joined — the field the store embeds. Re-embedded on each turn (one small embedding call per Research question).
- `record_conversation_turn` ignores any thread id that does not start with `desk_` (client pages, `/stream`, AgentCore, QA threads).

The graph node `record_question` (`app/agent/orchestration/graph.py`) calls it through the store injected by LangGraph (`Runtime.store` / `get_store()`), so typed Research and Research voice are both indexed with no API-side duplication. The node becomes async with a sync twin for `graph.invoke()` callers (same pattern as `suggest_followups`); the sync twin skips indexing. Any store error is logged and swallowed: indexing must never fail a turn.

### 3. API — `app/api/routers/conversations.py`

| Method | Path | Behavior |
|---|---|---|
| GET | `/conversations?q=&limit=50` | No `q`: all items, sorted by `updated_at` desc. With `q`: semantic `asearch(query=q)`, store relevance order. Returns `[{id, title, created_at, updated_at}]`. |
| PATCH | `/conversations/{thread_id}` | Body `{title}` (1–80 chars, trimmed). 404 if unknown. |
| DELETE | `/conversations/{thread_id}` | `checkpointer.adelete_thread(thread_id)` then `store.adelete(NAMESPACE, thread_id)`. 204. Refuses (400) a thread id not starting with `desk_`. |

The router reads `app.state.store` and `app.state.checkpointer` (set in lifespan). Deterministic, no LLM, same style as `data.py`.

### 4. Frontend

- New `frontend/src/research/` (or `desk/`) component `ConversationPanel`: header button **"+ New conversation"**, search box **"Search conversations…"** (debounced ~300 ms, calls `GET /conversations?q=`), list of items (title + relative time "2h ago"), active item highlighted, hover actions **Rename** (inline edit) and **Delete** (confirm "Delete this conversation? This cannot be undone."). Collapsible; collapsed state kept in `localStorage` (try/catch).
- Thread selection lives in the URL: `/research?c=<thread_id>`. No `c` → a new id is generated and written with `replace`. Reload keeps the open conversation. `DeskView` keeps `key={threadId}` so switching remounts and the existing `/copilot/market-desk/history` reload shows messages and cards.
- The panel refreshes its list after each finished run (new/updated conversation) and after rename/delete.
- Deleting the open conversation opens a fresh one.
- `AppLayout`: remove the "Session" box and the "+ New session" button (replaced by the panel). `App.tsx` no longer owns a thread id.
- A brand-new conversation appears in the list only after its first question (the index is written by the graph).

## Error handling

- Store down / embedding error during a turn → logged, turn continues, conversation simply missing from the list.
- `GET /conversations` failure → panel shows "Couldn't load conversations" with a Retry button; the chat stays usable.
- Delete of an unknown id → 204 (idempotent).
- Search with an empty/whitespace `q` → plain list.

## Testing

Backend (pytest, `memory` store backend + fake embeddings, no network):
- `create_store` sqlite backend: a fact saved, store reopened on the same file, fact still there.
- `record_conversation_turn`: creates with title from first question; second turn keeps title, updates `updated_at` and `questions`; rename survives a later turn; non-`desk_` ids ignored.
- `list_conversations`: order by `updated_at`; `q` returns semantic matches.
- `delete_conversation`: checkpoints gone (`aget_tuple` is None) and index entry gone.
- `record_question` node: an indexing error does not fail the turn.
- Router: GET / PATCH (404, length validation) / DELETE (400 on non-`desk_`).

Frontend (vitest): panel lists, search calls the API with `q`, new conversation changes `?c=`, rename and delete flows (confirm), delete of the active one opens a new one, error + Retry state.

Live check after implementation: ask two questions in two conversations, reload, reopen the first, search by meaning, rename, delete.

## Docs

- `CLAUDE.md`: store backend + env vars `STORE_BACKEND`, `STORE_DB_PATH`; conversations router; Research history.
- `docs/TOOLS.md`: memory tools now backed by a durable store (no tool added or renamed).

## Out of scope

- Client pages history, importing old orphan threads, LLM titles, prod/AWS durable store, sharing or exporting conversations.
