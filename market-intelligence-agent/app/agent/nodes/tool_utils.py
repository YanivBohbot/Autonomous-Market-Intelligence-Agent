def strip_image_content(content):
    """Drop image parts from an MCP tool result before it re-enters the
    conversation: OpenAI rejects image content on tool-role messages (only
    'user' may carry images), and the frontend already gets the real PNG via
    the dedicated screenshot SSE event, so the LLM never needs the raw bytes.
    """
    if not isinstance(content, list):
        return content
    return [
        part for part in content
        if not (isinstance(part, dict) and part.get("type") in ("image", "image_url"))
    ]
