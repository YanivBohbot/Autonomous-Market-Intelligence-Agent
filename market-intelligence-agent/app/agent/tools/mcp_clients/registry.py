"""MCP client registry — single MultiServerMCPClient for every stdio MCP server.

Exposes `get_mcp_tools()`, a sync function that returns the full list of LangChain
BaseTool objects produced by the registered MCP servers. Per-server modules
(`mcp_client.py`, `yfinance_client.py`, `filesystem_client.py`) filter this list
by name to re-export their public tool symbols.

Tool names come straight from the upstream MCP servers (no controller-side prefix).
yfmcp self-namespaces (`yfinance_get_ticker_info`, ...); the filesystem server uses
unambiguous names (`read_text_file`, `write_file`, ...). The CRM `read_query` tool
is the one bare name; per-server modules filter by exact name so any future
collision surfaces as a startup-time RuntimeError, not silent wrong-tool routing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.config import settings

logger = logging.getLogger(__name__)


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
            # Run the filesystem server with cwd = workspace_root so the LLM can use
            # plain relative paths like "brief.md" (the system prompt promises this).
            # Without it, relative paths resolve to the calling process's cwd (project
            # root), which is outside the allowed directory and the server rejects them.
            "cwd": str(workspace_root),
        },
    }


async def _load_tools() -> tuple[BaseTool, ...]:
    # No context manager needed: as of langchain-mcp-adapters 0.1.0, `async with`
    # raises NotImplementedError. `get_tools()` passes the connection config directly
    # to `load_mcp_tools(session=None, connection=...)` so each returned tool wrapper
    # manages its own per-call stdio subprocess — there is no long-lived session to clean up.
    client = MultiServerMCPClient(_server_config())
    tools = await client.get_tools()
    logger.info("MCP registry loaded %d tools: %s", len(tools), [t.name for t in tools])
    return tuple(tools)


def _run_async(coro):
    """Sync bridge that works whether or not an event loop is already running.

    Narrows the RuntimeError catch to the specific 'event loop is already running'
    case so that errors raised by the coroutine itself (e.g. MCP subprocess failures)
    propagate normally.
    """
    try:
        return asyncio.run(coro)
    except RuntimeError as exc:
        if "event loop is already running" not in str(exc).lower():
            raise
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


@lru_cache(maxsize=1)
def get_mcp_tools() -> tuple[BaseTool, ...]:
    """Return all MCP-backed LangChain tools. Cached after first call."""
    return _run_async(_load_tools())


def select_tool(name: str, server_label: str) -> BaseTool:
    """Return the registered MCP tool with the given .name, raising a clear
    startup error if the registry doesn't contain it. `server_label` only
    appears in the error message — it isn't used for matching."""
    for tool in get_mcp_tools():
        if tool.name == name:
            return tool
    raise RuntimeError(
        f"{server_label} MCP tool {name!r} not found in registry; check server config."
    )
