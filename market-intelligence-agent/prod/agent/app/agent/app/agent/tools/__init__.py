"""Tool registry — Phase 2 (local dev validation).

MCP stdio tools (crm, yfinance, filesystem, browser) are disabled here because
they spawn subprocesses via `uvx`/`npx`, which aren't available in the AgentCore
container. They will be re-enabled in Phase 4 as HTTPS-callable tools via
AgentCore Gateway. Until then, only the native LangChain tools are active.

Dev's full registry lives unchanged in the parent project — only this prod copy
is trimmed.
"""
from app.agent.tools.emails import send_email_tool
from app.agent.tools.memory import (
    save_memory_tool,
    recall_memory_tool,
    list_memories_tool,
)

# --- Phase 4 will restore these via AgentCore Gateway ---
# from app.agent.tools.mcp_clients.mcp_client import crm_tool
# from app.agent.tools.mcp_clients.yfinance_client import (
#     yf_quote_tool, yf_history_tool, yf_news_tool,
# )
# from app.agent.tools.mcp_clients.filesystem_client import (
#     fs_read_file_tool, fs_list_dir_tool, fs_write_file_tool,
# )
# from app.agent.tools.mcp_clients.browser_client import (
#     browser_navigate_tool, browser_snapshot_tool, browser_screenshot_tool,
# )

TOOLS = [
    send_email_tool,
    save_memory_tool,
    recall_memory_tool,
    list_memories_tool,
]

READ_ONLY_TOOLS: set[str] = {
    "recall_memory",
    "list_memories",
}

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
    "save_memory_tool",
    "recall_memory_tool",
    "list_memories_tool",
]
