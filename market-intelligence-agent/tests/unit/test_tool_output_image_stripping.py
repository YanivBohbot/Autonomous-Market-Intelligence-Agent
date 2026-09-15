"""Regression test: MCP tools that return multimodal content (e.g.
browser_take_screenshot returning a text block plus an inline base64 image)
must have the image part stripped before the ToolMessage re-enters
checkpointed state.

Root cause: OpenAI's Chat Completions API rejects image content on
tool-role messages ("Image URLs are only allowed for messages with role
'user'"). Once such a ToolMessage lands in the checkpoint, every later turn
on that thread resends full history and fails with a 400 forever — the same
class of failure as the thread-poisoning bug in test_tool_error_handling.py,
just triggered by tool *output shape* instead of a tool *exception*.
"""
import pytest
from langchain_core.messages import ToolMessage

from app.agent.graph import _strip_image_content


def test_strips_image_parts_keeps_text():
    content = [
        {"type": "text", "text": "### Result\n- [Screenshot of viewport](screenshots/x.png)"},
        {"type": "image", "data": "base64...", "mimeType": "image/png"},
    ]
    stripped = _strip_image_content(content)
    assert stripped == [content[0]]


def test_strips_openai_style_image_url_parts():
    content = [
        {"type": "text", "text": "screenshot taken"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
    ]
    stripped = _strip_image_content(content)
    assert stripped == [content[0]]


def test_leaves_plain_string_content_untouched():
    assert _strip_image_content("plain text result") == "plain text result"


def test_leaves_text_only_list_untouched():
    content = [{"type": "text", "text": "no images here"}]
    assert _strip_image_content(content) == content


@pytest.mark.anyio
async def test_run_tools_sanitizes_tool_message_content(monkeypatch):
    from app.agent import graph as graph_module

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
                        name="browser_take_screenshot",
                    )
                ]
            }

    monkeypatch.setattr(graph_module, "_tool_node", _FakeToolNode())
    result = await graph_module.run_tools({"messages": []})
    tool_msg = result["messages"][0]
    assert tool_msg.content == [{"type": "text", "text": "took screenshot"}]
