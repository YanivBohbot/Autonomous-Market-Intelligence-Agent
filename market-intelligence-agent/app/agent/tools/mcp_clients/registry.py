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
