from app.agent.tools.emails import send_email_tool
from app.agent.tools.memory import (
    save_memory_tool,
    recall_memory_tool,
    list_memories_tool,
)
from app.agent.tools.mcp_clients.mcp_client import crm_tool
from app.agent.tools.mcp_clients.yfinance_client import (
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
)
from app.agent.tools.mcp_clients.filesystem_client import (
    fs_read_file_tool,
    fs_list_dir_tool,
    fs_write_file_tool,
)
from app.agent.tools.mcp_clients.browser_client import (
    browser_navigate_tool,
    browser_snapshot_tool,
    browser_screenshot_tool,
)

TOOLS = [
    send_email_tool,
    crm_tool,
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
    fs_read_file_tool,
    fs_list_dir_tool,
    fs_write_file_tool,
    browser_navigate_tool,
    browser_snapshot_tool,
    browser_screenshot_tool,
    save_memory_tool,
    recall_memory_tool,
    list_memories_tool,
]

READ_ONLY_TOOLS: set[str] = {
    "read_query",
    "yfinance_get_ticker_info",
    "yfinance_get_price_history",
    "yfinance_get_ticker_news",
    "read_text_file",
    "list_directory",
    "browser_navigate",
    "browser_snapshot",
    "browser_take_screenshot",
    "recall_memory",
    "list_memories",
}

# Guard against silent drift: if an upstream MCP server renames a tool, the name
# in READ_ONLY_TOOLS no longer matches anything in TOOLS and the tool gets gated
# as a side effect. Fail loud at import instead.
_TOOL_NAMES = {t.name for t in TOOLS}
_missing = READ_ONLY_TOOLS - _TOOL_NAMES
if _missing:
    raise RuntimeError(
        f"READ_ONLY_TOOLS contains names not present in TOOLS: {sorted(_missing)}. "
        f"Known tool names: {sorted(_TOOL_NAMES)}"
    )

__all__ = [
    "TOOLS",
    "READ_ONLY_TOOLS",
    "send_email_tool",
    "crm_tool",
    "yf_quote_tool",
    "yf_history_tool",
    "yf_news_tool",
    "fs_read_file_tool",
    "fs_list_dir_tool",
    "fs_write_file_tool",
    "browser_navigate_tool",
    "browser_snapshot_tool",
    "browser_screenshot_tool",
    "save_memory_tool",
    "recall_memory_tool",
    "list_memories_tool",
]
