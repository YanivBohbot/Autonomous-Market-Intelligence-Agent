# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands must be run from inside `market-intelligence-agent/` with the `.venv` active, using `uv run`.

```bash
# One-time setup: create the SQLite customer database
uv run python create_db.py

# One-time setup: ingest PDFs from ./data/ into Pinecone
uv run python -m app.ingest

# Run the FastAPI backend (port 8000)
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload

# Run the Streamlit frontend (port 8080)
uv run streamlit run app/ui/app.py --server.port 8080 --server.address 0.0.0.0

# Run the React dev console (port 5173) — proxies to the backend on :8000
cd frontend && npm install && npm run dev

# Smoke-test the agent
uv run python test_agent.py

# Run unit tests
uv run pytest tests/ -v

# Test the MCP CRM tool in isolation
uv run python app/agent/tools/mcp_clients/mcp_client.py
```

## Required `.env` keys

`app/core/config.py` uses `pydantic-settings` and will raise at import time if any key is missing:

```
OPENAI_API_KEY, OPENAI_MODEL, OPENAI_EMBEDDING_MODEL
PINECONE_API_KEY, PINECONE_INDEX_NAME
TAVILY_API_KEY
EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT
```

Optional with defaults: `LOG_LEVEL` (INFO), `API_URL` (http://localhost:8000), `YFINANCE_TIMEOUT_S` (10), `WORKSPACE_ROOT` (data/workspace), `BROWSER_BACKEND` (local), `BROWSER_TOOL_ID` (none — required when `BROWSER_BACKEND=agentcore`), `BROWSER_IDLE_TTL_S` (300).

The email tool falls back to a simulation (no real send) when `EMAIL_SENDER` still contains `"ton_email"`.

## Architecture

### LangGraph state graph (`app/agent/graph.py`)

Compiled with a **SQLite checkpointer** (`data/checkpoints.db`, see `app/agent/memory/checkpointer.py`). HITL uses the **dynamic `interrupt()` pattern** with `Command(resume=...)` — no `interrupt_before`. Flow:

```
START → record_question → generate → (tool_calls?) → approval → [tools | generate]
tools → generate → … → END
```

- **record_question**: persists the user's turn as a `HumanMessage` so it shows up in checkpointed history.
- **generate**: LLM (with `TOOLS` bound) loaded from `app/agent/prompts/system.py` (`SYSTEM_PROMPT`, `ERROR_RECOVERY_PROMPT`). Decides whether to call a tool or emit a final answer.
- **approval**: inspects the last `AIMessage`'s `tool_calls`. If every call is in `READ_ONLY_TOOLS`, returns immediately. Otherwise calls `interrupt(requests)` surfacing only side-effect calls. **Atomic batch rule**: any reject cancels the entire batch via `ToolMessage`s.
- **tools** (LangGraph `ToolNode`): runs whatever the LLM called.

Note: retrieval (`search_knowledge_base`) and web search (`web_search`) are **not** separate graph nodes — they're tools the LLM calls from within the `generate`/`tools` loop, same as any other tool, and are gated by the same `READ_ONLY_TOOLS`/`approval` logic.

### Tools (`app/agent/tools/__init__.py`)

All MCP-backed tools are loaded via a single `MultiServerMCPClient` in `app/agent/tools/mcp_clients/registry.py`; per-server modules (`mcp_client.py`, `yfinance_client.py`, `filesystem_client.py`) filter that list and re-export public symbols. Tool names come from the upstream MCP servers (no controller-side prefix). yfmcp self-namespaces with `yfinance_`; the filesystem server uses unambiguous names; CRM's `read_query` is the one bare name.

| Tool name | File | Type | What it does |
|---|---|---|---|
| `send_email` | `app/agent/tools/emails.py` | side-effect | Sends via **Amazon SES** (boto3) using the verified `EMAIL_SENDER` identity. Simulates if `EMAIL_SENDER` is empty or an `@example.com` placeholder. SMTP fields kept optional for legacy local dev only. |
| `read_query` | `app/agent/tools/mcp_clients/mcp_client.py` | read-only | MCP stdio client → `mcp-server-sqlite` → `read_query` against `customers.db`. |
| `yfinance_get_ticker_info` | `app/agent/tools/mcp_clients/yfinance_client.py` | read-only | MCP stdio client → `yfmcp` → `get_ticker_info(ticker)`. |
| `yfinance_get_price_history` | same | read-only | `get_price_history(ticker, period="1mo")`. |
| `yfinance_get_ticker_news` | same | read-only | `get_ticker_news(ticker, limit=5)`. |
| `read_text_file` | `app/agent/tools/mcp_clients/filesystem_client.py` | read-only | MCP stdio client → `@modelcontextprotocol/server-filesystem` → `read_text_file(path)` inside `data/workspace/`. |
| `list_directory` | same | read-only | `list_directory(path)` inside `data/workspace/`. |
| `write_file` | same | side-effect | `write_file(path, content)` inside `data/workspace/`. Gated by `approval_node`. |
| `browser_navigate` | `app/agent/tools/mcp_clients/browser_client.py` | read-only | MCP stdio client → `@playwright/mcp` → `browser_navigate(url)` (headless Chromium). |
| `browser_snapshot` | same | read-only | Returns the current page as an accessibility tree (LLM-friendly structured text). |
| `browser_take_screenshot` | same | read-only | Saves a PNG into `data/workspace/screenshots/`. |
| `recall_memory` | `app/agent/tools/memory.py` | read-only | Look up a user fact in LangGraph's BaseStore by key. |
| `list_memories` | same | read-only | Return every user fact in memory as `key = value` strings. |
| `save_memory` | same | side-effect | Persist `{key: value}` under namespace `("user_facts",)`. Gated by `approval_node`. |
| `search_knowledge_base` | `app/agent/tools/knowledge_base.py` | read-only | Semantic search over ingested company reports/PDFs (Pinecone). Returns chunks prefixed `[Source: filename, page N]`. `source_filter` restricts to one document by filename substring. |
| `web_search` | `app/agent/tools/knowledge_base.py` | read-only | Live web search (Tavily), top 3 results, advanced depth. Fallback/supplement when the knowledge base has nothing relevant. |

`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot", "recall_memory", "list_memories", "search_knowledge_base", "web_search"}` is the allowlist consulted by `approval_node` to skip the interrupt for safe reads.

### Human-in-the-Loop (HITL) flow

1. `POST /stream` (in `app/api/routers/stream.py`) — SSE; streams `node`/`token` events as the graph runs, then a terminal `interrupted` event (`{action, next_step}`) when `interrupt()` fires, or `done` on normal completion. There is no non-streaming `/chat` endpoint.
2. `POST /approve` (in `app/api/routers/approve.py`) — resumes via `Command(resume="approve")` or `Command(resume="reject")`. The decision is a single global verdict that `approval_node` broadcasts across every pending side-effect call in the batch. Per-call approve/reject is not currently supported by the router contract.
3. Multiple side-effect calls in one batch share the single global decision; on reject, **all** tool calls in the batch (read-only included) are cancelled with `ToolMessage("Action cancelled by user.")`. Unknown / malformed resume payloads fail closed (cancel).
4. Session state persists across server restarts via the SQLite checkpointer keyed on `thread_id`.

### API routers (`app/api/routers/`)

- `health.py` — `/health` returns version + status (also `/ping` + `/invocations` for the AgentCore runtime contract).
- `stream.py` — `/stream` (SSE one-shot run; emits `node`, `token`, then `interrupted`/`done`/`error` events).
- `approve.py` — `/approve` for HITL resume.
- `gptlive_session.py` — `POST /gptlive/session` proxies the browser's WebRTC SDP offer to OpenAI (`client.live.create`) and spawns the voice delegation worker as a background task.
- `_helpers.py` — shared graph-invocation utilities.

### API models (`app/api/models/models.py`)

- `StreamRequest`: `query: str`, `thread_id: str = "default_thread"` — body for `/stream`.
- `ChatResponse`: `response: str`, `status: str` (`"completed"|"interrupted"`), `next_step: str|None` — returned by `/approve`.
- `ApproveRequest`: `thread_id: str`, `approved: bool` (single global verdict for the whole interrupted batch).
- `HealthResponse`, `GptLiveSessionRequest`/`GptLiveSessionResponse` round out the schema.

### Voice mode (`app/voice/` + Streamlit panel)

OpenAI **GPT-Live** in client-delegation mode. There is no separate worker process:
the browser opens a WebRTC session directly with OpenAI (offer/answer proxied through
`POST /gptlive/session` so the API key stays server-side), and the FastAPI process
spawns a background `asyncio` task (`app.voice.worker.run_delegation_worker`) that
attaches to that session over a **sideband** WebSocket
(`client.live.sideband.connect(session_id=...)`). GPT-Live handles audio I/O and
transport entirely; the delegation worker only sees `session.delegation.created`
events and the buffered `session.input_transcript.delta` text, and replies via
`connection.session.commentary.append(...)`. It invokes the **same** compiled
LangGraph voice workflow (`app.voice.graph.build_voice_agent_app`, built once in
`server.py`'s lifespan alongside the text graph) — tools and HITL behave identically
to text mode; only the transport differs.

- `app/voice/worker.py` — `run_delegation_worker(session_id, thread_id, agent_app)`: the sideband event loop.
- `app/voice/session.py` — transport-agnostic helpers: `VOICE_INSTRUCTIONS`, `_ToolCallLogger`, `strip_binary_score_prefix`.
- `app/voice/hitl.py` — verbalizes interrupts and maps yes/no (English or Hebrew כן/לא) to `Command(resume=…)`.
- `app/api/routers/gptlive_session.py` — `POST /gptlive/session` bootstraps the session.
- `app/ui/voice_panel.py` — `render_voice_panel()` embeds the browser-side WebRTC client
  (`RTCPeerConnection` + `getUserMedia`) via `st.components.v1.html`. Activated by the
  `🎤 Enable voice` sidebar toggle in `app/ui/app.py`. Voice and text share the
  same `thread_id` (Streamlit generates one `web_session_<uuid>` per browser
  tab and passes it to both `/stream` and `/gptlive/session`), so they're one
  continuous LangGraph conversation. `GET /voice/{thread_id}/transcript`
  mirrors voice turns (and HITL pause state) into the Streamlit chat, since
  the voice delegation worker runs as a background task with no direct line
  back into the Streamlit process.

See `docs/VOICE.md` for env vars, run order, and the Hebrew-support caveat.

### Data ingestion (`app/ingest.py`)

Reads all PDFs from `./data/`, splits at 1000 chars / 200 overlap, embeds with `text-embedding-3-small`, and upserts into Pinecone. Run once per document set. The Pinecone index must already exist. It also rewrites `app/agent/tools/kb_documents.json`, the manifest `search_knowledge_base`'s `source_filter` resolves against — **commit it after ingesting**, since the AgentCore image ships `app/` but not `data/`.

## Spec & plan workflow

Specs live in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`. The agentic-expansion roadmap (`docs/superpowers/specs/2026-05-07-agentic-expansion-roadmap.md`) decomposes future work into 6 subsystems; subsystem #1 (Yahoo Finance MCP) is shipped on master.

## Project rules

### Rule: keep `docs/TOOLS.md` in sync with `TOOLS`

Whenever a new tool — native LangChain or MCP-backed — is added to `TOOLS` in `app/agent/tools/__init__.py`, update `docs/TOOLS.md` in the same change:

1. Add a row to the summary table (name, type, backend, args, what it does, why we have it).
2. Add a short sub-section under "Per-tool details" with file path, *What* (one sentence), and *Why* (one or two sentences explaining the purpose / what capability it unlocks).
3. If the tool is read-only, also add its name to `READ_ONLY_TOOLS` and mention this in the entry.

Do not merge a tool addition without updating `docs/TOOLS.md`. The same applies to renaming or removing a tool — the registry is the single source of truth for what the agent can do and why.