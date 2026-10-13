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
uv run python app/agent/mcp_clients/crm_client.py
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

Optional with defaults: `LOG_LEVEL` (INFO), `API_URL` (http://localhost:8000), `YFINANCE_TIMEOUT_S` (10), `WORKSPACE_ROOT` (data/workspace), `BROWSER_BACKEND` (local), `BROWSER_TOOL_ID` (none — required when `BROWSER_BACKEND=agentcore`), `BROWSER_IDLE_TTL_S` (300), `COPILOT_ENABLED` (False — enables the Market Desk AG-UI endpoint `/copilot/market-desk`; set `true` in local `.env`), `MODERATION_ENABLED` (True — `OpenAIModerationMiddleware` on every specialist; `tests/conftest.py` sets it false), `ANTHROPIC_API_KEY` (empty — enables `ModelFallbackMiddleware`/`with_fallbacks()` to `claude-sonnet-5-5` if OpenAI is still failing after `ModelRetryMiddleware`'s own retries are exhausted; see `app/agent/middleware.py` and `app/agent/nodes/generate.py`).

The email tool falls back to a simulation (no real send) when `EMAIL_SENDER` still contains `"ton_email"`.

## Architecture

### Agent graph

There is a single agent graph: the multi-agent supervisor graph: wiring in `app/agent/orchestration/` (`graph.py`, `supervisor.py`, `state.py`), specialists in `app/agent/agents_specialist/` (see "Multi-agent mode" below). The former single-agent graph (`app/agent/graph.py`, `nodes/generate.py`, `state.py`, the `pii_guard` node, `prompts/system.py`) was removed on 2026-10-12 once no runtime caller remained. Its credit-card guard lives on as `block_credit_cards`, a `@before_agent` middleware on the supervisor's router agent, and its HITL as `HumanInTheLoopMiddleware` per specialist.

### Tools (`app/agent/tools/__init__.py`)

All MCP-backed tools are loaded via a single `MultiServerMCPClient` in `app/agent/mcp_clients/registry.py`; per-server modules (`crm_client.py`, `yfinance_client.py`, `filesystem_client.py`) filter that list and re-export public symbols. Tool names come from the upstream MCP servers (no controller-side prefix). yfmcp self-namespaces with `yfinance_`; the filesystem server uses unambiguous names; CRM's `read_query` is the one bare name.

| Tool name | File | Type | What it does |
|---|---|---|---|
| `send_email` | `app/agent/tools/emails.py` | side-effect | Sends via **Amazon SES** (boto3) using the verified `EMAIL_SENDER` identity. Simulates if `EMAIL_SENDER` is empty or an `@example.com` placeholder. SMTP fields kept optional for legacy local dev only. |
| `read_query` | `app/agent/mcp_clients/crm_client.py` | read-only | MCP stdio client → `mcp-server-sqlite` → `read_query` against `customers.db` (wealth-management DB: companies, clients, transactions, holdings, watchlists; seeded by `create_db.py`). |
| `list_tables` / `describe_table` | same | read-only | Schema discovery on `customers.db`. |
| `portfolio_metrics` / `pct_change` | `app/agent/tools/finance_calc.py` | read-only | Deterministic portfolio math (value, P&L, weights, sectors) and % change. |
| `concentration_screen` | `app/agent/tools/concentration.py` | read-only | Finds clients with more than `threshold_pct` (default 30) of their portfolio in one stock. The LLM passes only a filter (`risk_profile`, `client_names`); the tool loads holdings via `read_query` and live prices via yfinance itself, then computes `breaches` with `finance_calc.compute_concentration_screen`. ETFs (`exclude_sectors`, default `["ETF"]`) count in totals but are never flagged. No position copying by the LLM = deterministic answers with gpt-4o-mini. |
| `compare_companies` | `app/agent/tools/compare_companies.py` | read-only | 2-4 tickers side by side (price, market cap, P/E, 52-week range position, period return, rebased series), computed in Python from the yfinance tools. finance_agent; comparison card. |
| `simulate_portfolio_change` | `app/agent/tools/what_if.py` | read-only | What-if on one client's portfolio: hypothetical buys/sells (pct or shares) → before/after weights, value, `cash_delta`, concentration. Never writes to the DB. portfolio_agent; what-if card. |
| `watchlist_alerts` | `app/agent/tools/watchlist_alerts.py` | read-only | Watchlist alerts vs live prices: triggered / near (`near_pct`, default 5) / watching. portfolio_agent; alert card. |
| `ask_user_choice` | `app/agent/tools/user_choice.py` | interactive | LangGraph `interrupt()` choice card (buttons/checkboxes) in Market Desk; resumes with the selected labels. portfolio/finance/email; hidden unless `state["ag-ui"]` is present (`OnlyOnAgUi`). NOT in `READ_ONLY_TOOLS` (tool retry would catch the interrupt). |
| `yfinance_get_ticker_info` | `app/agent/mcp_clients/yfinance_client.py` | read-only | MCP stdio client → `yfmcp` → `get_ticker_info(ticker)`. |
| `yfinance_get_price_history` | same | read-only | `get_price_history(ticker, period="1mo")`. |
| `yfinance_get_ticker_news` | `app/agent/mcp_clients/yfinance_news.py` | read-only | Native `yf.Search` replacement for yfmcp's dead news tool (same name/shape); headlines whose title names the ticker/company, `limit=5`. Gateway mode uses the yfinance Lambda. |
| `read_text_file` | `app/agent/mcp_clients/filesystem_client.py` | read-only | MCP stdio client → `@modelcontextprotocol/server-filesystem` → `read_text_file(path)` inside `data/workspace/`. |
| `list_directory` | same | read-only | `list_directory(path)` inside `data/workspace/`. |
| `write_file` | same | side-effect | `write_file(path, content)` inside `data/workspace/`. Gated by `HumanInTheLoopMiddleware` (HITL). |
| `browser_navigate` | `app/agent/mcp_clients/browser_client.py` | read-only | MCP stdio client → `@playwright/mcp` → `browser_navigate(url)` (headless Chromium). Locally the 3 browser tools share ONE long-lived session per event loop (`browser_session.py`) so navigate/snapshot/screenshot act on the same page; the server runs in `data/workspace/screenshots/`. |
| `browser_snapshot` | same | read-only | Returns the current page as an accessibility tree (LLM-friendly structured text). |
| `browser_take_screenshot` | same | read-only | Saves a PNG into `data/workspace/screenshots/`. |
| `recall_memory` | `app/agent/tools/memory.py` | read-only | Look up a user fact in LangGraph's BaseStore by key. |
| `list_memories` | same | read-only | Return every user fact in memory as `key = value` strings. |
| `save_memory` | same | side-effect | Persist `{key: value}` under namespace `("user_facts",)`. Gated by `HumanInTheLoopMiddleware` (HITL). |
| `search_knowledge_base` | `app/agent/tools/knowledge_base.py` | read-only | Hybrid search over ingested company reports/PDFs through `app/rag/retriever.build_kb_retriever` — a `RerankingRetriever(BaseRetriever)` over `PineconeVectorStore.as_retriever(similarity_score_threshold, k=20, relevance ≥ 0.675 ≡ cosine 0.35)` + BM25 candidates (`app/rag/keyword_search.py`, only when the vector side found something) + `PineconeRerank(bge-reranker-v2-m3)`; no `langchain-classic`. Returns chunks prefixed `[Source: filename, page N]`. `source_filter` restricts to one document by filename substring. |
| `web_search` | `app/agent/tools/knowledge_base.py` | read-only | Live web search (Tavily), top 3 results, advanced depth. Fallback/supplement when the knowledge base has nothing relevant. |

`READ_ONLY_TOOLS = {"read_query", "list_tables", "describe_table", "portfolio_metrics", "pct_change", "concentration_screen", "compare_companies", "simulate_portfolio_change", "watchlist_alerts", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot", "recall_memory", "list_memories", "search_knowledge_base", "web_search"}` is the documented read-only classification of every tool (HITL itself is enforced per specialist by `HumanInTheLoopMiddleware`).

### Human-in-the-Loop (HITL) flow

1. `POST /stream` (in `app/api/routers/stream.py`) — SSE over the shared multi-agent graph; streams nested `node`/`token` events and ends with `interrupted`, `done`, or `error`. There is no non-streaming `/chat` endpoint.
2. `POST /approve` (in `app/api/routers/approve.py`) — reads the nested specialist interrupt and translates its boolean request to `Command(resume={"decisions": [...]})`.
3. The resume payload contains exactly one `approve` or `reject` decision per pending action. A subsequent nested interrupt is surfaced instead of being mistaken for completion.
4. Session state persists across server restarts via the SQLite checkpointer keyed on `thread_id`.

### Multi-agent mode (`app/agent/orchestration/` + `app/agent/agents_specialist/`)

Router pattern: `load_client_context → record_question → supervisor → <specialist> → supervisor → finalize_turn → END`. `supervisor_node` keeps the deterministic routing rules (hop limit, forced finish after a plain answer, portfolio→email chaining, sticky "save it", FINISH-without-answer → `rag_agent`) in Python and makes its one LLM decision through `router_agent` (`build_router_agent()` in `supervisor.py`): a `create_agent` with `tools=[]`, `response_format=RoutingDecision` (read from `result["structured_response"]`), and middleware `block_credit_cards` (`app/agent/guardrails/card_guard.py`, `@before_agent(can_jump_to=["end"])` on LangChain's `detect_credit_card`: a card in the latest user message ends the router run with the question masked under the same id plus `SENSITIVE_DATA_WARNING`, which the node copies into the conversation before ending the turn — no model call at all), `fresh_documents_prompt` + `client_context_routing_prompt` (`@dynamic_prompt`), `context_editing()`, `model_fallback()` and `model_retry()`. It is invoked with a copy of the conversation inside the node, so its own messages never enter shared state; its model carries `emit-messages`/`emit-tool-calls: False` for AG-UI, and `/stream` drops every event whose namespace is `supervisor:...`. FastAPI compiles this graph once and assigns the same object to `app.state.agent_app` and `app.state.market_desk_agent.graph`. `/stream`, `/approve`, AgentCore `/invocations`, the opt-in Market Desk endpoint, and React Research voice therefore share state.

The console uses `react-router-dom` (`/research`, `/briefing`, `/clients`, `/reports`, `/data`) — not a `localStorage`-persisted mode toggle.

- MCP clients live in `app/agent/mcp_clients/` (outside `tools/`); our own MCP server in `app/mcp_servers/browser/`; `/data` narratives in `app/narratives/`.
- Prompts mirror this split: `app/agent/prompts/orchestration_prompt.py` (`SUPERVISOR_ROUTING_PROMPT`), `prompts/agents_specialist_prompts.py` (one `<NAME>_SYSTEM_PROMPT` per specialist), `prompts/ingested_documents_prompt.py` (the `{INGESTED_DOCUMENTS}` placeholder + `kb_documents.json` reader both use), `prompts/__init__.py` (`with_today`).
- One file per specialist in `agents_specialist/` (`rag_agent`, `finance_agent`, `portfolio_agent`, `browser_agent`, `email_agent`, `filesystem_agent`, `memory_agent`), each `build_<name>_agent()` → LangChain `create_agent(...)`, added as a subgraph node with a static edge back to `supervisor`.
- `app/agent/middleware.py` (shared by `orchestration/` and `agents_specialist/`; named for its contents — middleware factories — rather than `common.py`): `specialist_model()` and `base_middleware(tools)` = `mask_credit_cards()` (prebuilt `PIIMiddleware` credit_card/mask on input, output and tool results — defense in depth behind `block_credit_cards`), `moderation()` (`OpenAIModerationMiddleware`, `omni-moderation-latest`, input + output, `exit_behavior="end"` with `MODERATION_VIOLATION_MESSAGE`; omitted when `MODERATION_ENABLED=false`, as in unit tests), `today_prompt` (date in the system prompt), `context_editing()` (official `ContextEditingMiddleware` with `ClearOldTurnToolResults`: past 4000 tokens, tool results older than the current turn + 2 previous turns become `[cleared]` in the model request only — state and Market Desk cards untouched), `summarization()` (`SummarizationMiddleware`; only acts past 50 messages, deliberately, since it rewrites shared state), `ModelCallLimitMiddleware(run_limit=10)`, `model_fallback()` (`ModelFallbackMiddleware` to `claude-sonnet-5-5` — opt-in, only when `ANTHROPIC_API_KEY` is set; omitted otherwise), `model_retry()` (`ModelRetryMiddleware`, default 2 retries/exponential backoff — covers a transient OpenAI error during the model call itself, which `tool_errors_to_messages` below never sees), `tool_errors_to_messages` (official `ToolErrorMiddleware`: tool exception → error ToolMessage), then `tool_retry(tools)` (`ToolRetryMiddleware`, 2 retries, listed after — i.e. wrapped inside — `ToolErrorMiddleware`; scoped to the specialist's **read-only** tools via `is_read_only`, so `send_email`/`write_file`/`save_memory`/`save_portfolio_report` are never retried). `rag`/`finance`/`browser` also get `redact_emails()` (`RedactEmailsForModel`: the model gets a copy of the conversation with addresses replaced by `[REDACTED_EMAIL]`, via `wrap_model_call` + LangChain's `detect_email` — their queries go to third parties; the turn proceeds, and unlike `PIIMiddleware(apply_to_input=True)` the stored conversation keeps the real address for a later `email_agent` hop); `rag` gets `tool_call_limit("web_search", 3)` and browser `tool_call_limit("browser_navigate", 5)` (`ToolCallLimitMiddleware`, `exit_behavior="continue"`); browser also gets `strip_tool_images`. `email`/`portfolio`/`memory`/`filesystem` get no email PII middleware and keep addresses — they need a real one to work (`send_email`, or a report/fact tied to a client); `apply_to_output` would also rewrite `send_email`'s recipient argument. `/stream` turns the static blocking messages of the `supervisor` node (card warning) and `OpenAIModerationMiddleware` into `token` events (`_STATIC_MESSAGE_NODES`). `email_agent.EmailRecipientGuard`: `send_email` only to a `clients.email` address, checked at execution (after HITL approval).
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

RAG is built from standard LangChain components in `app/rag/`: `loaders.load_pdf` (Document Loader, `PyPDFLoader`), `splitters.build_text_splitter` (Text Splitter, Recursive 1000/200), `vectorstore.get_vectorstore` (the single `PineconeVectorStore` + `OpenAIEmbeddings` instance), `ingestion.index_documents` (split → `filename` metadata → deterministic sha256 chunk IDs → `add_documents(ids=...)` + the same chunks into the BM25 corpus `app/rag/kb_chunks.jsonl.gz`), `keyword_search.build_keyword_retriever` (`BM25Retriever` over that corpus) and `retriever.build_kb_retriever` (Retriever: vector + BM25 candidates → rerank). Both ingestion paths use them: the bulk CLI `app/ingest.py` and the Data-page upload `app/data_import/pdf_ingest.py`, both with `source` = bare filename so the same PDF gets the same chunk IDs (overwrite, not duplicate). The retriever also drops chunks with identical text before reranking (older index entries ingested with source `data/x.pdf` are duplicates of `x.pdf`).

`app/ingest.py` reads all PDFs from `./data/`, splits at 1000 chars / 200 overlap, embeds with `text-embedding-3-small`, and upserts into Pinecone. Run once per document set. The Pinecone index must already exist. It also rewrites `app/agent/tools/kb_documents.json`, the manifest `search_knowledge_base`'s `source_filter` resolves against, and writes the BM25 corpus `app/rag/kb_chunks.jsonl.gz` — **commit both after ingesting**, since the AgentCore image ships `app/` but not `data/`. `python -m app.ingest --corpus-only` rebuilds the corpus without re-embedding. All 4 PDFs are indexed under bare-filename chunk IDs (2833 vectors, one copy each; the old `source="data\x.pdf"` IDs were deleted on 2026-10-13), so a full re-run overwrites instead of duplicating.

## Spec & plan workflow

Specs live in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`. The agentic-expansion roadmap (`docs/superpowers/specs/2026-05-07-agentic-expansion-roadmap.md`) decomposes future work into 6 subsystems; subsystem #1 (Yahoo Finance MCP) is shipped on master.

## Project rules

### Rule: keep `docs/TOOLS.md` in sync with `TOOLS`

Whenever a new tool — native LangChain or MCP-backed — is added to `TOOLS` in `app/agent/tools/__init__.py`, update `docs/TOOLS.md` in the same change:

1. Add a row to the summary table (name, type, backend, args, what it does, why we have it).
2. Add a short sub-section under "Per-tool details" with file path, *What* (one sentence), and *Why* (one or two sentences explaining the purpose / what capability it unlocks).
3. If the tool is read-only, also add its name to `READ_ONLY_TOOLS` and mention this in the entry.

Do not merge a tool addition without updating `docs/TOOLS.md`. The same applies to renaming or removing a tool — the registry is the single source of truth for what the agent can do and why.
