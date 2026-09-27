"""Market Desk display envelope: reshapes a specialist's ToolMessage into
{"summary": <original text, unchanged>, "displays": [...]} so the frontend can
render a table/chart/card instead of a plain-text tool card.

Scoped to the multi-agent graph only, via MarketDeskDisplayMiddleware, wired
per-specialist in portfolio_agent.py / finance_agent.py / rag_agent.py /
browser_agent.py. Never imported by app/agent/graph.py (single-agent): the two
tools this touches that ARE shared instances with the single-agent graph
(search_knowledge_base_tool, browser_screenshot_tool) must keep their own
return value untouched for Streamlit/voice — this middleware only ever
rewrites the copy of ToolMessage.content that flows through this graph.

The `summary` field is always the original tool text, verbatim — never a
normalizer's own rewrite — so the LLM's next-turn reasoning is provably
unaffected by any of this. A normalizer's only job is to produce `displays`
from that same text; if it fails, the ToolMessage is left exactly as it was
(fail open — a broken display must never break the answer).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

ToolResult = ToolMessage | Command[Any]
# (original text, tool call args) -> list of {"type": ..., ...} display payloads
Normalizer = Callable[[str, dict], list[dict]]

# Populated by Tasks 2-5, one entry per displayable tool name.
DISPLAY_NORMALIZERS: dict[str, Normalizer] = {}


def _content_text(content: Any) -> str:
    """ToolMessage.content is a plain string for tools that return a Python
    str/dict directly (portfolio_metrics, concentration_screen,
    search_knowledge_base), but a list of MCP content blocks for MCP-backed
    tools (yfinance_*, browser_take_screenshot) — [{"type": "text", "text":
    ...}, ...]. Every normalizer receives plain text either way."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)


class MarketDeskDisplayMiddleware(AgentMiddleware):
    """Looks up the tool name in DISPLAY_NORMALIZERS; if found, replaces
    ToolMessage.content with the envelope. Unregistered tools and non-
    ToolMessage results (e.g. a Command from another middleware) pass
    through untouched."""

    @staticmethod
    def _envelope(result: ToolResult, args: dict) -> ToolResult:
        if not isinstance(result, ToolMessage):
            return result
        normalizer = DISPLAY_NORMALIZERS.get(result.name or "")
        if normalizer is None:
            return result
        text = _content_text(result.content)
        try:
            displays = normalizer(text, args)
        except Exception:
            logger.exception("display normalizer failed for tool %r", result.name)
            return result
        result.content = json.dumps({"summary": text, "displays": displays})
        return result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolResult],
    ) -> ToolResult:
        return self._envelope(handler(request), request.tool_call.get("args", {}))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolResult]],
    ) -> ToolResult:
        return self._envelope(await handler(request), request.tool_call.get("args", {}))


market_desk_display = MarketDeskDisplayMiddleware()


def normalize_portfolio(text: str, args: dict) -> list[dict]:
    data = json.loads(text)
    positions = data["positions"]
    table = {
        "type": "portfolio_table",
        "positions": [
            {
                "ticker": p["ticker"], "shares": p["shares"], "price": p["price"],
                "market_value": p["market_value"], "cost_basis": p["cost_basis"],
                "unrealized_pnl": p["unrealized_pnl"], "unrealized_pnl_pct": p["unrealized_pnl_pct"],
                "weight_pct": p["weight_pct"], "sector": p["sector"],
            }
            for p in positions
        ],
        "totals": data["totals"],
    }
    chart = {
        "type": "portfolio_chart",
        "slices": [{"ticker": p["ticker"], "weight_pct": p["weight_pct"]} for p in positions],
    }
    return [table, chart]


DISPLAY_NORMALIZERS["portfolio_metrics"] = normalize_portfolio
