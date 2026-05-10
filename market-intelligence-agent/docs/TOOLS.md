# Tools Registry

This file lists every tool exposed to the agent (native LangChain tools and MCP-backed tools), with a brief explanation of what each does and why it exists in this project.

**Rule:** every time a new tool (native or MCP) is added to `TOOLS` in `app/agent/tools/__init__.py`, append an entry to the table below and add a short *Why* paragraph in the "Per-tool details" section. Keep `READ_ONLY_TOOLS` in sync.

All MCP-backed tools are loaded through a single `MultiServerMCPClient` registered in `app/agent/tools/mcp_clients/registry.py`. Tool names come straight from the upstream MCP servers (no controller-side prefix). yfmcp self-namespaces (`yfinance_*`); the filesystem server uses unambiguous names (`read_text_file`, etc.); the CRM server's `read_query` is the one bare name.

## Summary table

| # | Name | Type | Backend | Args | What it does | Why we have it |
|---|---|---|---|---|---|---|
| 1 | `send_email` | side-effect | SMTP/Gmail (native) | recipient, subject, body | Sends an email from the configured sender account; falls back to a console simulation when credentials are placeholder. | Lets the agent take a real-world action (notify a human, deliver a brief) — primary motivation for the HITL approval gate. |
| 2 | `read_query` | read-only | MCP stdio → `mcp-server-sqlite` | sql (single string) | Runs a `read_query` against the local `customers.db` via the SQLite MCP server. | Demonstrates the MCP stdio pattern with a structured-DB tool and gives the agent customer/CRM context to ground its analysis. |
| 3 | `yfinance_get_ticker_info` | read-only | MCP stdio → `yfmcp` | ticker | Returns the latest quote (price, change, volume, day stats) for a given ticker. | Live market price is the most-asked datapoint for a market-intelligence agent; cheap real-time signal. |
| 4 | `yfinance_get_price_history` | read-only | MCP stdio → `yfmcp` | ticker, period (default `"1mo"`) | Returns historical OHLCV bars for a ticker over the requested period. | Enables trend / momentum reasoning that a single quote can't support. |
| 5 | `yfinance_get_ticker_news` | read-only | MCP stdio → `yfmcp` | ticker, limit (default `5`) | Returns the most recent headlines associated with a ticker. | Pairs price action with narrative; lets the agent explain *why* a ticker moved. |
| 6 | `read_text_file` | read-only | MCP stdio → `@modelcontextprotocol/server-filesystem` | path | Reads a UTF-8 text file from the sandboxed workspace at `data/workspace/`. | Lets the user drop a file (CSV of tickers, briefing notes) into the workspace and have the agent consume it without re-running the Pinecone ingest pipeline. |
| 7 | `list_directory` | read-only | same | path (default `"."`) | Lists files and folders inside a workspace path. | Discovery: the agent uses this to find out what the user has dropped before reading. |
| 8 | `write_file` | side-effect | same | path, content | Writes a UTF-8 text file into the sandboxed workspace. Gated by HITL approval. | Lets the agent persist briefs, CSV snapshots, or JSON dossiers as durable artifacts that survive the session. |

`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory"}` — the allowlist consulted by `approval_node` to skip the HITL interrupt for safe reads.

## Per-tool details

### 1. `send_email`
- **File:** `app/agent/tools/emails.py`
- **What:** SMTP send via Gmail (587, STARTTLS). If `EMAIL_SENDER` still contains the placeholder `"ton_email"`, the tool prints to stdout and returns success without sending — useful for portfolio demos.
- **Why:** It is the only native side-effect tool currently shipped. It exists to exercise the human-in-the-loop approval flow end-to-end: the LLM proposes a recipient/subject/body, the graph hits `interrupt()`, the user approves or rejects in the Streamlit UI, and only then does `ToolNode` execute the send.

### 2. `read_query`
- **File:** `app/agent/tools/mcp_clients/mcp_client.py` (selects from registry)
- **What:** Spawns `mcp-server-sqlite` as a stdio subprocess scoped to `customers.db`, sends a `read_query` with the LLM-supplied SQL, returns rows.
- **Why:** Demonstrates structured-data retrieval over MCP and gives the agent a private dataset (customers, deals, regions) to combine with public market data. Read-only by construction — `mcp-server-sqlite`'s `read_query` rejects writes.

### 3. `yfinance_get_ticker_info`
- **File:** `app/agent/tools/mcp_clients/yfinance_client.py` (selects from registry)
- **What:** Spawns `yfmcp` as a stdio subprocess and calls `get_ticker_info(ticker)`. Returns price, change, volume, day stats.
- **Why:** Most market questions start with "what's it trading at right now?" This is the cheapest, lowest-latency signal the agent can reach for.

### 4. `yfinance_get_price_history`
- **File:** same as `yfinance_get_ticker_info`
- **What:** Calls `get_price_history(ticker, period)`; default period `"1mo"`. Returns OHLCV bars.
- **Why:** Single-point quotes don't support trend reasoning. With history the agent can answer "is NVDA breaking out?" or "how did TSM perform last quarter?".

### 5. `yfinance_get_ticker_news`
- **File:** same as `yfinance_get_ticker_info`
- **What:** Calls `get_ticker_news(ticker, limit)`; default limit `5`. Returns recent headlines.
- **Why:** Price moves without context are noise. News headlines provide the narrative thread the synthesis step needs.

### 6. `read_text_file`
- **File:** `app/agent/tools/mcp_clients/filesystem_client.py` (selects from registry)
- **What:** Reads a UTF-8 text file from `data/workspace/<path>` via `@modelcontextprotocol/server-filesystem`. Paths outside the workspace root are rejected by the server.
- **Why:** The input channel of the workspace. Drop a CSV of tickers, a competitor list, or a briefing note into `data/workspace/` and the agent can consume it without going through the Pinecone ingest pipeline.

### 7. `list_directory`
- **File:** same as `read_text_file`
- **What:** Lists entries in a workspace path; defaults to the workspace root.
- **Why:** Discovery. The agent uses this to find out what files exist before reading. Without it, the LLM would have to guess paths.

### 8. `write_file`
- **File:** same as `read_text_file`
- **What:** Writes UTF-8 content to `data/workspace/<path>`. Creates parent directories if missing. Last-write-wins.
- **Why:** The output channel of the workspace. The agent's synthesis usually lives only in the message history; this lets it persist briefs and snapshots that survive the session. Gated by `approval_node` — the user sees the path and content in the Streamlit Approve/Refuse modal before any disk write.

## How to add a new tool

1. **MCP-backed:** add an entry to `_server_config()` in `app/agent/tools/mcp_clients/registry.py`. Create a per-server selector module (or extend an existing one) that filters the registry's tool list by exact name. Native tool: implement under `app/agent/tools/`, wrap with `@tool` if multi-arg.
2. Export the tool symbol from `app/agent/tools/__init__.py` and append it to `TOOLS`.
3. If the tool is read-only (no side effects, idempotent, safe to retry), add its name to `READ_ONLY_TOOLS` so it bypasses the HITL approval gate.
4. **Update this file:** add a row to the summary table and a sub-section under "Per-tool details" explaining *what* it does and *why* it earns a slot. Keep entries short — a few sentences each.
5. If the tool is a new MCP server, also note the binary/package name and any stdio invocation quirks.
