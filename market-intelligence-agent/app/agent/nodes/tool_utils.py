from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode


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


def make_tool_runner(tools):
    """Factory: build an async run_tools(state) node bound to `tools`,
    applying the same image-content sanitization as app.agent.graph.run_tools."""
    tool_node = ToolNode(tools, handle_tool_errors=True)

    async def run_tools(state):
        result = await tool_node.ainvoke(state)
        for msg in result.get("messages", []):
            if isinstance(msg, ToolMessage):
                msg.content = strip_image_content(msg.content)
        return result

    return run_tools
