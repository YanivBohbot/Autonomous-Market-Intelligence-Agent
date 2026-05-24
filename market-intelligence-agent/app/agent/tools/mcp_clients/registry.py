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
import concurrent.futures
import logging
import os
from functools import lru_cache

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.config import settings

logger = logging.getLogger(__name__)


def _gateway_config() -> dict:
    """Single AgentCore Gateway endpoint that proxies all tool servers.

    The MCP-over-HTTPS transport name (`streamable_http`) is the langchain-mcp-adapters
    name for AgentCore Gateway's MCP endpoint. The Gateway routes by tool name to
    the underlying Lambda targets (yfinance, filesystem, sqlite-crm), so we register
    *one* logical server here and the tool list still comes back the same as the
    stdio path — the agent code doesn't know which transport is in use.
    """
    if not settings.AGENTCORE_GATEWAY_URL:
        raise RuntimeError(
            "MCP_TRANSPORT=gateway requires AGENTCORE_GATEWAY_URL to be set."
        )
    return {
        "agentcore_gateway": {
            "transport": "streamable_http",
            "url": settings.AGENTCORE_GATEWAY_URL,
        }
    }


def _stdio_config() -> dict:
    """Local dev: each tool server runs as a stdio subprocess inside this process."""
    workspace_root = settings.WORKSPACE_ROOT.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "screenshots").mkdir(parents=True, exist_ok=True)
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
        "browser": {
            "command": "npx",
            "args": [
                "-y", "@playwright/mcp@latest",
                "--browser", "chromium",
                "--headless",
                "--output-dir", str(workspace_root / "screenshots"),
            ],
            "transport": "stdio",
            "env": dict(os.environ),
            # cwd = workspace_root so any relative path the LLM passes to
            # browser_take_screenshot lands inside the workspace, not the project root.
            "cwd": str(workspace_root),
        },
    }


def _server_config() -> dict:
    """Return the right MCP server config based on MCP_TRANSPORT.

    `stdio` (default): local subprocess servers — the original behavior, kept for
    dev and tests. `gateway`: a single AgentCore Gateway HTTPS endpoint that
    fronts the production tool Lambdas.
    """
    transport = settings.MCP_TRANSPORT.lower()
    if transport == "stdio":
        return _stdio_config()
    if transport == "gateway":
        return _gateway_config()
    raise ValueError(
        f"Unknown MCP_TRANSPORT={settings.MCP_TRANSPORT!r}. "
        "Valid values: 'stdio', 'gateway'."
    )


async def _load_tools() -> tuple[BaseTool, ...]:
    # No context manager needed: as of langchain-mcp-adapters 0.1.0, `async with`
    # raises NotImplementedError. `get_tools()` passes the connection config directly
    # to `load_mcp_tools(session=None, connection=...)` so each returned tool wrapper
    # manages its own per-call stdio subprocess — there is no long-lived session to clean up.
    config = _server_config()
    client = MultiServerMCPClient(config)
    try:
        tools = await client.get_tools()
    except Exception as exc:
        servers = ", ".join(config.keys())
        raise RuntimeError(
            f"Failed to load MCP tools from servers [{servers}]. "
            f"Check that `npx`, `uv`, and the configured MCP packages are installed and reachable. "
            f"Underlying error: {exc!r}"
        ) from exc
    logger.info("MCP registry loaded %d tools: %s", len(tools), [t.name for t in tools])
    return tuple(tools)


def _run_async(coro):
    """Sync bridge that works whether or not an event loop is already running.

    The MCP tools are loaded at module import time (`get_mcp_tools()` is called
    from module-level `select_tool(...)` lines in each per-server selector
    module). When uvicorn imports the app, that import happens *inside* uvicorn's
    running event loop — so `asyncio.run()` raises and we have to fall back.
    Running another loop in the same thread is illegal, so the fallback runs the
    coroutine in a fresh worker thread with its own loop and blocks until done.
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # asyncio.run() refused because a loop is already running on this thread.
        # Hand the coroutine to a worker thread that owns its own fresh loop.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()


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
