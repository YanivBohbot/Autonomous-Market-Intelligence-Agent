"""MCP client registry — Gateway-backed MultiServerMCPClient.

In production (Phase 4a+), the yfinance and CRM tools live behind an AgentCore
Gateway exposed as a single MCP-over-HTTPS endpoint. The agent talks to that
Gateway via `streamable_http` transport. The Gateway URL is injected into the
runtime as the `GATEWAY_URL` env var by the CDK stack (see cdk-stack.ts).

In local dev, `agentcore dev` doesn't spin up a real Gateway, so `GATEWAY_URL`
is unset. We log a clear "skipped" message and return an empty tool list — the
container's native tools (email, memory) still work, the graph still loads, and
the Phase 2 HITL smoke tests still pass.

Per-server modules (`mcp_client.py`, `yfinance_client.py`) filter this list by
exact name. `select_tool()` gracefully handles the empty-list case by returning
a no-op tool wrapper that raises only if the LLM actually tries to call it.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from functools import lru_cache

from langchain_core.tools import BaseTool, Tool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


def _gateway_url() -> str | None:
    """Return the Gateway URL from env, or None if unset (local dev)."""
    url = os.environ.get("GATEWAY_URL")
    if url and url.strip():
        return url.strip()
    return None


async def _load_tools() -> tuple[BaseTool, ...]:
    """Load MCP tools from the AgentCore Gateway via streamable_http."""
    url = _gateway_url()
    if url is None:
        logger.warning("[registry] GATEWAY_URL unset — Gateway tools skipped")
        return ()

    config = {
        "market-gw": {
            "transport": "streamable_http",
            "url": url,
        },
    }
    client = MultiServerMCPClient(config)
    try:
        tools = await client.get_tools()
    except Exception as exc:
        logger.warning(
            "[registry] Failed to load Gateway tools from %s: %r — proceeding with empty set",
            url,
            exc,
        )
        return ()
    logger.info(
        "[registry] Loaded %d Gateway tools from %s: %s",
        len(tools),
        url,
        [t.name for t in tools],
    )
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
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()


@lru_cache(maxsize=1)
def get_mcp_tools() -> tuple[BaseTool, ...]:
    """Return all MCP-backed LangChain tools. Cached after first call.

    Returns an empty tuple in local dev (no Gateway).
    """
    return _run_async(_load_tools())


def _noop_tool(name: str, server_label: str) -> BaseTool:
    """Build a placeholder tool that raises only if actually invoked.

    Used when the registry is empty (local dev / Gateway unreachable). Keeps
    module imports working so the agent boots; the LLM won't bind these into
    its tool set because they aren't in TOOLS, but per-server selector modules
    can still re-export them as references.
    """

    def _unavailable(*_args, **_kwargs):  # pragma: no cover - never run in healthy flow
        raise RuntimeError(
            f"{server_label} MCP tool {name!r} is not available — Gateway not configured."
        )

    return Tool(
        name=name,
        description=f"[unavailable] {server_label} {name} — Gateway not configured.",
        func=_unavailable,
    )


def select_tool(name: str, server_label: str) -> BaseTool:
    """Return the registered MCP tool with the given .name.

    If the registry is empty (local dev fallback), log a warning and return a
    no-op tool whose `.func` raises on invocation. That keeps `from ... import
    yf_quote_tool` working without crashing import; the tool simply won't be
    listed in TOOLS so the LLM never tries to call it.
    """
    tools = get_mcp_tools()
    for tool in tools:
        if tool.name == name:
            return tool
    logger.warning(
        "[registry] %s MCP tool %r not found (registry has %d tools) — returning no-op",
        server_label,
        name,
        len(tools),
    )
    return _noop_tool(name, server_label)
