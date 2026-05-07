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

# Smoke-test the agent (no HITL, streams through all graph nodes)
uv run python test_agent.py

# Interactive HITL test in the terminal (approve/refuse each tool call manually)
uv run python test_hitl_agent.py

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

The email tool falls back to a simulation (no real send) when `EMAIL_SENDER` still contains `"ton_email"`.

## Architecture

### LangGraph state graph (`app/agent/graph.py`)

The graph is a cyclic DAG compiled with `interrupt_before=["tools"]` and an in-memory `MemorySaver` checkpointer. The flow is:

```
rag → grader → [generate | web_search] → generate → tools → generate → …
```

- **rag**: pulls top-3 chunks from Pinecone via semantic similarity.
- **grader**: binary LLM filter — drops chunks that don't answer the question.
- **grader → generate** if any chunks passed, **grader → web_search** if none.
- **web_search**: Tavily advanced search, max 3 results; always feeds into generate.
- **generate**: GPT-4o-mini with both tools bound. Decides whether to call a tool or emit a final answer. Also handles `ToolMessage` errors gracefully before looping back.
- **tools** (LangGraph `ToolNode`): executes whichever tool the LLM called. The graph **pauses here** waiting for human approval before this node runs.

### Tools

| Tool name | File | What it does |
|---|---|---|
| `send_email` | `app/agent/tools/emails.py` | SMTP send via Gmail. Simulates if credentials are placeholder. |
| `crm_query` | `app/agent/tools/mcp_clients/mcp_client.py` | Launches `mcp-server-sqlite` as a subprocess over stdio, calls its `read_query` tool, returns the raw text result. Wraps async MCP client in a sync shim for LangChain. |

### Human-in-the-Loop (HITL) flow

1. `POST /chat` — runs the graph until it hits `interrupt_before=["tools"]`, returns `status: "interrupted"` with a description of the pending tool call.
2. `POST /approve` — if `approved: true`, resumes by calling `agent_app.invoke(None, config)`; if false, cancels.
3. The graph can chain multiple interruptions (e.g. CRM query → email) within a single `thread_id` session.
4. Session state lives only in-process memory; restarting the server loses all pending sessions.

### API models (`app/api/models/Models.py`)

- `ChatRequest`: `query: str`, `thread_id: str = "default_thread"`
- `ChatResponse`: `response: str`, `status: "completed"|"interrupted"`, `next_step: str|None`
- `ApproveRequest`: `thread_id: str`, `approved: bool`

### Data ingestion (`app/ingest.py`)

Reads all PDFs from `./data/`, splits at 1000 chars / 200 overlap, embeds with `text-embedding-3-small`, and upserts into Pinecone. Run once per document set. The Pinecone index must already exist.
