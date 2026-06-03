# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands must be run from inside `market-intelligence-agent/` with the `.venv` active, using `uv run`.

```bash
# One-time setup: create the SQLite customer database
uv run python create_db.py

# One-time setup: ingest PDFs from ./data/ into Pinecone
uv run python app/ingest.py

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
START → rag → grader → [generate | web_search → generate]
generate → (tool_calls?) → approval → [tools | generate]
tools → generate → … → END
```

- **rag**: pulls top-3 chunks from Pinecone via semantic similarity.
- **grader**: binary LLM filter — drops chunks that don't answer the question.
- **grader → generate** if any chunks passed, **grader → web_search** if none.
- **web_search**: Tavily advanced search, max 3 results; always feeds into generate.
- **generate**: LLM (with `TOOLS` bound) loaded from `app/agent/prompts/system.py` (`SYSTEM_PROMPT`, `ERROR_RECOVERY_PROMPT`). Decides whether to call a tool or emit a final answer.
- **approval**: inspects the last `AIMessage`'s `tool_calls`. If every call is in `READ_ONLY_TOOLS`, returns immediately. Otherwise calls `interrupt(requests)` surfacing only side-effect calls. **Atomic batch rule**: any reject cancels the entire batch via `ToolMessage`s.
- **tools** (LangGraph `ToolNode`): runs whatever the LLM called.

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

`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot", "recall_memory", "list_memories"}` is the allowlist consulted by `approval_node` to skip the interrupt for safe reads.

### Human-in-the-Loop (HITL) flow

1. `POST /chat` (in `app/api/routers/stream.py`) — runs the graph until `interrupt()` fires, returns `status: "interrupted"` with the pending tool-call payload. Streaming variant exposed at `/chat/stream`.
2. `POST /approve` (in `app/api/routers/approve.py`) — resumes via `Command(resume="approve")` or `Command(resume="reject")`. The decision is a single global verdict that `approval_node` broadcasts across every pending side-effect call in the batch. Per-call approve/reject is not currently supported by the router contract.
3. Multiple side-effect calls in one batch share the single global decision; on reject, **all** tool calls in the batch (read-only included) are cancelled with `ToolMessage("Action cancelled by user.")`. Unknown / malformed resume payloads fail closed (cancel).
4. Session state persists across server restarts via the SQLite checkpointer keyed on `thread_id`.

### API routers (`app/api/routers/`)

- `health.py` — `/health` returns version + status.
- `stream.py` — `/chat` (one-shot) and `/chat/stream` (SSE).
- `approve.py` — `/approve` for HITL resume.
- `_helpers.py` — shared graph-invocation utilities.

### API models (`app/api/models/models.py`)

- `ChatRequest`: `query: str`, `thread_id: str = "default_thread"`
- `ChatResponse`: `response: str`, `status: "completed"|"interrupted"`, `next_step: str|None`, `pending_tool_calls: list|None`
- `ApproveRequest`: `thread_id: str`, `approved: bool` (single global verdict for the whole interrupted batch)

### Voice mode (`app/voice/` + Streamlit panel)

A separate `livekit-agents` worker process (`uv run python -m app.voice.worker dev`)
joins LiveKit Cloud rooms and runs the pipeline
`Deepgram STT → langchain.LLMAdapter(graph=agent_app) → ElevenLabs TTS`. The
worker imports the **same** compiled LangGraph workflow as the FastAPI app —
RAG, grader, tools, and HITL behave identically; only the transport differs.

- `app/voice/worker.py` — entrypoint; `agents.cli.run_app`.
- `app/voice/session.py` — `MarketIntelAssistant` + `AgentSession` factory.
- `app/voice/hitl.py` — verbalizes interrupts and maps yes/no to `Command(resume=…)`.
- `app/api/routers/livekit_token.py` — `POST /livekit/token` mints room-join JWTs.
- `app/ui/voice_panel.py` — `render_voice_panel()` injects a LiveKit JS client into
  the existing Streamlit app via `st.components.v1.html`. Activated by the
  `🎤 Enable voice` sidebar toggle in `app/ui/app.py`. Voice and text sessions
  use different `thread_id`s (`voice-<room>` vs `web_session_<uuid>`).

See `docs/VOICE.md` for env vars and run order.

### Data ingestion (`app/ingest.py`)

Reads all PDFs from `./data/`, splits at 1000 chars / 200 overlap, embeds with `text-embedding-3-small`, and upserts into Pinecone. Run once per document set. The Pinecone index must already exist.

## Spec & plan workflow

Specs live in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`. The agentic-expansion roadmap (`docs/superpowers/specs/2026-05-07-agentic-expansion-roadmap.md`) decomposes future work into 6 subsystems; subsystem #1 (Yahoo Finance MCP) is shipped on master.

## Project rules

### Rule: keep `docs/TOOLS.md` in sync with `TOOLS`

Whenever a new tool — native LangChain or MCP-backed — is added to `TOOLS` in `app/agent/tools/__init__.py`, update `docs/TOOLS.md` in the same change:

1. Add a row to the summary table (name, type, backend, args, what it does, why we have it).
2. Add a short sub-section under "Per-tool details" with file path, *What* (one sentence), and *Why* (one or two sentences explaining the purpose / what capability it unlocks).
3. If the tool is read-only, also add its name to `READ_ONLY_TOOLS` and mention this in the entry.

Do not merge a tool addition without updating `docs/TOOLS.md`. The same applies to renaming or removing a tool — the registry is the single source of truth for what the agent can do and why.