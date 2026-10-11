"""Unit tests for strip_image_content (app/agent/middleware.py), which the
browser specialist's middleware uses to drop image parts from MCP tool
output before it re-enters the conversation."""
from app.agent.middleware import strip_image_content


def test_strips_image_parts_keeps_text():
    content = [
        {"type": "text", "text": "result"},
        {"type": "image", "data": "base64...", "mimeType": "image/png"},
    ]
    assert strip_image_content(content) == [content[0]]


def test_leaves_plain_string_content_untouched():
    assert strip_image_content("plain text result") == "plain text result"
