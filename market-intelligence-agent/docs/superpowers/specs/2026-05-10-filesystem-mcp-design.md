# Filesystem MCP — Design

**Date:** 2026-05-10
**Subsystem:** #2 of the agentic-expansion roadmap (`docs/superpowers/specs/2026-05-07-agentic-expansion-roadmap.md`)
**Status:** Draft — pending user approval

## Goal

Give the agent a scoped read-write workspace at `data/workspace/` so the user can drop files for the agent to consume (PDFs converted to text, CSVs, ticker lists) and the agent can persist artifacts (markdown briefs, CSV snapshots, JSON dossiers) that survive the session.

## Decisions captured during brainstorming

| # | Question | Decision |
|---|---|---|
| 1 | Read or write? | **Both** — full read+write workspace. |
| 2 | MCP server vs native LangChain tools? | **MCP server** — official `@modelcontextprotocol/server-filesystem`, run as stdio subprocess. |
| 3 | Sandbox scope? | **Single shared workspace** at `data/workspace/`. No per-thread isolation. |
| 4 | HITL approval on writes? | **All writes gated** through the existing `approval_node`. Reads bypass via `READ_ONLY_TOOLS`. |
| 5 | Which operations to expose? | **Three:** `read_text_file`, `list_directory`, `write_file`. |
| Doc-check | Library to use? | **`langchain-mcp-adapters`** — first-party LangChain wrapper for MCP. Replaces hand-rolled `stdio_client` glue across all three MCP clients. |

## Architecture

The graph topology is unchanged:

```
START → rag → grader → [generate | web_search → generate]
generate → (tool_calls?) → approval → [tools | generate]
```

The new tools plug into `TOOLS` and `READ_ONLY_TOOLS` exactly like the existing five. Routing is unchanged: the existing `approval_node` already handles "any side-effect call → interrupt" with atomic batch semantics, and `filesystem_write_file` falls under that path automatically.

This subsystem also migrates the two existing MCP clients (CRM, Yahoo Finance) onto `langchain-mcp-adapters`. The migration is part of the change — it's smaller than maintaining two divergent implementations and gives us a single registry to extend for subsystems #3 (Playwright) and #5 (Drive).

## Components

**1. `app/agent/tools/mcp_clients/registry.py` (new, ~30 LOC)**

Single `MultiServerMCPClient` configured with all three servers:

| Server name | Command | Args | Transport |
|---|---|---|---|
| `crm` | `uvx` | `["mcp-server-sqlite", "--db-path", "<path-to-customers.db>"]` | stdio |
| `yfinance` | `uvx` | `["yfmcp"]` | stdio |
| `filesystem` | `npx` | `["-y", "@modelcontextprotocol/server-filesystem", "<WORKSPACE_ROOT>"]` | stdio |

(Exact `command`/`args` will match what the existing two clients use today; only the third entry is new.)

Public surface:
- `get_mcp_tools() -> list[BaseTool]` — sync wrapper around `await client.get_tools()`. Called once at module import time.

Tool-name prefixing: `tool_name_prefix=True` so the LLM sees namespaced names (`crm_query`, `yfinance_get_quote`, `filesystem_read_text_file`, etc.). This avoids any future collision when more servers join.

**2. `app/agent/tools/mcp_clients/mcp_client.py` (rewrite)**

Reduces to a thin module that selects the CRM tools out of the registry's full list and re-exports them under the public name(s) the rest of the codebase already imports (`crm_tool`). Hand-rolled `stdio_client`/`ClientSession` glue removed.

**3. `app/agent/tools/mcp_clients/yfinance_client.py` (rewrite)**

Same pattern as `mcp_client.py`. Selects `yf_quote_tool`, `yf_history_tool`, `yf_news_tool` out of the registry. `_sync_call` and `StructuredTool.from_function` glue removed — the adapter handles schema conversion automatically.

**4. `app/agent/tools/mcp_clients/filesystem_client.py` (new, ~20 LOC)**

Selects the three filesystem tools out of the registry (filtering by name from the ~10 the server exposes) and re-exports as `fs_read_file_tool`, `fs_list_dir_tool`, `fs_write_file_tool`.

**5. `app/agent/tools/__init__.py` (modify)**

- Append the three new tools to `TOOLS`.
- Add the read-only filesystem tool names to `READ_ONLY_TOOLS`. Update existing entries if the prefix-rename changes their names.

## Supporting changes

- `app/core/config.py` — add `WORKSPACE_ROOT: Path = Path("data/workspace")` and `FILESYSTEM_TIMEOUT_S: int = 10`.
- `app/agent/prompts/system.py` — short paragraph (English) telling the agent the workspace exists, that user-supplied files appear there, and that it can save briefs there. Suggest discovery via `filesystem_list_directory(".")`.
- `data/workspace/.gitkeep` — ensures the directory exists in fresh clones.
- `.gitignore` — ignore everything inside `data/workspace/` except `.gitkeep`.
- `Dockerfile` — install Node + `npx` in the API image; pre-pull `@modelcontextprotocol/server-filesystem` at build time so first request isn't a 30s install.
- `docker-compose.yml` — bind-mount `./data/workspace:/app/data/workspace` so artifacts survive container restarts.
- `pyproject.toml` — add `langchain-mcp-adapters` dependency. No new transitive Python deps beyond what it pulls in.

## Data flow

### Startup (process lifecycle)

1. `app/api/server.py` lifespan starts → `compile_graph()` → `bind_tools(TOOLS)`.
2. `app/agent/tools/__init__.py` calls `registry.get_mcp_tools()` once at module import.
3. `registry.py` instantiates `MultiServerMCPClient` with the three server entries and runs `await client.get_tools()` via a sync bridge. Returns the full list of LangChain `BaseTool` objects.
4. Each MCP client module (`mcp_client.py`, `yfinance_client.py`, `filesystem_client.py`) filters that list by name and re-exports the public tool symbols.
5. `__init__.py` builds `TOOLS = [send_email_tool, *crm_tools, *yfinance_tools, *filesystem_tools]` and the matching `READ_ONLY_TOOLS` allowlist.

The MCP server subprocesses are not yet running. `MultiServerMCPClient` is lazy — subprocesses spawn per call.

### Per-call lifecycle (write path — agent saves a brief)

1. `generate` returns an AIMessage with `tool_calls=[{"name": "filesystem_write_file", "args": {"path": "brief.md", "content": "..."}}]`.
2. `approval` node sees a non-`READ_ONLY_TOOLS` call, calls `interrupt(requests)`, graph pauses.
3. `/chat` returns `status="interrupted"` with the pending tool call. Streamlit renders Approve/Refuse.
4. User clicks Approve → `/approve` resumes via `Command(resume=[{"type": "approve"}])`.
5. `ToolNode` invokes the LangChain tool. The adapter opens a stdio session to the filesystem server, calls `write_file`, returns the result. Subprocess closes.
6. The result becomes a `ToolMessage`, fed back to `generate`, which produces the final response.

### Per-call lifecycle (read path — agent consumes a dropped file)

1. AIMessage `tool_calls=[{"name": "filesystem_read_text_file", "args": {"path": "tickers.csv"}}]`.
2. `approval` node: name is in `READ_ONLY_TOOLS` → returns immediately, no interrupt.
3. `ToolNode` runs the tool via the adapter. Result returns to `generate`.

### Sandboxing

The only allowed root passed to `@modelcontextprotocol/server-filesystem` is the absolute path to `data/workspace/`. Any path the LLM proposes is resolved relative to that root by the server; anything outside (`../`, `/etc/passwd`, etc.) is rejected by the server before reaching our code. We do not add a second sandboxing layer.

### Persistence

`data/workspace/` is bind-mounted in Docker, so artifacts survive container restarts the same way `checkpoints.db` does today.

## Error handling & edge cases

**Server-spawn failures (startup).** If `npx` is missing or the package fails to fetch, the adapter raises on first `get_tools()`. We let it propagate — startup should fail loud, not silently ship without filesystem tools. Mitigation: bake `npx`/Node into the API Docker image and pre-pull the package at build time.

**Per-call MCP errors.** Subprocess crash, timeout, JSON-RPC error. The adapter surfaces these as exceptions from `ainvoke()`. `ToolNode` catches them and converts to a `ToolMessage` with the error text — same UX as today. The agent decides whether to retry or report.

**Path errors (server-side).** Access denied (path outside root) and `ENOENT` are returned by the server as plain error text in the tool result; the agent reads them like any other tool output. No special handling on our side.

**Concurrent access.** Last-write-wins; partial reads possible during writes. Acceptable for the portfolio scope.

**Large files.** Bounded by the LLM's context window. Documented as a limitation in `docs/TOOLS.md`; no truncation layer added.

**Binary files.** Not in this iteration. `read_text_file` is UTF-8; PDFs/images return errors. Documented limitation; the existing Pinecone ingest pipeline still covers PDFs.

**HITL rejection.** Reject `filesystem_write_file` → existing atomic-batch rule kicks in. `ToolMessage("Action cancelled by user.")`, file untouched. No new code path.

**Workspace doesn't exist on first run.** `data/workspace/.gitkeep` covers fresh clones; Docker volume mount creates it on the host. Belt-and-suspenders: a one-line `WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)` at app startup before the registry is built.

**Existing two MCP clients during the migration.** The two clients are rewritten in the same change. Risk: regressing existing tool behavior. Safety net: `uv run pytest tests/ -v` must keep the current pass count after the migration, otherwise we don't merge.

## Documentation deliverables (in the same change)

- **`docs/TOOLS.md`** — three new entries for `filesystem_read_text_file`, `filesystem_list_directory`, `filesystem_write_file`, each with the standard *What* + *Why*. Per the project rule established in `CLAUDE.md`.
- **`CLAUDE.md`** — update the tools table, mention the new `mcp_clients/registry.py`, note the migration to `langchain-mcp-adapters` and the new namespaced tool names if any existing names change.
- **`README.md`** — one short paragraph on the workspace folder and how to drop files into it.
- **`app/agent/prompts/system.py`** — workspace-awareness paragraph (English).
