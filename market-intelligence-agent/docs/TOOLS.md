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
| 9 | `browser_navigate` | read-only | MCP stdio → `@playwright/mcp` | url | Loads a URL in the headless Chromium controlled by the Playwright MCP server. Sets the active page for subsequent snapshot/screenshot calls. | Tavily snippets and yfinance metadata don't return article bodies — the browser lets the agent reach the actual page (paywalled-but-readable, JS-rendered, login-walled). |
| 10 | `browser_snapshot` | read-only | same | (none) | Returns the current page as an accessibility tree — structured text plus element refs like `button [ref=e2]`. | The "extract" capability for the browser. Returns LLM-friendly structured text instead of raw HTML, so the agent can read full article bodies, pricing tables, and earnings transcripts without burning tokens on markup. |
| 11 | `browser_take_screenshot` | read-only | same | filename (optional), fullPage (optional) | Captures a PNG of the current page, written to `data/workspace/screenshots/`. | Visual evidence of what the agent saw. Lets a human reviewer cross-check a brief or email proposal against the actual source before approving it. |
| 12 | `recall_memory` | read-only | LangGraph BaseStore (in-memory v1) | key | Look up a previously-saved user fact by key. Returns the value or "No memory for…". | The read side of cross-thread memory. Lets the agent fetch a fact (email, preference) before a tool call that needs it, without re-asking the user. |
| 13 | `list_memories` | read-only | same | (none) | Return every user fact currently in memory as `"key = value"` strings. | Discovery. The agent uses this to know what's on file before guessing keys — same pattern as `list_directory` for files. |
| 14 | `save_memory` | side-effect | same | key, value | Persist a durable user fact under namespace `("user_facts",)`. Gated by HITL approval. | The write side of cross-thread memory. Without it, the user re-types their email and preferences every session. Gated because "the agent learning new facts about you" is a real side-effect users should consent to. |

`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot", "recall_memory", "list_memories"}` — the allowlist consulted by `approval_node` to skip the HITL interrupt for safe reads.

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

### 9. `browser_navigate`
- **File:** `app/agent/tools/mcp_clients/browser_client.py` (selects from registry)
- **What:** Spawns `@playwright/mcp` as a stdio subprocess (with headless Chromium), navigates the active browser tab to the given URL, returns page metadata.
- **Why:** The agent's reach was bounded by what Tavily snippets and yfinance metadata could surface. With `browser_navigate` it can open the actual Reuters article, the actual investor-relations page, the actual competitor pricing tier — and feed that into the synthesis step instead of guessing from headlines.

### 10. `browser_snapshot`
- **File:** same as `browser_navigate`
- **What:** Returns the current page as an accessibility tree — structured text plus element refs (`button [ref=e2]`, `link [ref=e3]`, etc.). No raw HTML.
- **Why:** This is the "extract text" capability. Accessibility-tree output is LLM-friendly: cheap on tokens, semantically labelled, ignores the markup soup. Pair with `browser_navigate` to do the equivalent of "open page X and read it to me."

### 11. `browser_take_screenshot`
- **File:** same as `browser_navigate`
- **What:** Captures a PNG of the current page. Saves into `data/workspace/screenshots/<filename>` via the server's `--output-dir` flag. Optional `fullPage` argument captures beyond the viewport.
- **Why:** Visual evidence for HITL review. When the agent proposes a `write_file` or `send_email`, attaching a screenshot reference (`see screenshots/acme-2026-05-12.png`) lets the human reviewer cross-check the claim against the source page in one click. Screenshots are bypassed by `READ_ONLY_TOOLS` — they go into a dedicated subfolder so the workspace root stays clean for user-facing briefs.

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

## How to add a new tool

1. **MCP-backed:** add an entry to `_server_config()` in `app/agent/tools/mcp_clients/registry.py`. Create a per-server selector module (or extend an existing one) that filters the registry's tool list by exact name. Native tool: implement under `app/agent/tools/`, wrap with `@tool` if multi-arg.
2. Export the tool symbol from `app/agent/tools/__init__.py` and append it to `TOOLS`.
3. If the tool is read-only (no side effects, idempotent, safe to retry), add its name to `READ_ONLY_TOOLS` so it bypasses the HITL approval gate.
4. **Update this file:** add a row to the summary table and a sub-section under "Per-tool details" explaining *what* it does and *why* it earns a slot. Keep entries short — a few sentences each.
5. If the tool is a new MCP server, also note the binary/package name and any stdio invocation quirks.
