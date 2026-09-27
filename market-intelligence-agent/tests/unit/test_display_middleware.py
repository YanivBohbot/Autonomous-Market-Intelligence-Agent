"""MarketDeskDisplayMiddleware: reshapes a registered tool's ToolMessage into
{"summary": <original text>, "displays": [...]}; everything else (unregistered
tools, a failing normalizer) passes through untouched — the answer must never
break because a display couldn't be built."""
import json
from unittest.mock import patch

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from app.agent.multi_agent import display


def _request(name: str, args: dict) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"id": "c1", "name": name, "args": args},
        tool=None,
        state={"messages": []},
        runtime=None,
    )


def _handler_returning(content):
    def handler(request):
        return ToolMessage(content=content, name=request.tool_call["name"], tool_call_id=request.tool_call["id"])
    return handler


async def _ahandler_returning(content):
    async def handler(request):
        return ToolMessage(content=content, name=request.tool_call["name"], tool_call_id=request.tool_call["id"])
    return handler


def test_unregistered_tool_passes_through_untouched():
    result = display.market_desk_display.wrap_tool_call(_request("read_query", {}), _handler_returning("raw text"))
    assert result.content == "raw text"


def test_registered_tool_gets_the_envelope():
    with patch.dict(display.DISPLAY_NORMALIZERS, {"fake_tool": lambda text, args: [{"type": "fake", "n": len(text)}]}):
        result = display.market_desk_display.wrap_tool_call(_request("fake_tool", {}), _handler_returning("hello"))
    envelope = json.loads(result.content)
    assert envelope == {"summary": "hello", "displays": [{"type": "fake", "n": 5}]}


def test_a_raising_normalizer_leaves_content_untouched():
    def boom(text, args):
        raise ValueError("no")
    with patch.dict(display.DISPLAY_NORMALIZERS, {"fake_tool": boom}):
        result = display.market_desk_display.wrap_tool_call(_request("fake_tool", {}), _handler_returning("hello"))
    assert result.content == "hello"


def test_normalizer_receives_the_tool_call_args():
    seen = {}
    def spy(text, args):
        seen.update(args)
        return []
    with patch.dict(display.DISPLAY_NORMALIZERS, {"fake_tool": spy}):
        display.market_desk_display.wrap_tool_call(_request("fake_tool", {"symbol": "AAPL"}), _handler_returning("x"))
    assert seen == {"symbol": "AAPL"}


def test_list_content_is_flattened_to_text_before_normalizing():
    # yfinance/browser MCP tools return [{"type": "text", "text": "..."}], not a plain string.
    list_content = [{"type": "text", "text": "hello", "id": "x"}]
    with patch.dict(display.DISPLAY_NORMALIZERS, {"fake_tool": lambda text, args: [{"type": "fake", "text": text}]}):
        result = display.market_desk_display.wrap_tool_call(_request("fake_tool", {}), _handler_returning(list_content))
    envelope = json.loads(result.content)
    assert envelope == {"summary": "hello", "displays": [{"type": "fake", "text": "hello"}]}


def test_a_non_toolmessage_result_passes_through():
    # HumanInTheLoopMiddleware and others can return a Command instead of a ToolMessage.
    sentinel = object()
    result = display.market_desk_display.wrap_tool_call(_request("read_query", {}), lambda request: sentinel)
    assert result is sentinel


@pytest.mark.anyio
async def test_async_path_mirrors_the_sync_path():
    with patch.dict(display.DISPLAY_NORMALIZERS, {"fake_tool": lambda text, args: [{"type": "fake"}]}):
        result = await display.market_desk_display.awrap_tool_call(_request("fake_tool", {}), await _ahandler_returning("hi"))
    assert json.loads(result.content) == {"summary": "hi", "displays": [{"type": "fake"}]}


def test_browser_agent_strips_images_before_enveloping():
    # Regression: AgentMiddleware.wrap_tool_call chains "first = outermost"
    # (langchain/agents/factory.py, _chain_tool_call_wrappers) — the display
    # middleware must be listed BEFORE strip_tool_images in browser_agent's
    # middleware list, so it only ever sees text, never a raw image block.
    from app.agent.multi_agent.common import strip_tool_images

    image_and_text = [
        {"type": "text", "text": "### Result\n- [Screenshot of viewport](screenshots/x.png)"},
        {"type": "image", "data": "base64...", "mimeType": "image/png"},
    ]

    def raw_handler(request):
        return ToolMessage(content=image_and_text, name="browser_take_screenshot", tool_call_id="c1")

    # Simulate the chain exactly as build_browser_agent() wires it: display
    # middleware listed before strip_tool_images -> display's handler(request)
    # call resolves through strip_tool_images first.
    def strip_then_raw(request):
        return strip_tool_images.wrap_tool_call(request, raw_handler)

    result = display.market_desk_display.wrap_tool_call(_request("browser_take_screenshot", {}), strip_then_raw)
    envelope = json.loads(result.content)
    assert envelope["displays"] == [{"type": "screenshot", "url": "/workspace/screenshots/x.png"}]
    assert "base64" not in result.content
