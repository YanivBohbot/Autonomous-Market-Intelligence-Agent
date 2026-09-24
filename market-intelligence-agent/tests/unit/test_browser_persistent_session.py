"""Local browser tools share ONE MCP session per event loop.

Regression: each browser tool call used to spawn its own @playwright/mcp
subprocess (fresh Chromium), so browser_navigate loaded page A and
browser_take_screenshot captured a brand-new blank page B.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest
from langchain_core.tools import StructuredTool

from app.agent.tools.mcp_clients.browser_session import (
    PersistentToolSession,
    persistent_tool,
)


class _FakeBrowser:
    """Stands in for one Playwright MCP session: remembers the current page."""

    def __init__(self):
        self.page = "about:blank"

    def tools(self):
        async def navigate(**kw):
            self.page = kw["url"]
            return ([{"type": "text", "text": f"navigated {self.page}"}], None)

        async def screenshot(**kw):
            return ([{"type": "text", "text": f"shot of {self.page}"}], None)

        return {
            "browser_navigate": StructuredTool(
                name="browser_navigate", description="nav", coroutine=navigate,
                args_schema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
                response_format="content_and_artifact"),
            "browser_take_screenshot": StructuredTool(
                name="browser_take_screenshot", description="shot", coroutine=screenshot,
                args_schema={"type": "object", "properties": {}},
                response_format="content_and_artifact"),
        }


def _holder():
    opened = []

    @asynccontextmanager
    async def open_tools():
        browser = _FakeBrowser()
        opened.append(browser)
        yield browser.tools()

    return PersistentToolSession(open_tools), opened


def _wrapped(holder):
    template = _FakeBrowser().tools()
    return {name: persistent_tool(t, holder) for name, t in template.items()}


def test_navigate_then_screenshot_hit_the_same_page():
    holder, opened = _holder()
    tools = _wrapped(holder)

    async def run():
        await tools["browser_navigate"].ainvoke({"url": "https://tv10.co.il/"})
        return await tools["browser_take_screenshot"].ainvoke({})

    result = asyncio.run(run())
    assert "shot of https://tv10.co.il/" in str(result)
    assert len(opened) == 1  # one session for both calls


def test_concurrent_first_calls_open_a_single_session():
    holder, opened = _holder()
    tools = _wrapped(holder)

    async def run():
        await asyncio.gather(*(tools["browser_take_screenshot"].ainvoke({}) for _ in range(5)))

    asyncio.run(run())
    assert len(opened) == 1


def test_each_event_loop_gets_its_own_session():
    holder, opened = _holder()
    tools = _wrapped(holder)
    asyncio.run(tools["browser_take_screenshot"].ainvoke({}))
    asyncio.run(tools["browser_take_screenshot"].ainvoke({}))
    assert len(opened) == 2


def test_failed_open_is_retried_on_next_call():
    attempts = []

    @asynccontextmanager
    async def flaky_open():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("npx not ready")
        yield _FakeBrowser().tools()

    holder = PersistentToolSession(flaky_open)
    tools = _wrapped(holder)

    async def run():
        with pytest.raises(RuntimeError, match="npx not ready"):
            await tools["browser_take_screenshot"].ainvoke({})
        return await tools["browser_take_screenshot"].ainvoke({})

    assert "shot of about:blank" in str(asyncio.run(run()))
    assert len(attempts) == 2


def test_wrapper_keeps_the_llm_facing_schema():
    holder, _ = _holder()
    template = _FakeBrowser().tools()["browser_navigate"]
    wrapped = persistent_tool(template, holder)
    assert wrapped.name == template.name
    assert wrapped.description == template.description
    assert wrapped.args_schema == template.args_schema
    assert wrapped.response_format == "content_and_artifact"


def test_local_backend_wraps_tools_agentcore_does_not(monkeypatch):
    from app.agent.tools.mcp_clients import browser_client as bc

    sentinel = StructuredTool(name="browser_navigate", description="d", coroutine=None,
                              func=lambda **k: None, args_schema={"type": "object", "properties": {}})
    monkeypatch.setattr(bc, "select_tool", lambda name, label: sentinel)

    monkeypatch.setattr(bc.settings, "BROWSER_BACKEND", "local")
    wrapped = bc._browser_tool("browser_navigate")
    assert wrapped is not sentinel and wrapped.name == "browser_navigate"

    monkeypatch.setattr(bc.settings, "BROWSER_BACKEND", "agentcore")
    assert bc._browser_tool("browser_navigate") is sentinel


def test_screenshot_filename_is_reduced_to_a_bare_name():
    from app.agent.tools.mcp_clients.browser_session import bare_screenshot_filename
    assert bare_screenshot_filename({"filename": "screenshots/tv10.png"}) == {"filename": "tv10.png"}
    assert bare_screenshot_filename({"filename": "..\..\evil.png", "fullPage": True}) == {"filename": "evil.png", "fullPage": True}
    assert bare_screenshot_filename({"fullPage": True}) == {"fullPage": True}


def test_persistent_screenshot_tool_passes_a_bare_filename():
    seen = []

    class _Browser(_FakeBrowser):
        def tools(self):
            tools = super().tools()

            async def screenshot(**kw):
                seen.append(kw)
                return ([{"type": "text", "text": "ok"}], None)

            tools["browser_take_screenshot"] = StructuredTool(
                name="browser_take_screenshot", description="shot", coroutine=screenshot,
                args_schema={"type": "object", "properties": {"filename": {"type": "string"}}},
                response_format="content_and_artifact")
            return tools

    @asynccontextmanager
    async def open_tools():
        yield _Browser().tools()

    holder = PersistentToolSession(open_tools)
    tool = persistent_tool(_Browser().tools()["browser_take_screenshot"], holder)
    asyncio.run(tool.ainvoke({"filename": "screenshots/a.png"}))
    assert seen == [{"filename": "a.png"}]
