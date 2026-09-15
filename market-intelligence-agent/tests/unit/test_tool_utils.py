"""Unit tests for the shared tool_utils module, extracted so both the
single-agent graph and the multi-agent specialists can sanitize MCP tool
output without duplicating the image-stripping logic."""
import pytest
from langchain_core.messages import ToolMessage

from app.agent.nodes.tool_utils import strip_image_content, make_tool_runner


def test_strips_image_parts_keeps_text():
    content = [
        {"type": "text", "text": "result"},
        {"type": "image", "data": "base64...", "mimeType": "image/png"},
    ]
    assert strip_image_content(content) == [content[0]]


def test_leaves_plain_string_content_untouched():
    assert strip_image_content("plain text result") == "plain text result"


@pytest.mark.anyio
async def test_make_tool_runner_sanitizes_tool_message_content(monkeypatch):
    from app.agent.nodes import tool_utils as tool_utils_module

    class _FakeToolNode:
        async def ainvoke(self, state):
            return {
                "messages": [
                    ToolMessage(
                        content=[
                            {"type": "text", "text": "took screenshot"},
                            {"type": "image", "data": "base64...", "mimeType": "image/png"},
                        ],
                        tool_call_id="call_1",
                        name="some_tool",
                    )
                ]
            }

    monkeypatch.setattr(tool_utils_module, "ToolNode", lambda tools, **kwargs: _FakeToolNode())
    run_tools = make_tool_runner([])
    result = await run_tools({"messages": []})
    tool_msg = result["messages"][0]
    assert tool_msg.content == [{"type": "text", "text": "took screenshot"}]
