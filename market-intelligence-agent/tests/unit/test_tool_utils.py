"""Unit tests for the shared tool_utils module, extracted so both the
single-agent graph and the multi-agent specialists can sanitize MCP tool
output without duplicating the image-stripping logic."""
from app.agent.nodes.tool_utils import strip_image_content


def test_strips_image_parts_keeps_text():
    content = [
        {"type": "text", "text": "result"},
        {"type": "image", "data": "base64...", "mimeType": "image/png"},
    ]
    assert strip_image_content(content) == [content[0]]


def test_leaves_plain_string_content_untouched():
    assert strip_image_content("plain text result") == "plain text result"
