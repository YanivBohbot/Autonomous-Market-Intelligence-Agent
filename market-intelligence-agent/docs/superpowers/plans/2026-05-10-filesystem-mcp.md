# Filesystem MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent a scoped read-write workspace at `data/workspace/` exposed via the official `@modelcontextprotocol/server-filesystem` MCP server, and migrate all three MCP clients (CRM, Yahoo Finance, Filesystem) onto `langchain-mcp-adapters`.

**Architecture:** A single `MultiServerMCPClient` registers all three stdio MCP servers and produces LangChain `BaseTool` objects. Per-server modules filter and re-export the public tools. The graph topology is unchanged; the existing `approval_node` continues to gate side-effect tools via `READ_ONLY_TOOLS`.

**Tech Stack:** Python 3.12, `langchain-mcp-adapters` (new), `langgraph`, `mcp`, `pydantic-settings`. Filesystem MCP server is Node-based (`npx`), the other two are Python-based (`uv run`).

**Source spec:** `docs/superpowers/specs/2026-05-10-filesystem-mcp-design.md`

**User preferences carried in:**
- Tests are deferred. Each task ends with the **regression gate** (`uv run pytest tests/ -v`) which must keep the current count of **18 passed, 1 failed** (`test_health_returns_ok` is the pre-existing fail and is unrelated). No new tests are added.
- Prompts and user-facing strings in English.
- Atomic-batch HITL semantics preserved (no changes to `approval_node`).
- Multi-arg LangChain tools must use `StructuredTool.from_function`, not legacy `Tool`. The adapter handles this automatically; we don't reach for it directly.
- Every tool added to `TOOLS` gets an entry in `docs/TOOLS.md` (project rule in `CLAUDE.md`).

**File structure (target):**

```
market-intelligence-agent/
├── app/
│   ├── agent/
│   │   ├── prompts/system.py             # MODIFY — add workspace paragraph, update tool names
│   │   └── tools/
│   │       ├── __init__.py               # MODIFY — wire 3 new tools, refresh READ_ONLY_TOOLS
│   │       └── mcp_clients/
│   │           ├── registry.py           # CREATE — MultiServerMCPClient, sync get_mcp_tools()
│   │           ├── mcp_client.py         # REWRITE — selects CRM tools from registry
│   │           ├── yfinance_client.py    # REWRITE — selects yfinance tools from registry
│   │           └── filesystem_client.py  # CREATE — selects 3 filesystem tools from registry
│   └── core/config.py                    # MODIFY — WORKSPACE_ROOT, FILESYSTEM_TIMEOUT_S
├── data/workspace/.gitkeep               # CREATE
├── docs/TOOLS.md                         # MODIFY — append 3 entries
├── CLAUDE.md                             # MODIFY — refresh tools table
├── README.md                             # MODIFY — workspace paragraph
├── Dockerfile                            # MODIFY — install Node + npx, pre-pull filesystem MCP
├── .gitignore                            # MODIFY — keep workspace/.gitkeep, ignore the rest
└── pyproject.toml                        # MODIFY — add langchain-mcp-adapters
```

`docker-compose.yml` already mounts `./data:/app/data`, so `data/workspace/` is automatically persisted in containers without any compose changes.

**Tool-name namespacing decision:** the registry uses `tool_name_prefix=True`, which produces names of the form `<server_name>_<mcp_tool_name>`. Final tool names exposed to the LLM:

| Old name | New name | Read-only? |
|---|---|---|
| `crm_query` | `crm_read_query` | yes |
| `yf_quote` | `yfinance_get_quote` | yes |
| `yf_history` | `yfinance_get_history` | yes |
| `yf_news` | `yfinance_get_news` | yes |
| (new) | `filesystem_read_text_file` | yes |
| (new) | `filesystem_list_directory` | yes |
| (new) | `filesystem_write_file` | **no — gated** |
| `send_email` | `send_email` (unchanged — native tool) | no — gated |

`READ_ONLY_TOOLS` is updated to the new names. The system prompt is updated to reference the new names.

---

## Task 1: Add dependency, workspace plumbing, and config

**Files:**
- Modify: `market-intelligence-agent/pyproject.toml`
- Modify: `market-intelligence-agent/app/core/config.py`
- Modify: `market-intelligence-agent/.gitignore`
- Create: `market-intelligence-agent/data/workspace/.gitkeep`

- [ ] **Step 1: Add the `langchain-mcp-adapters` dependency to `pyproject.toml`**

In `market-intelligence-agent/pyproject.toml`, the `dependencies` array currently ends with `"yfmcp>=0.11.1",`. Add one line, keeping alphabetical order:

```toml
    "langchain-mcp-adapters>=0.1.0",
```

The full block, after edit:

```toml
dependencies = [
    "emails>=0.6",
    "fastapi>=0.135.0",
    "langchain>=1.0.8",
    "langchain-community>=0.4.1",
    "langchain-mcp-adapters>=0.1.0",
    "langchain-openai>=1.0.3",
    "langchain-pinecone>=0.2.13",
    "langgraph>=1.0.3",
    "langgraph-checkpoint-sqlite>=3.0.3",
    "mcp>=1.22.0",
    "mcp-server-sqlite>=2025.4.25",
    "pinecone>=7.3.0",
    "pydantic>=2.12.4",
    "pydantic-settings>=2.12.0",
    "pypdf>=6.3.0",
    "python-dotenv>=1.2.1",
    "streamlit>=1.51.0",
    "tavily-python>=0.7.13",
    "tiktoken>=0.12.0",
    "uvicorn>=0.38.0",
    "yfmcp>=0.11.1",
]
```

- [ ] **Step 2: Lock the new dependency**

Run: `uv lock`
Expected output: contains `Resolved N packages` with `langchain-mcp-adapters` showing as added. No errors.

- [ ] **Step 3: Add `WORKSPACE_ROOT` and `FILESYSTEM_TIMEOUT_S` to `app/core/config.py`**

Open `app/core/config.py`. Locate the `Settings` class. Right after the line `YFINANCE_TIMEOUT_S: int = 10` add:

```python
    WORKSPACE_ROOT: Path = Path("data/workspace")
    FILESYSTEM_TIMEOUT_S: int = 10
```

`Path` is already imported at the top of the file. Final relevant section:

```python
class Settings(BaseSettings):
    OPENAI_API_KEY: str
    OPENAI_MODEL: str
    OPENAI_EMBEDDING_MODEL: str
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str
    TAVILY_API_KEY: str
    EMAIL_SENDER: str
    EMAIL_PASSWORD: str
    EMAIL_SMTP_SERVER: str
    EMAIL_SMTP_PORT: int
    LOG_LEVEL: str = "INFO"
    CHECKPOINT_DB_PATH: str = "data/checkpoints.db"
    API_URL: str = "http://127.0.0.1:8000"
    YFINANCE_TIMEOUT_S: int = 10
    WORKSPACE_ROOT: Path = Path("data/workspace")
    FILESYSTEM_TIMEOUT_S: int = 10

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

- [ ] **Step 4: Create `data/workspace/.gitkeep`**

The file is empty. From the project root:

```bash
mkdir -p market-intelligence-agent/data/workspace
touch market-intelligence-agent/data/workspace/.gitkeep
```

- [ ] **Step 5: Update `.gitignore` to keep `.gitkeep` but ignore everything else in the workspace**

Open `market-intelligence-agent/.gitignore`. After the existing block:

```
# LangGraph SQLite checkpointer runtime files
data/checkpoints.db
data/checkpoints.db-shm
data/checkpoints.db-wal
```

append:

```
# Agent workspace — keep the folder, ignore its contents
data/workspace/*
!data/workspace/.gitkeep
```

- [ ] **Step 6: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed** (`test_health_returns_ok`). No new failures.

- [ ] **Step 7: Commit**

```bash
git add market-intelligence-agent/pyproject.toml \
        market-intelligence-agent/uv.lock \
        market-intelligence-agent/app/core/config.py \
        market-intelligence-agent/.gitignore \
        market-intelligence-agent/data/workspace/.gitkeep
git commit -m "feat(filesystem-mcp): add langchain-mcp-adapters dep, WORKSPACE_ROOT config, workspace dir"
```

---

## Task 2: Update `Dockerfile` to install Node + npx and pre-pull the filesystem MCP server

**Files:**
- Modify: `market-intelligence-agent/Dockerfile`

- [ ] **Step 1: Replace the Dockerfile**

Open `market-intelligence-agent/Dockerfile`. Replace the entire file with:

```dockerfile
FROM python:3.12-slim

# Install Node.js + npm (provides npx) for MCP servers that ship as Node packages
# (e.g. @modelcontextprotocol/server-filesystem).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /usr/local/bin/uv

WORKDIR /app

COPY . .

RUN uv sync --frozen --no-dev

# Pre-pull the filesystem MCP server so the first request doesn't pay an npm install.
RUN npx -y @modelcontextprotocol/server-filesystem --help >/dev/null 2>&1 || true

EXPOSE 8000 8080

CMD ["uv", "run", "uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Run the regression gate (no Docker rebuild yet — code-only)**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. Dockerfile changes don't affect pytest.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/Dockerfile
git commit -m "feat(filesystem-mcp): install Node and pre-pull filesystem MCP server in API image"
```

---

## Task 3: Create `mcp_clients/registry.py` (CRM + yfinance only for now)

**Files:**
- Create: `market-intelligence-agent/app/agent/tools/mcp_clients/registry.py`

The registry module is the single source of MCP-backed LangChain tools. We register filesystem in **Task 6** so each commit boundary leaves the regression gate green.

- [ ] **Step 1: Create `registry.py`**

Create `market-intelligence-agent/app/agent/tools/mcp_clients/registry.py` with:

```python
"""MCP client registry — single MultiServerMCPClient for every stdio MCP server.

Exposes `get_mcp_tools()`, a sync function that returns the full list of LangChain
BaseTool objects produced by the registered MCP servers. Per-server modules
(`mcp_client.py`, `yfinance_client.py`, `filesystem_client.py`) filter this list
by name to re-export their public tool symbols.

Tool names are namespaced as `<server_name>_<tool_name>` via tool_name_prefix=True.
"""

from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


def _server_config() -> dict:
    """Build the MultiServerMCPClient server config. Centralised so adding a server
    means changing one dict, not three import sites."""
    return {
        "crm": {
            "command": "uv",
            "args": ["run", "mcp-server-sqlite", "--db-path", "customers.db"],
            "transport": "stdio",
            "env": dict(os.environ),
        },
        "yfinance": {
            "command": "uv",
            "args": ["run", "yfmcp"],
            "transport": "stdio",
            "env": dict(os.environ),
        },
    }


async def _load_tools() -> list[BaseTool]:
    client = MultiServerMCPClient(_server_config(), tool_name_prefix=True)
    tools = await client.get_tools()
    logger.info("MCP registry loaded %d tools: %s", len(tools), [t.name for t in tools])
    return tools


def _run_async(coro):
    """Sync bridge that works whether or not an event loop is already running."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


@lru_cache(maxsize=1)
def get_mcp_tools() -> list[BaseTool]:
    """Return all MCP-backed LangChain tools. Cached after first call."""
    return _run_async(_load_tools())
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. The registry isn't imported anywhere yet, so pytest is unaffected.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/mcp_clients/registry.py
git commit -m "feat(filesystem-mcp): add MCP registry using MultiServerMCPClient"
```

---

## Task 4: Migrate `mcp_client.py` to use the registry

**Files:**
- Modify: `market-intelligence-agent/app/agent/tools/mcp_clients/mcp_client.py`

The new MCP tool name will be `crm_read_query` (server `crm` + tool `read_query`). The public symbol `crm_tool` is preserved so `app/agent/tools/__init__.py` doesn't need to change names.

- [ ] **Step 1: Replace `mcp_client.py`**

Replace the entire contents of `market-intelligence-agent/app/agent/tools/mcp_clients/mcp_client.py` with:

```python
"""CRM MCP client — selects CRM-server tools out of the shared registry.

Public surface preserved: `crm_tool` is the single LangChain BaseTool for SQL reads
against the customer database. Schema and routing are unchanged; only the underlying
transport moved to langchain-mcp-adapters.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.registry import get_mcp_tools

logger = logging.getLogger(__name__)

CRM_TOOL_NAME = "crm_read_query"


def _select_crm_tool() -> BaseTool:
    for tool in get_mcp_tools():
        if tool.name == CRM_TOOL_NAME:
            return tool
    raise RuntimeError(
        f"CRM MCP tool {CRM_TOOL_NAME!r} not found in registry; check server config."
    )


crm_tool: BaseTool = _select_crm_tool()
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. If a test imports the old `query_crm_tool` or `sync_query_wrapper` symbols, fix that test by updating it to use `crm_tool.invoke(...)` directly. Recount must match before commit.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/mcp_clients/mcp_client.py
git commit -m "refactor(mcp): migrate CRM client to MultiServerMCPClient"
```

---

## Task 5: Migrate `yfinance_client.py` to use the registry

**Files:**
- Modify: `market-intelligence-agent/app/agent/tools/mcp_clients/yfinance_client.py`

New names: `yfinance_get_quote`, `yfinance_get_history`, `yfinance_get_news`. Public symbols preserved as `yf_quote_tool`, `yf_history_tool`, `yf_news_tool` so `__init__.py` re-exports don't need to change.

- [ ] **Step 1: Replace `yfinance_client.py`**

Replace the entire contents of `market-intelligence-agent/app/agent/tools/mcp_clients/yfinance_client.py` with:

```python
"""Yahoo Finance MCP client — selects yfinance-server tools out of the shared registry.

Public symbols preserved: `yf_quote_tool`, `yf_history_tool`, `yf_news_tool`. Schema
conversion (single-arg vs multi-arg) is now handled automatically by
langchain-mcp-adapters; the legacy Tool / StructuredTool decisions are gone.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.registry import get_mcp_tools

logger = logging.getLogger(__name__)

QUOTE_TOOL_NAME = "yfinance_get_quote"
HISTORY_TOOL_NAME = "yfinance_get_history"
NEWS_TOOL_NAME = "yfinance_get_news"


def _select(name: str) -> BaseTool:
    for tool in get_mcp_tools():
        if tool.name == name:
            return tool
    raise RuntimeError(
        f"Yahoo Finance MCP tool {name!r} not found in registry; check server config."
    )


yf_quote_tool: BaseTool = _select(QUOTE_TOOL_NAME)
yf_history_tool: BaseTool = _select(HISTORY_TOOL_NAME)
yf_news_tool: BaseTool = _select(NEWS_TOOL_NAME)
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. If a test imports the old `_quote`, `_history`, `_news`, or `_sync_call` symbols, fix that test by updating it to call `yf_quote_tool.invoke(...)`, etc. Recount must match before commit.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/mcp_clients/yfinance_client.py
git commit -m "refactor(mcp): migrate Yahoo Finance client to MultiServerMCPClient"
```

---

## Task 6: Register filesystem server and create `filesystem_client.py`

**Files:**
- Modify: `market-intelligence-agent/app/agent/tools/mcp_clients/registry.py`
- Create: `market-intelligence-agent/app/agent/tools/mcp_clients/filesystem_client.py`

- [ ] **Step 1: Add filesystem server to the registry config**

Open `market-intelligence-agent/app/agent/tools/mcp_clients/registry.py`. Add one import at the top:

```python
from app.core.config import settings
```

Replace the `_server_config()` function with the version below (adds the filesystem entry plus a `mkdir` for the workspace root):

```python
def _server_config() -> dict:
    """Build the MultiServerMCPClient server config. Centralised so adding a server
    means changing one dict, not three import sites."""
    workspace_root = settings.WORKSPACE_ROOT.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    return {
        "crm": {
            "command": "uv",
            "args": ["run", "mcp-server-sqlite", "--db-path", "customers.db"],
            "transport": "stdio",
            "env": dict(os.environ),
        },
        "yfinance": {
            "command": "uv",
            "args": ["run", "yfmcp"],
            "transport": "stdio",
            "env": dict(os.environ),
        },
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", str(workspace_root)],
            "transport": "stdio",
            "env": dict(os.environ),
        },
    }
```

- [ ] **Step 2: Create `filesystem_client.py`**

Create `market-intelligence-agent/app/agent/tools/mcp_clients/filesystem_client.py` with:

```python
"""Filesystem MCP client — selects the 3 filesystem tools out of the shared registry.

The official @modelcontextprotocol/server-filesystem server exposes ~10 tools; we
expose only the 3 needed for the read+write workspace use case. Sandboxing is
enforced by the server itself via the allowed-root argument set in registry.py.

Public symbols: fs_read_file_tool (read-only), fs_list_dir_tool (read-only),
fs_write_file_tool (gated by approval_node).
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.registry import get_mcp_tools

logger = logging.getLogger(__name__)

READ_FILE_TOOL_NAME = "filesystem_read_text_file"
LIST_DIR_TOOL_NAME = "filesystem_list_directory"
WRITE_FILE_TOOL_NAME = "filesystem_write_file"


def _select(name: str) -> BaseTool:
    for tool in get_mcp_tools():
        if tool.name == name:
            return tool
    raise RuntimeError(
        f"Filesystem MCP tool {name!r} not found in registry; check server config."
    )


fs_read_file_tool: BaseTool = _select(READ_FILE_TOOL_NAME)
fs_list_dir_tool: BaseTool = _select(LIST_DIR_TOOL_NAME)
fs_write_file_tool: BaseTool = _select(WRITE_FILE_TOOL_NAME)
```

- [ ] **Step 3: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. The filesystem client isn't imported anywhere yet, but the registry now includes the filesystem server — `get_mcp_tools()` will spawn it once if anything imports the registry. If `npx` isn't available locally, you'll see a clear error; install Node 20+ or run inside Docker.

- [ ] **Step 4: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/mcp_clients/registry.py \
        market-intelligence-agent/app/agent/tools/mcp_clients/filesystem_client.py
git commit -m "feat(filesystem-mcp): register filesystem MCP server, add filesystem_client"
```

---

## Task 7: Wire new tools into `TOOLS` and update `READ_ONLY_TOOLS`

**Files:**
- Modify: `market-intelligence-agent/app/agent/tools/__init__.py`

- [ ] **Step 1: Replace `__init__.py`**

Replace the entire contents of `market-intelligence-agent/app/agent/tools/__init__.py` with:

```python
from app.agent.tools.emails import send_email_tool
from app.agent.tools.mcp_clients.mcp_client import crm_tool
from app.agent.tools.mcp_clients.yfinance_client import (
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
)
from app.agent.tools.mcp_clients.filesystem_client import (
    fs_read_file_tool,
    fs_list_dir_tool,
    fs_write_file_tool,
)

TOOLS = [
    send_email_tool,
    crm_tool,
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
    fs_read_file_tool,
    fs_list_dir_tool,
    fs_write_file_tool,
]

READ_ONLY_TOOLS: set[str] = {
    "crm_read_query",
    "yfinance_get_quote",
    "yfinance_get_history",
    "yfinance_get_news",
    "filesystem_read_text_file",
    "filesystem_list_directory",
}

__all__ = [
    "TOOLS",
    "READ_ONLY_TOOLS",
    "send_email_tool",
    "crm_tool",
    "yf_quote_tool",
    "yf_history_tool",
    "yf_news_tool",
    "fs_read_file_tool",
    "fs_list_dir_tool",
    "fs_write_file_tool",
]
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. If a test asserted the old tool count or old names (`crm_query`, `yf_quote`, etc.), fix that test by updating the assertion to the new namespaced names. Recount must match before commit.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/__init__.py
git commit -m "feat(filesystem-mcp): expose 3 filesystem tools, refresh READ_ONLY_TOOLS to namespaced names"
```

---

## Task 8: Update the system prompt for namespaced tool names + workspace awareness

**Files:**
- Modify: `market-intelligence-agent/app/agent/prompts/system.py`

- [ ] **Step 1: Replace `system.py`**

Replace the entire contents of `market-intelligence-agent/app/agent/prompts/system.py` with:

```python
SYSTEM_PROMPT = """You are an expert assistant for data analysis and communication.

🛠️ YOUR TOOLS

CRM (read-only):
1. `crm_read_query` — run a SELECT query against the customer database.

Market data (read-only, Yahoo Finance):
2. `yfinance_get_quote` — current price and day stats for a ticker (args: `ticker: str`).
3. `yfinance_get_history` — historical prices for a ticker (args: `ticker: str`, optional `period: str` like "1mo", "3mo", "1y"; default "1mo").
4. `yfinance_get_news` — recent news headlines for a ticker (args: `ticker: str`, optional `limit: int`; default 5).

Filesystem workspace (read-only reads, gated writes):
5. `filesystem_list_directory` — list files in a workspace path (args: `path: str`, default "."). Use this first to discover what the user has dropped into the workspace.
6. `filesystem_read_text_file` — read a UTF-8 text file from the workspace (args: `path: str`).
7. `filesystem_write_file` — save a text artifact (e.g. a brief, a CSV) into the workspace (args: `path: str`, `content: str`). This is a side-effect tool and requires human approval.

Side effects (require human approval):
8. `send_email` — send a report or message.

🗄️ CRM SCHEMA (table: `customers`)
- `id` (INTEGER): unique id
- `name` (TEXT): full name
- `email` (TEXT): email address
- `status` (TEXT): customer tier (e.g., 'VIP', 'Standard', 'Premium')
- `total_spend` (REAL): total amount spent

📁 WORKSPACE GUIDELINES
- The workspace is a single shared folder on disk. Files dropped there by the user appear immediately; files you write there persist after the session ends.
- Only UTF-8 text files are supported. Binary files (PDFs, images) will return an error — for PDFs, the user should use the existing Pinecone ingest pipeline.
- Paths are relative to the workspace root. You cannot read or write outside it; the MCP server enforces this.
- Before reading, list the directory if you don't already know what files exist.

🧠 INSTRUCTIONS
- You are autonomous: write valid `SELECT` SQL queries based on the user's request. You may use WHERE, ORDER BY, LIMIT, and aggregates (COUNT, SUM).
- To find a customer by name, use `LIKE '%Name%'`.
- Before sending an email, make sure you have the recipient's address — fetch it from the CRM if needed.

📈 MARKET DATA GUIDELINES
- For "what's X trading at" questions, call `yfinance_get_quote`.
- For trend / performance / chart questions ("how has X done over the last quarter"), call `yfinance_get_history` with an appropriate `period`.
- For "any news on X" questions, call `yfinance_get_news`.
- You may call multiple market-data tools in parallel for the same ticker, or across several tickers, when the question benefits from it.
- Tickers are case-insensitive but conventionally uppercase (e.g., AAPL, MSFT, NVDA).
- Yahoo Finance is unauthenticated and may return "no data found" for invalid tickers — explain this to the user and suggest verifying the symbol.

Use the provided context (RAG documents and conversation history) to answer precisely.
"""

ERROR_RECOVERY_PROMPT = (
    "A tool returned a technical error. Analyze the error, explain it simply "
    "to the user, and propose a workaround if possible."
)
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/prompts/system.py
git commit -m "feat(filesystem-mcp): system prompt — namespaced tool names + workspace guidance"
```

---

## Task 9: Update `docs/TOOLS.md`, `CLAUDE.md`, and `README.md`

**Files:**
- Modify: `market-intelligence-agent/docs/TOOLS.md`
- Modify: `market-intelligence-agent/CLAUDE.md`
- Modify: `market-intelligence-agent/README.md`

- [ ] **Step 1: Replace `docs/TOOLS.md`**

Replace the entire contents of `market-intelligence-agent/docs/TOOLS.md` with:

```markdown
# Tools Registry

This file lists every tool exposed to the agent (native LangChain tools and MCP-backed tools), with a brief explanation of what each does and why it exists in this project.

**Rule:** every time a new tool (native or MCP) is added to `TOOLS` in `app/agent/tools/__init__.py`, append an entry to the table below and add a short *Why* paragraph in the "Per-tool details" section. Keep `READ_ONLY_TOOLS` in sync.

All MCP-backed tools are loaded through a single `MultiServerMCPClient` registered in `app/agent/tools/mcp_clients/registry.py`. Tool names are namespaced as `<server_name>_<mcp_tool_name>`.

## Summary table

| # | Name | Type | Backend | Args | What it does | Why we have it |
|---|---|---|---|---|---|---|
| 1 | `send_email` | side-effect | SMTP/Gmail (native) | recipient, subject, body | Sends an email from the configured sender account; falls back to a console simulation when credentials are placeholder. | Lets the agent take a real-world action (notify a human, deliver a brief) — primary motivation for the HITL approval gate. |
| 2 | `crm_read_query` | read-only | MCP stdio → `mcp-server-sqlite` | sql (single string) | Runs a `read_query` against the local `customers.db` via the SQLite MCP server. | Demonstrates the MCP stdio pattern with a structured-DB tool and gives the agent customer/CRM context to ground its analysis. |
| 3 | `yfinance_get_quote` | read-only | MCP stdio → `yfmcp` | ticker | Returns the latest quote (price, change, volume) for a given ticker. | Live market price is the most-asked datapoint for a market-intelligence agent; cheap real-time signal. |
| 4 | `yfinance_get_history` | read-only | MCP stdio → `yfmcp` | ticker, period (default `"1mo"`) | Returns historical OHLCV bars for a ticker over the requested period. | Enables trend / momentum reasoning that a single quote can't support. |
| 5 | `yfinance_get_news` | read-only | MCP stdio → `yfmcp` | ticker, limit (default `5`) | Returns the most recent headlines associated with a ticker. | Pairs price action with narrative; lets the agent explain *why* a ticker moved. |
| 6 | `filesystem_read_text_file` | read-only | MCP stdio → `@modelcontextprotocol/server-filesystem` | path | Reads a UTF-8 text file from the sandboxed workspace at `data/workspace/`. | Lets the user drop a file (CSV of tickers, briefing notes) into the workspace and have the agent consume it without re-running the Pinecone ingest pipeline. |
| 7 | `filesystem_list_directory` | read-only | same | path (default `"."`) | Lists files and folders inside a workspace path. | Discovery: the agent uses this to find out what the user has dropped before reading. |
| 8 | `filesystem_write_file` | side-effect | same | path, content | Writes a UTF-8 text file into the sandboxed workspace. Gated by HITL approval. | Lets the agent persist briefs, CSV snapshots, or JSON dossiers as durable artifacts that survive the session. |

`READ_ONLY_TOOLS = {"crm_read_query", "yfinance_get_quote", "yfinance_get_history", "yfinance_get_news", "filesystem_read_text_file", "filesystem_list_directory"}` — the allowlist consulted by `approval_node` to skip the HITL interrupt for safe reads.

## Per-tool details

### 1. `send_email`
- **File:** `app/agent/tools/emails.py`
- **What:** SMTP send via Gmail (587, STARTTLS). If `EMAIL_SENDER` still contains the placeholder `"ton_email"`, the tool prints to stdout and returns success without sending — useful for portfolio demos.
- **Why:** It is the only native side-effect tool currently shipped. It exists to exercise the human-in-the-loop approval flow end-to-end: the LLM proposes a recipient/subject/body, the graph hits `interrupt()`, the user approves or rejects in the Streamlit UI, and only then does `ToolNode` execute the send.

### 2. `crm_read_query`
- **File:** `app/agent/tools/mcp_clients/mcp_client.py` (selects from registry)
- **What:** Spawns `mcp-server-sqlite` as a stdio subprocess scoped to `customers.db`, sends a `read_query` with the LLM-supplied SQL, returns rows.
- **Why:** Demonstrates structured-data retrieval over MCP and gives the agent a private dataset (customers, deals, regions) to combine with public market data. Read-only by construction — `mcp-server-sqlite`'s `read_query` rejects writes.

### 3. `yfinance_get_quote`
- **File:** `app/agent/tools/mcp_clients/yfinance_client.py` (selects from registry)
- **What:** Spawns `yfmcp` as a stdio subprocess and calls `get_quote(ticker)`.
- **Why:** Most market questions start with "what's it trading at right now?" This is the cheapest, lowest-latency signal the agent can reach for.

### 4. `yfinance_get_history`
- **File:** same as `yfinance_get_quote`
- **What:** Calls `get_history(ticker, period)`; default period `"1mo"`. Returns OHLCV bars.
- **Why:** Single-point quotes don't support trend reasoning. With history the agent can answer "is NVDA breaking out?" or "how did TSM perform last quarter?".

### 5. `yfinance_get_news`
- **File:** same as `yfinance_get_quote`
- **What:** Calls `get_news(ticker, limit)`; default limit `5`. Returns recent headlines.
- **Why:** Price moves without context are noise. News headlines provide the narrative thread the synthesis step needs.

### 6. `filesystem_read_text_file`
- **File:** `app/agent/tools/mcp_clients/filesystem_client.py` (selects from registry)
- **What:** Reads a UTF-8 text file from `data/workspace/<path>` via `@modelcontextprotocol/server-filesystem`. Paths outside the workspace root are rejected by the server.
- **Why:** The input channel of the workspace. Drop a CSV of tickers, a competitor list, or a briefing note into `data/workspace/` and the agent can consume it without going through the Pinecone ingest pipeline.

### 7. `filesystem_list_directory`
- **File:** same as `filesystem_read_text_file`
- **What:** Lists entries in a workspace path; defaults to the workspace root.
- **Why:** Discovery. The agent uses this to find out what files exist before reading. Without it, the LLM would have to guess paths.

### 8. `filesystem_write_file`
- **File:** same as `filesystem_read_text_file`
- **What:** Writes UTF-8 content to `data/workspace/<path>`. Creates parent directories if missing. Last-write-wins.
- **Why:** The output channel of the workspace. The agent's synthesis usually lives only in the message history; this lets it persist briefs and snapshots that survive the session. Gated by `approval_node` — the user sees the path and content in the Streamlit Approve/Refuse modal before any disk write.

## How to add a new tool

1. **MCP-backed:** add an entry to `_server_config()` in `app/agent/tools/mcp_clients/registry.py`. Create a per-server selector module (or extend an existing one) that filters the registry's tool list by name. Native tool: implement under `app/agent/tools/`, wrap with `@tool` if multi-arg.
2. Export the tool symbol from `app/agent/tools/__init__.py` and append it to `TOOLS`.
3. If the tool is read-only (no side effects, idempotent, safe to retry), add its name to `READ_ONLY_TOOLS` so it bypasses the HITL approval gate.
4. **Update this file:** add a row to the summary table and a sub-section under "Per-tool details" explaining *what* it does and *why* it earns a slot. Keep entries short — a few sentences each.
5. If the tool is a new MCP server, also note the binary/package name and any stdio invocation quirks.
```

- [ ] **Step 2: Update `CLAUDE.md`**

Open `market-intelligence-agent/CLAUDE.md`. Replace the `### Tools (`app/agent/tools/__init__.py`)` section (the table and the line that follows it) with this updated version that uses the new namespaced names and adds the three filesystem rows:

```markdown
### Tools (`app/agent/tools/__init__.py`)

All MCP-backed tools are loaded via a single `MultiServerMCPClient` in `app/agent/tools/mcp_clients/registry.py`; per-server modules (`mcp_client.py`, `yfinance_client.py`, `filesystem_client.py`) filter that list and re-export public symbols. Tool names are namespaced as `<server_name>_<mcp_tool_name>`.

| Tool name | File | Type | What it does |
|---|---|---|---|
| `send_email` | `app/agent/tools/emails.py` | side-effect | SMTP send via Gmail. Simulates if credentials are placeholder. |
| `crm_read_query` | `app/agent/tools/mcp_clients/mcp_client.py` | read-only | MCP stdio client → `mcp-server-sqlite` → `read_query` against `customers.db`. |
| `yfinance_get_quote` | `app/agent/tools/mcp_clients/yfinance_client.py` | read-only | MCP stdio client → `yfmcp` → `get_quote(ticker)`. |
| `yfinance_get_history` | same | read-only | `get_history(ticker, period="1mo")`. |
| `yfinance_get_news` | same | read-only | `get_news(ticker, limit=5)`. |
| `filesystem_read_text_file` | `app/agent/tools/mcp_clients/filesystem_client.py` | read-only | MCP stdio client → `@modelcontextprotocol/server-filesystem` → `read_text_file(path)` inside `data/workspace/`. |
| `filesystem_list_directory` | same | read-only | `list_directory(path)` inside `data/workspace/`. |
| `filesystem_write_file` | same | side-effect | `write_file(path, content)` inside `data/workspace/`. Gated by `approval_node`. |

`READ_ONLY_TOOLS = {"crm_read_query", "yfinance_get_quote", "yfinance_get_history", "yfinance_get_news", "filesystem_read_text_file", "filesystem_list_directory"}` is the allowlist consulted by `approval_node` to skip the interrupt for safe reads.
```

- [ ] **Step 3: Update `README.md`**

Open `market-intelligence-agent/README.md`. Find a sensible spot (typically before "Run the FastAPI backend" or near other directory references like `data/`) and add this paragraph:

```markdown
## Workspace folder

The agent has a sandboxed read-write workspace at `data/workspace/`. Drop files there (text only — UTF-8 CSV, markdown, JSON, etc.) and the agent can read them via `filesystem_read_text_file` and `filesystem_list_directory`. The agent can also save artifacts (briefs, snapshots) via `filesystem_write_file`; saves are gated by HITL approval. The folder is bind-mounted into Docker, so artifacts survive container restarts.
```

- [ ] **Step 4: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**.

- [ ] **Step 5: Commit**

```bash
git add market-intelligence-agent/docs/TOOLS.md \
        market-intelligence-agent/CLAUDE.md \
        market-intelligence-agent/README.md
git commit -m "docs(filesystem-mcp): tools registry, CLAUDE.md table, README workspace section"
```

---

## Self-review notes

**Spec coverage check:**
- Goal (single shared workspace + 3 tools) → Tasks 1, 6, 7. ✓
- Decision table (MCP, single workspace, gated writes, 3 tools, langchain-mcp-adapters) → Tasks 1–7. ✓
- Architecture (graph topology unchanged, registry pattern, migration of existing two clients) → Tasks 3–7. ✓
- All five components from the spec (registry.py, mcp_client.py rewrite, yfinance_client.py rewrite, filesystem_client.py, __init__.py update) → Tasks 3, 4, 5, 6, 7. ✓
- Supporting changes (config WORKSPACE_ROOT/FILESYSTEM_TIMEOUT_S, .gitkeep, .gitignore, Dockerfile node + pre-pull, system prompt, pyproject.toml dep) → Tasks 1, 2, 8. ✓
- Documentation deliverables (docs/TOOLS.md, CLAUDE.md, README.md) → Task 9. ✓
- Error handling (server-spawn failures, per-call MCP errors, sandboxing, mkdir belt-and-suspenders) → Task 2 (Docker pre-pull), Task 6 (mkdir in registry). The remaining error categories (path errors, concurrent access, large/binary files, HITL rejection) need no code — they're behaviors of the existing server / `approval_node` and are documented in `docs/TOOLS.md` (Task 9) and the system prompt (Task 8). ✓

**Type / name consistency:**
- `crm_read_query` / `yfinance_get_quote` / `yfinance_get_history` / `yfinance_get_news` / `filesystem_read_text_file` / `filesystem_list_directory` / `filesystem_write_file` — used identically in `READ_ONLY_TOOLS`, system prompt, `docs/TOOLS.md`, `CLAUDE.md`. ✓
- Public symbols `crm_tool` / `yf_quote_tool` / `yf_history_tool` / `yf_news_tool` / `fs_read_file_tool` / `fs_list_dir_tool` / `fs_write_file_tool` — used identically in client modules and `__init__.py`. ✓
- `get_mcp_tools()` defined in Task 3, called in Tasks 4, 5, 6. ✓

**Placeholder scan:** none. Every step has either complete code or an exact command.
