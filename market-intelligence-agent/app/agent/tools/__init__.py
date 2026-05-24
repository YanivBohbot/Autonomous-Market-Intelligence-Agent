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
# Browser tools are stdio-only (Playwright MCP runs as a subprocess). In
# AgentCore Gateway mode there is no browser target, so the registry has no
# matching tools and select_tool() would raise at import. Defer that error
# to actual call sites instead.
try:
    from app.agent.tools.mcp_clients.browser_client import (
        browser_navigate_tool,
        browser_snapshot_tool,
        browser_screenshot_tool,
    )
    _BROWSER_TOOLS = [browser_navigate_tool, browser_snapshot_tool, browser_screenshot_tool]
except RuntimeError:
    browser_navigate_tool = browser_snapshot_tool = browser_screenshot_tool = None
    _BROWSER_TOOLS = []

TOOLS = [
    send_email_tool,
    crm_tool,
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
    fs_read_file_tool,
    fs_list_dir_tool,
    fs_write_file_tool,
    *_BROWSER_TOOLS,
    save_memory_tool,
    recall_memory_tool,
    list_memories_tool,
]

_BASE_READ_ONLY_TOOLS: set[str] = {
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
# Drop browser tool names if the browser MCP isn't loaded so the integrity
# check below doesn't fire on AgentCore Gateway mode (no browser target).
READ_ONLY_TOOLS: set[str] = _BASE_READ_ONLY_TOOLS - (
    set() if _BROWSER_TOOLS else {"browser_navigate", "browser_snapshot", "browser_take_screenshot"}
)

def _base_name(name: str) -> str:
    """Strip the AgentCore Gateway `<target>___` prefix to the bare tool name."""
    return name.rsplit("___", 1)[-1]


def is_read_only(tool_name: str) -> bool:
    """READ_ONLY_TOOLS membership check that tolerates the Gateway's
    `<target>___<tool>` prefixed names. Used by the approval node in
    graph.py to skip the HITL interrupt for read-only tool calls."""
    return _base_name(tool_name) in READ_ONLY_TOOLS


# Guard against silent drift: if an upstream MCP server renames a tool, the name
# in READ_ONLY_TOOLS no longer matches anything in TOOLS and the tool gets gated
# as a side effect. Fail loud at import instead.
_TOOL_NAMES = {_base_name(t.name) for t in TOOLS}
_missing = READ_ONLY_TOOLS - _TOOL_NAMES
if _missing:
    raise RuntimeError(
        f"READ_ONLY_TOOLS contains names not present in TOOLS: {sorted(_missing)}. "
        f"Known tool names: {sorted(_TOOL_NAMES)}"
    )

__all__ = [
    "TOOLS",
    "READ_ONLY_TOOLS",
    "is_read_only",
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
