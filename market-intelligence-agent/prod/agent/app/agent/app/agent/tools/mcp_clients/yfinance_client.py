"""Yahoo Finance MCP client — selects yfinance-server tools out of the shared registry.

Public symbols preserved: `yf_quote_tool`, `yf_history_tool`, `yf_news_tool`. Schema
conversion (single-arg vs multi-arg) is now handled automatically by
langchain-mcp-adapters; the legacy Tool / StructuredTool decisions are gone.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.registry import select_tool

logger = logging.getLogger(__name__)

QUOTE_TOOL_NAME = "yfinance_get_ticker_info"
HISTORY_TOOL_NAME = "yfinance_get_price_history"
NEWS_TOOL_NAME = "yfinance_get_ticker_news"

yf_quote_tool: BaseTool = select_tool(QUOTE_TOOL_NAME, "Yahoo Finance")
yf_history_tool: BaseTool = select_tool(HISTORY_TOOL_NAME, "Yahoo Finance")
yf_news_tool: BaseTool = select_tool(NEWS_TOOL_NAME, "Yahoo Finance")
