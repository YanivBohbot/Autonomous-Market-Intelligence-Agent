from app.agent.tools.emails import send_email_tool
from app.agent.tools.mcp_clients.mcp_client import crm_tool
from app.agent.tools.mcp_clients.yfinance_client import (
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
)

TOOLS = [
    send_email_tool,
    crm_tool,
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
]

READ_ONLY_TOOLS: set[str] = {"crm_query", "yf_quote", "yf_history", "yf_news"}

__all__ = [
    "TOOLS",
    "READ_ONLY_TOOLS",
    "send_email_tool",
    "crm_tool",
    "yf_quote_tool",
    "yf_history_tool",
    "yf_news_tool",
]
