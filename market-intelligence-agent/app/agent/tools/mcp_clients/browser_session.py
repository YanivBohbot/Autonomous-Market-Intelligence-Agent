"""One long-lived MCP session for the local browser server.

The shared registry loads tools with `session=None`, so every call spawns a
fresh stdio subprocess. That is fine for stateless servers (SQLite,
yfinance, filesystem), but for @playwright/mcp each call got a brand-new
Chromium: browser_navigate loaded page A, then browser_take_screenshot
captured a blank page B.

`PersistentToolSession` keeps ONE session open per event loop, held by a
background task so the anyio context is entered and exited in the same task,
and closed when the loop shuts down. `persistent_tool` wraps the registry
tool, keeping its name, description and JSON schema so the LLM sees nothing
new, and runs every call on that shared session.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import PureWindowsPath
from typing import Any, cast

from langchain_core.tools import BaseTool, StructuredTool

OpenTools = Callable[[], AbstractAsyncContextManager[dict[str, BaseTool]]]


class PersistentToolSession:
    def __init__(self, open_tools: OpenTools):
        self._open_tools = open_tools
        # loop -> (future resolving to the session's tools, holder task)
        self._by_loop: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, tuple[asyncio.Future, asyncio.Task]
        ] = weakref.WeakKeyDictionary()

    async def get(self, name: str) -> BaseTool:
        loop = asyncio.get_running_loop()
        entry = self._by_loop.get(loop)
        if entry is None or entry[1].done():
            ready: asyncio.Future = loop.create_future()
            task = loop.create_task(self._hold(ready))
            entry = self._by_loop[loop] = (ready, task)
        try:
            tools = await asyncio.shield(entry[0])
        except BaseException:
            # Failed to open: forget it so the next call retries.
            if self._by_loop.get(loop) is entry:
                del self._by_loop[loop]
            raise
        return tools[name]

    async def _hold(self, ready: asyncio.Future) -> None:
        try:
            async with self._open_tools() as tools:
                ready.set_result(tools)
                await asyncio.Event().wait()  # until the loop cancels us at shutdown
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            if isinstance(exc, asyncio.CancelledError):
                raise


def bare_screenshot_filename(arguments: dict[str, Any]) -> dict[str, Any]:
    """Keep only the file name: the browser server runs in the screenshots
    folder, so every capture lands where the chat UI serves it, and the LLM
    can't write outside it."""
    filename = arguments.get("filename")
    if not filename:
        return arguments
    return {**arguments, "filename": PureWindowsPath(str(filename)).name}


def persistent_tool(template: BaseTool, holder: PersistentToolSession) -> StructuredTool:
    name = template.name

    async def _call(**arguments: Any) -> Any:
        if name == "browser_take_screenshot":
            arguments = bare_screenshot_filename(arguments)
        tool = await holder.get(name)
        coroutine = getattr(tool, "coroutine", None)  # MCP tools are StructuredTools
        if coroutine is None:
            raise RuntimeError(f"MCP tool {name!r} has no coroutine")
        return await coroutine(**arguments)

    return StructuredTool(
        name=name,
        description=template.description,
        args_schema=template.args_schema or {"type": "object", "properties": {}},
        coroutine=_call,
        response_format=template.response_format,
        metadata=template.metadata,
    )


@asynccontextmanager
async def open_local_browser_tools():
    """Open one stdio session to the configured browser MCP server."""
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools

    from app.agent.tools.mcp_clients.registry import _browser_entry
    from app.core.config import settings

    connections = cast(Any, {"browser": _browser_entry(settings.WORKSPACE_ROOT.resolve())})
    client = MultiServerMCPClient(connections)
    async with client.session("browser") as session:
        yield {tool.name: tool for tool in await load_mcp_tools(session)}
