# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands must be run from inside `market-intelligence-agent/` with the `.venv` active, using `uv run`.

```bash
# (Re)build the wealth-management SQLite DB (customers.db) — commit the result
uv run python create_db.py

# One-time setup: ingest PDFs from ./data/ into Pinecone
uv run python -m app.ingest

# Run the FastAPI backend (port 8000)
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload

# Run the React dev console (port 5173) — proxies to the backend on :8000
cd frontend && npm install && npm run dev

# Smoke-test the agent
uv run python test_agent.py

# Run unit tests
uv run pytest tests/ -v

# One-time: install the Chromium build @playwright/mcp@latest expects (local browser tools)
npx -y @playwright/mcp@latest install-browser chrome-for-testing

# Test the MCP CRM tool in isolation
uv run python app/agent/tools/mcp_clients/mcp_client.py
```

## Dependency versions

`uv.lock` is the source of truth. `requirements.agentcore.txt` (the AgentCore prod image) pins the LangChain/LangGraph family **exactly** to the `uv.lock` versions so prod runs what the tests ran. To upgrade: `uv lock --upgrade-package <pkg> ...` → `uv sync` → run tests → copy the new versions into `requirements.agentcore.txt`.

## Required `.env` keys

`app/core/config.py` uses `pydantic-settings` and will raise at import time if any key is missing:

```
OPENAI_API_KEY, OPENAI_MODEL, OPENAI_EMBEDDING_MODEL
PINECONE_API_KEY, PINECONE_INDEX_NAME
TAVILY_API_KEY
EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT
```

Optional with defaults: `LOG_LEVEL` (INFO), `API_URL` (http://localhost:8000), `YFINANCE_TIMEOUT_S` (10), `WORKSPACE_ROOT` (data/workspace), `BROWSER_BACKEND` (local), `BROWSER_TOOL_ID` (none — required when `BROWSER_BACKEND=agentcore`), `BROWSER_IDLE_TTL_S` (300), `COPILOT_ENABLED` (False — enables the Market Desk AG-UI endpoint `/copilot/market-desk`; set `true` in local `.env`), `ANTHROPIC_API_KEY` (empty — enables `ModelFallbackMiddleware`/`with_fallbacks()` to `claude-sonnet-5-5` if OpenAI is still failing after `ModelRetryMiddleware`'s own retries are exhausted; see `app/agent/middleware.py` and `app/agent/nodes/generate.py`).

The email tool falls back to a simulation (no real send) when `EMAIL_SENDER` still contains `"ton_email"`.

## Architecture

### Legacy single-agent graph (`app/agent/graph.py`)

This graph is retained for shared node helpers (no runtime caller remains; removal is a tracked follow-up); the main text transports no longer compile it. Its HITL uses the dynamic `interrupt()` pattern with `Command(resume=...)` — no `interrupt_before`. Flow:

```
START → record_question → pii_guard → (sensitive?) → END
                              ↓ no
                           generate → (tool_calls?) → approval → [tools | generate]
tools → generate → … → END
```

- **record_question**: persists the user's turn as a `HumanMessage` so it shows up in checkpointed history.
- **pii_guard** (`app/agent/guardrails/node.py`): if the last `HumanMessage` contains a credit card, short-circuits straight to `END` with a warning `AIMessage` — `generate` never runs, no user data reaches the LLM. Email is NOT checked here (this graph needs `send_email` to work — see `app/agent/middleware.py` below). Shared detection logic lives in `app/agent/guardrails/` (named for the official LangChain "guardrails" concept `PIIMiddleware` itself belongs to, not narrowed to "pii" since more guardrails can land here later).
- **generate**: LLM (with `TOOLS` bound) loaded from `app/agent/prompts/system.py` (`SYSTEM_PROMPT`, `ERROR_RECOVERY_PROMPT`). Decides whether to call a tool or emit a final answer.
- **approval**: inspects the last `AIMessage`'s `tool_calls`. If every call is in `READ_ONLY_TOOLS`, returns immediately. Otherwise calls `interrupt(requests)` surfacing only side-effect calls. **Atomic batch rule**: any reject cancels the entire batch via `ToolMessage`s.
- **tools** (LangGraph `ToolNode`): runs whatever the LLM called.

Note: retrieval (`search_knowledge_base`) and web search (`web_search`) are **not** separate graph nodes — they're tools the LLM calls from within the `generate`/`tools` loop, same as any other tool, and are gated by the same `READ_ONLY_TOOLS`/`approval` logic.

### Tools (`app/agent/tools/__init__.py`)

All MCP-backed tools are loaded via a single `MultiServerMCPClient` in `app/agent/tools/mcp_clients/registry.py`; per-server modules (`mcp_client.py`, `yfinance_client.py`, `filesystem_client.py`) filter that list and re-export public symbols. Tool names come from the upstream MCP servers (no controller-side prefix). yfmcp self-namespaces with `yfinance_`; the filesystem server uses unambiguous names; CRM's `read_query` is the one bare name.

| Tool name | File | Type | What it does |
|---|---|---|---|
| `send_email` | `app/agent/tools/emails.py` | side-effect | Sends via **Amazon SES** (boto3) using the verified `EMAIL_SENDER` identity. Simulates if `EMAIL_SENDER` is empty or an `@example.com` placeholder. SMTP fields kept optional for legacy local dev only. |
| `read_query` | `app/agent/tools/mcp_clients/mcp_client.py` | read-only | MCP stdio client → `mcp-server-sqlite` → `read_query` against `customers.db` (wealth-management DB: companies, clients, transactions, holdings, watchlists; seeded by `create_db.py`). |
| `list_tables` / `describe_table` | same | read-only | Schema discovery on `customers.db`. |
| `portfolio_metrics` / `pct_change` | `app/agent/tools/finance_calc.py` | read-only | Deterministic portfolio math (value, P&L, weights, sectors) and % change. |
| `concentration_screen` | `app/agent/tools/concentration.py` | read-only | Finds clients with more than `threshold_pct` (default 30) of their portfolio in one stock. The LLM passes only a filter (`risk_profile`, `client_names`); the tool loads holdings via `read_query` and live prices via yfinance itself, then computes `breaches` with `finance_calc.compute_concentration_screen`. ETFs (`exclude_sectors`, default `["ETF"]`) count in totals but are never flagged. No position copying by the LLM = deterministic answers with gpt-4o-mini. |
| `yfinance_get_ticker_info` | `app/agent/tools/mcp_clients/yfinance_client.py` | read-only | MCP stdio client → `yfmcp` → `get_ticker_info(ticker)`. |
| `yfinance_get_price_history` | same | read-only | `get_price_history(ticker, period="1mo")`. |
| `yfinance_get_ticker_news` | same | read-only | `get_ticker_news(ticker, limit=5)`. |
| `read_text_file` | `app/agent/tools/mcp_clients/filesystem_client.py` | read-only | MCP stdio client → `@modelcontextprotocol/server-filesystem` → `read_text_file(path)` inside `data/workspace/`. |
| `list_directory` | same | read-only | `list_directory(path)` inside `data/workspace/`. |
| `write_file` | same | side-effect | `write_file(path, content)` inside `data/workspace/`. Gated by `approval_node`. |
| `browser_navigate` | `app/agent/tools/mcp_clients/browser_client.py` | read-only | MCP stdio client → `@playwright/mcp` → `browser_navigate(url)` (headless Chromium). Locally the 3 browser tools share ONE long-lived session per event loop (`browser_session.py`) so navigate/snapshot/screenshot act on the same page; the server runs in `data/workspace/screenshots/`. |
| `browser_snapshot` | same | read-only | Returns the current page as an accessibility tree (LLM-friendly structured text). |
| `browser_take_screenshot` | same | read-only | Saves a PNG into `data/workspace/screenshots/`. |
| `recall_memory` | `app/agent/tools/memory.py` | read-only | Look up a user fact in LangGraph's BaseStore by key. |
| `list_memories` | same | read-only | Return every user fact in memory as `key = value` strings. |
| `save_memory` | same | side-effect | Persist `{key: value}` under namespace `("user_facts",)`. Gated by `approval_node`. |
| `search_knowledge_base` | `app/agent/tools/knowledge_base.py` | read-only | Semantic search over ingested company reports/PDFs through `app/rag/retriever.build_kb_retriever` — a `RerankingRetriever(BaseRetriever)` over `PineconeVectorStore.as_retriever(similarity_score_threshold, k=20, relevance ≥ 0.675 ≡ cosine 0.35)` + `PineconeRerank(bge-reranker-v2-m3)`; no `langchain-classic`. Returns chunks prefixed `[Source: filename, page N]`. `source_filter` restricts to one document by filename substring. |
| `web_search` | `app/agent/tools/knowledge_base.py` | read-only | Live web search (Tavily), top 3 results, advanced depth. Fallback/supplement when the knowledge base has nothing relevant. |

`READ_ONLY_TOOLS = {"read_query", "list_tables", "describe_table", "portfolio_metrics", "pct_change", "concentration_screen", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot", "recall_memory", "list_memories", "search_knowledge_base", "web_search"}` is the allowlist consulted by `approval_node` to skip the interrupt for safe reads.

### Human-in-the-Loop (HITL) flow

1. `POST /stream` (in `app/api/routers/stream.py`) — SSE over the shared multi-agent graph; streams nested `node`/`token` events and ends with `interrupted`, `done`, or `error`. There is no non-streaming `/chat` endpoint.
2. `POST /approve` (in `app/api/routers/approve.py`) — reads the nested specialist interrupt and translates its boolean request to `Command(resume={"decisions": [...]})`.
3. The resume payload contains exactly one `approve` or `reject` decision per pending action. A subsequent nested interrupt is surfaced instead of being mistaken for completion.
4. Session state persists across server restarts via the SQLite checkpointer keyed on `thread_id`.

### Multi-agent mode (`app/agent/multi_agent/`)

Router pattern: `load_client_context → record_question → supervisor → <specialist> → supervisor → END`. FastAPI compiles this graph once and assigns the same object to `app.state.agent_app` and `app.state.market_desk_agent.graph`. `/stream`, `/approve`, AgentCore `/invocations`, the opt-in Market Desk endpoint, and React Research voice therefore share state.

The console uses `react-router-dom` (`/research`, `/briefing`, `/clients`, `/reports`, `/data`) — not a `localStorage`-persisted mode toggle.

- One file per specialist (`rag_agent`, `finance_agent`, `portfolio_agent`, `browser_agent`, `email_agent`, `filesystem_agent`, `memory_agent`), each `build_<name>_agent()` → LangChain `create_agent(...)`, added as a subgraph node with a static edge back to `supervisor`.
- `app/agent/middleware.py` (shared with the single-agent graph, so it lives outside `multi_agent/`; named for its contents — middleware factories — rather than `common.py`): `specialist_model()` and `base_middleware(*, check_email=True)` = `SensitiveDataGuard(check_email=...)` (`app/agent/guardrails/`: blocks before any model call if the user's message contains a credit card, or — unless `check_email=False` — an email; see below), `today_prompt` (date in the system prompt), `summarization()` (`SummarizationMiddleware`: past 6000 tokens, older messages → summary, last 50 kept), `mask_credit_cards()` (`PIIMiddleware` credit_card/mask), `ModelCallLimitMiddleware(run_limit=10)`, `model_fallback()` (`ModelFallbackMiddleware` to `claude-sonnet-5-5` — opt-in, only when `ANTHROPIC_API_KEY` is set; omitted otherwise), `model_retry()` (`ModelRetryMiddleware`, default 2 retries/exponential backoff — covers a transient OpenAI error during the model call itself, which `tool_errors_to_messages` below never sees), `tool_errors_to_messages` (official `ToolErrorMiddleware`: tool exception → error ToolMessage). `rag`/`finance`/`browser` also get `redact_emails()` (their queries go to third parties); browser also gets `strip_tool_images`. `email`/`portfolio`/`memory`/`filesystem` call `base_middleware(check_email=False)` and keep addresses — they need a real one to work (`send_email`, or a report/fact tied to a client); the single-agent graph's `pii_guard` node does the same (hardcoded `check_email=False`) since it bundles `send_email` alongside everything else with no per-specialist split. `email_agent.EmailRecipientGuard`: `send_email` only to a `clients.email` address, checked at execution (after HITL approval).
- HITL uses the official `HumanInTheLoopMiddleware` (email: `send_email`, filesystem: `write_file`, memory: `save_memory`). Resume with `Command(resume={"decisions": [{"type": "approve"} | {"type": "reject", "message": ...} | {"type": "edit", "edited_action": {...}}]})`, one decision per pending call. Legacy boolean adapters expand their verdict to this same payload.

### API routers (`app/api/routers/`)

- `health.py` — `/health` returns version + status (also `/ping` + `/invocations` for the AgentCore runtime contract).
- `copilot.py` — `POST /copilot/market-desk` (AG-UI SSE over the shared multi-agent graph, agent id `market_desk`), included only when `COPILOT_ENABLED`; the wrapper is attached in `lifespan` without compiling a second graph.
- `stream.py` — `/stream` (SSE one-shot run; emits `node`, `token`, then `interrupted`/`done`/`error` events).
- `approve.py` — `/approve` for HITL resume.
- `gptlive_session.py` — `POST /gptlive/session` proxies the browser's WebRTC SDP offer to OpenAI (`client.live.create`) and spawns the voice delegation worker as a background task. `surface="research"` acquires a per-thread turn lease and uses the shared multi-agent graph; `surface` must be `research` (default); `classic` is rejected with 422. Research activity and visual HITL use `GET /voice/{thread_id}/state` and `POST /voice/{thread_id}/decision`.
- `data.py` — `/data/clients` (GET), `/data/documents` (GET), `/data/import/pdf` (POST), `/data/import/preview` (POST), `/data/import/confirm` (POST). Deterministic, non-agentic CRUD + import for the React console's `/data` section — no LLM, not wired into either graph. Direct sqlite3 access to `customers.db` (bare relative path, same convention as `create_db.py` and the MCP sqlite server), not the MCP indirection the agent uses. See `docs/superpowers/specs/2026-10-03-data-import-and-view-design.md`.
- `_helpers.py` — shared graph-invocation utilities.

### API models (`app/api/models/models.py`)

- `StreamRequest`: `query: str`, `thread_id: str = "default_thread"` — body for `/stream`.
- `ChatResponse`: `response: str`, `status: str` (`"completed"|"interrupted"`), `next_step: str|None` — returned by `/approve`.
- `ApproveRequest`: `thread_id: str`, `approved: bool` (single global verdict for the whole interrupted batch).
- `HealthResponse`, `GptLiveSessionRequest`/`GptLiveSessionResponse` round out the schema.

### Voice mode (`app/voice/`, React Research)

OpenAI **GPT-Live** in client-delegation mode. There is no separate worker process:
the browser opens a WebRTC session directly with OpenAI (offer/answer proxied through
`POST /gptlive/session` so the API key stays server-side), and the FastAPI process
spawns a background `asyncio` task (`app.voice.worker.run_delegation_worker`) that
attaches to that session over a **sideband** WebSocket
(`client.live.sideband.connect(session_id=...)`). GPT-Live handles audio I/O and
transport entirely; the delegation worker only sees `session.delegation.created`
events and the buffered `session.input_transcript.delta` text, and replies via
`connection.session.commentary.append(...)`.

React `/research` passes `surface="research"` and invokes the shared multi-agent
graph (`app.state.agent_app`) with the same thread/checkpoint as typed Research.
Only one text or voice turn may own a thread at a time. The composer locks text
while voice is active and shows Connecting, Listening, Analyzing, Speaking, or
Approval required. Activity is polled incrementally from
`GET /voice/{thread_id}/state?after=<sequence>` and merged into the normal activity
rail. Pending side effects use the same visual HITL cards and generated-report
selector; decisions are idempotently submitted to
`POST /voice/{thread_id}/decision`, and remain actionable after disconnect.

Spoken turns are shown in the Research chat: a live caption from `session.input_transcript.delta` while speaking, then the committed user/assistant messages, reloaded from `/copilot/market-desk/history` on `run_finished`/`approval_required` (see `docs/superpowers/specs/2026-10-11-research-voice-chat-transcript-design.md`).

- `app/voice/worker.py` — `run_delegation_worker(session_id, thread_id, agent_app)`: the sideband event loop.
- `app/voice/session.py` — transport-agnostic helpers: `VOICE_INSTRUCTIONS`, `_ToolCallLogger`, `strip_binary_score_prefix`.
- `app/voice/hitl.py` — verbalizes interrupts and maps yes/no (English or Hebrew כן/לא) to `Command(resume=…)`.
- `app/voice/research_runtime.py` and `activity_store.py` — multi-agent Research turns, incremental activity, stable interrupts, and first-decision-wins handling.
- `app/api/routers/gptlive_session.py` — bootstraps the Research surface and exposes Research state/decision endpoints.
- `frontend/src/voice/` — continuous Research WebRTC lifecycle, phase UI, activity adapter, and visual approval bridge.

See `docs/VOICE.md` for env vars, run order, and the Hebrew-support caveat.

### Data ingestion (`app/ingest.py`, `app/rag/`)

RAG is built from standard LangChain components in `app/rag/`: `loaders.load_pdf` (Document Loader, `PyPDFLoader`), `splitters.build_text_splitter` (Text Splitter, Recursive 1000/200), `vectorstore.get_vectorstore` (the single `PineconeVectorStore` + `OpenAIEmbeddings` instance), `ingestion.index_documents` (split → `filename` metadata → deterministic sha256 chunk IDs → `add_documents(ids=...)`) and `retriever.build_kb_retriever` (Retriever). Both ingestion paths use them: the bulk CLI `app/ingest.py` and the Data-page upload `app/data_import/pdf_ingest.py`, both with `source` = bare filename so the same PDF gets the same chunk IDs (overwrite, not duplicate). The retriever also drops chunks with identical text before reranking (older index entries ingested with source `data/x.pdf` are duplicates of `x.pdf`).

`app/ingest.py` reads all PDFs from `./data/`, splits at 1000 chars / 200 overlap, embeds with `text-embedding-3-small`, and upserts into Pinecone. Run once per document set. The Pinecone index must already exist. It also rewrites `app/agent/tools/kb_documents.json`, the manifest `search_knowledge_base`'s `source_filter` resolves against — **commit it after ingesting**, since the AgentCore image ships `app/` but not `data/`.

## Spec & plan workflow

Specs live in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`. The agentic-expansion roadmap (`docs/superpowers/specs/2026-05-07-agentic-expansion-roadmap.md`) decomposes future work into 6 subsystems; subsystem #1 (Yahoo Finance MCP) is shipped on master.

## Project rules

### Rule: keep `docs/TOOLS.md` in sync with `TOOLS`

Whenever a new tool — native LangChain or MCP-backed — is added to `TOOLS` in `app/agent/tools/__init__.py`, update `docs/TOOLS.md` in the same change:

1. Add a row to the summary table (name, type, backend, args, what it does, why we have it).
2. Add a short sub-section under "Per-tool details" with file path, *What* (one sentence), and *Why* (one or two sentences explaining the purpose / what capability it unlocks).
3. If the tool is read-only, also add its name to `READ_ONLY_TOOLS` and mention this in the entry.

Do not merge a tool addition without updating `docs/TOOLS.md`. The same applies to renaming or removing a tool — the registry is the single source of truth for what the agent can do and why.
