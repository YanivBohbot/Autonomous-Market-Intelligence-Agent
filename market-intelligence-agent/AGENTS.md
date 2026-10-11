# Repository Guidelines

This document gives coding agents the project context and working rules needed to contribute safely. This repository is a full-stack market-intelligence system: a FastAPI/LangGraph backend that researches financial questions, uses MCP tools and RAG, and gates side effects behind human approval. It has a React/Vite operations console.

## Commands

Run Python commands from `market-intelligence-agent/` with `uv run`:

```bash
uv sync
uv run python create_db.py
uv run python -m app.ingest
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload
uv run python test_agent.py
uv run pytest tests/ -v
uv run python app/agent/tools/mcp_clients/mcp_client.py
```

`create_db.py` rebuilds the committed wealth-management SQLite database, `customers.db`. `app.ingest` reads PDFs in `data/`, embeds them in Pinecone, and rewrites `app/agent/tools/kb_documents.json`; commit that manifest whenever ingesting content. Install the local browser once with `npx -y @playwright/mcp@latest install-browser chrome-for-testing`.

For the React console, run `npm install` once in `frontend/`, then use `npm run dev` (port 5173, proxying API requests to port 8000), `npm test`, and `npm run build`.

## Dependencies and Configuration

`uv.lock` is authoritative. The AgentCore production image pins the LangChain/LangGraph family in `requirements.agentcore.txt` to the exact locked versions. Upgrade in this order: `uv lock --upgrade-package <package>`, `uv sync`, run tests, then update `requirements.agentcore.txt`.

`app/core/config.py` validates configuration at import time. Required `.env` values are:

```
OPENAI_API_KEY, OPENAI_MODEL, OPENAI_EMBEDDING_MODEL
PINECONE_API_KEY, PINECONE_INDEX_NAME, TAVILY_API_KEY
EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT
```

Important optional settings include `LOG_LEVEL`, `API_URL`, `YFINANCE_TIMEOUT_S`, `WORKSPACE_ROOT`, `BROWSER_BACKEND`, `BROWSER_TOOL_ID`, `BROWSER_IDLE_TTL_S`, `COPILOT_ENABLED`, and `ANTHROPIC_API_KEY`. Do not commit `.env` files or credentials. Email simulates when the sender is a placeholder or no real Amazon SES identity is configured.

## Project Layout

- `app/api/`: FastAPI server, request models, and routers.
- `app/agent/`: multi-agent LangGraph graph (supervisor + specialists), prompts, guardrails, memory, and tools.
- `app/voice/`: GPT-Live delegation worker, shared voice graph, and HITL handling.
- `app/data_import/`: deterministic, non-agentic SQLite/PDF import logic.
- `frontend/src/`: React console features such as Desk, Clients, Data, Reports, and Briefing.
- `tests/unit/`: pytest suite. Frontend Vitest tests are colocated with components.
- `docs/`: project documentation; `docs/TOOLS.md` is the tool catalog.

## Runtime Architecture

FastAPI compiles one multi-agent graph with the configured checkpointer and store. That same object is assigned to `app.state.agent_app` and wrapped by `app.state.market_desk_agent`; `/stream`, `/approve`, AgentCore `/invocations`, and opt-in `/copilot/market-desk` therefore share checkpoints and conversation state. The graph routes `load_client_context -> record_question -> input_guard -> supervisor -> specialist -> supervisor -> END` (`input_guard` blocks credit-card numbers before any LLM call) across RAG, finance, portfolio, browser, email, filesystem, and memory specialists.

Side effects use `HumanInTheLoopMiddleware`. Legacy boolean approval is expanded into `Command(resume={"decisions": [...]})`, with one `approve` or `reject` decision per pending action. Nested specialist state must be inspected with `subgraphs=True` before describing or resuming an interrupt.

The former single-agent graph (`app/agent/graph.py` and `app/agent/nodes/`) was removed on 2026-10-12; the multi-agent graph is the only graph.

## Tools and Safety Rules

`app/agent/tools/__init__.py` is the tool registry. MCP-backed tools are created once through `MultiServerMCPClient` in `app/agent/tools/mcp_clients/registry.py` and re-exported by the server-specific modules.

- CRM: `read_query`, `list_tables`, and `describe_table` access the SQLite wealth database.
- Financial analysis: `portfolio_metrics`, `pct_change`, `concentration_screen`, and `yfinance_*` read market and portfolio data.
- Knowledge: `search_knowledge_base` queries Pinecone; `web_search` uses Tavily.
- Files: `read_text_file` and `list_directory` are read-only; `write_file` is approval-gated inside `data/workspace/`.
- Browser: navigate, snapshot, and screenshot run against a persistent local Playwright session; screenshots are stored in `data/workspace/screenshots/`.
- Memory: `recall_memory` and `list_memories` read; `save_memory` is approval-gated.
- Email: `send_email` uses Amazon SES and is approval-gated. The recipient guard permits only addresses present in `clients.email`.

When adding, renaming, or removing a tool, update `TOOLS` and `READ_ONLY_TOOLS` together as applicable, and update `docs/TOOLS.md` in the same change. Each catalog entry needs its name, type, backend, arguments, purpose, and a short rationale. Never merge a registry change without this documentation.

## Multi-Agent Mode

`app/agent/multi_agent/` is the primary text runtime used by `/stream`, `/approve`, AgentCore, and Market Desk. `COPILOT_ENABLED=true` only exposes the AG-UI `/copilot/market-desk` wrapper; it does not change which graph the other text transports use.

Shared middleware lives in `app/agent/middleware.py`: sensitive-data checks, date prompting, message summarization, credit-card masking, call limits, optional Anthropic fallback, model retry, and tool-error conversion. Multi-agent HITL supports one `approve`, `reject`, or `edit` decision per pending call.

## API and Voice

Key routers are `health.py` (`/health`, AgentCore `/ping` and `/invocations`), `stream.py`, `approve.py`, `copilot.py`, `gptlive_session.py`, and `data.py`. The `/data/*` import and client endpoints are deterministic SQLite operations: they do not call an LLM and are not part of either agent graph.

OpenAI GPT-Live uses browser-to-OpenAI WebRTC with a FastAPI sideband worker. React `/research` voice runs on the same `app.state.agent_app`, thread/checkpoint, activity rail, and visual HITL cards as typed Research; text entry is locked while its continuous voice session is active. `GET /voice/{thread_id}/state` and `POST /voice/{thread_id}/decision` are Research-only. Research voice shows a live caption, then committed turns, in the chat (see `docs/superpowers/specs/2026-10-11-research-voice-chat-transcript-design.md`). See `docs/VOICE.md` before changing voice or Hebrew support.

## Development and Test Conventions

Use Python 3.12+, four-space indentation, `snake_case` for Python symbols, and `PascalCase` for classes. Follow existing async FastAPI and LangGraph patterns. Frontend code is TypeScript with two-space indentation and `PascalCase` React component filenames. No repository-wide formatter or linter is configured; match the surrounding file.

Write backend tests as `tests/unit/test_<feature>.py` with `test_<behavior>` functions. Mock network, model, MCP, and persistence boundaries. Frontend tests use Vitest and Testing Library, colocated as `<Component>.test.tsx` or `<module>.test.ts`. Run the focused tests you changed plus the applicable complete suite before handoff.

Use concise Conventional Commit subjects such as `feat(briefing): add BriefingPage` or `fix(api): handle empty results`. Pull requests should describe behavior, list verification commands, link a relevant issue or design document, and include screenshots for UI work. Specs belong in `docs/superpowers/specs/`; implementation plans belong in `docs/superpowers/plans/`.

## Agent Workflow

Before developing any change in this repository, invoke the applicable Superpowers skills and follow their gates. Broad or architectural work requires an approved design, a written spec, and an approved implementation plan before product code is edited. Bounded work follows the lighter workflow only when the selected Superpowers skill explicitly permits it. Use test-driven development where applicable and run the relevant focused and complete test suites before handoff. After completing a task, start or restart the project so the user can test it locally.
