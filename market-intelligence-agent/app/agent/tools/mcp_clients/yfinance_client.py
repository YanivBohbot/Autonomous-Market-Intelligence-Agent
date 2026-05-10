"""Yahoo Finance MCP client — selects yfinance-server tools out of the shared registry.

Public symbols preserved: `yf_quote_tool`, `yf_history_tool`, `yf_news_tool`. Schema
conversion (single-arg vs multi-arg) is now handled automatically by
langchain-mcp-adapters; the legacy Tool / StructuredTool decisions are gone.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.registry import get_mcp_tools

logger = logging.getLogger(__name__)

QUOTE_TOOL_NAME = "yfinance_get_ticker_info"
HISTORY_TOOL_NAME = "yfinance_get_price_history"
NEWS_TOOL_NAME = "yfinance_get_ticker_news"


def _select(name: str) -> BaseTool:
    for tool in get_mcp_tools():
        if tool.name == name:
            return tool
    raise RuntimeError(
        f"Yahoo Finance MCP tool {name!r} not found in registry; check server config."
    )


yf_quote_tool: BaseTool = _select(QUOTE_TOOL_NAME)
yf_history_tool: BaseTool = _select(HISTORY_TOOL_NAME)
yf_news_tool: BaseTool = _select(NEWS_TOOL_NAME)
