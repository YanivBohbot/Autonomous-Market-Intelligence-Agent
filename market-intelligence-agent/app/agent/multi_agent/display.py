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
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
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

# The news card is unreadable past a handful of items; capped here regardless
# of the `limit` the model passed to yfinance_get_ticker_news (a display
# concern, not a data concern — the tool's own limit stays model-controlled).
MAX_NEWS_ITEMS = 7


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


def normalize_concentration(text: str, args: dict) -> list[dict]:
    data = json.loads(text)
    breaches = data.get("breaches") or []
    if not breaches:
        return []
    return [{
        "type": "concentration_alert",
        "threshold_pct": data["threshold_pct"],
        "breaches": [
            {"label": b["label"], "ticker": b["ticker"], "weight_pct": b["weight_pct"], "market_value": b["market_value"]}
            for b in breaches
        ],
    }]


DISPLAY_NORMALIZERS["concentration_screen"] = normalize_concentration


def _row_ticker(args: dict) -> str:
    return str(args.get("symbol") or args.get("ticker") or "").upper()


def normalize_price_history(text: str, args: dict) -> list[dict]:
    points = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or not cells[0][:4].isdigit():
            continue  # skips the header row ("Date") and the ":---" separator row
        try:
            close = float(cells[4])
        except ValueError:
            continue
        points.append({"date": cells[0][:10], "close": close})
    if not points:
        return []
    return [{"type": "price_chart", "ticker": _row_ticker(args), "points": points}]


def normalize_ticker_info(text: str, args: dict) -> list[dict]:
    data = json.loads(text)
    price = data.get("currentPrice") or data.get("regularMarketPrice")
    if price is None:
        return []
    return [{
        "type": "ticker_info", "ticker": _row_ticker(args) or str(data.get("symbol") or ""),
        "name": data.get("shortName") or data.get("longName") or "",
        "sector": data.get("sector"), "industry": data.get("industry"),
        "current_price": float(price), "currency": data.get("currency") or "USD",
        "market_cap": data.get("marketCap"), "fifty_two_week_low": data.get("fiftyTwoWeekLow"),
        "fifty_two_week_high": data.get("fiftyTwoWeekHigh"),
    }]


def normalize_ticker_news(text: str, args: dict) -> list[dict]:
    entries = json.loads(text)
    items = []
    for entry in entries:
        content = entry.get("content", {}) if isinstance(entry, dict) else {}
        title = content.get("title")
        url = (content.get("canonicalUrl") or {}).get("url") or (content.get("clickThroughUrl") or {}).get("url")
        if not title or not url:
            continue
        items.append({
            "title": title, "summary": content.get("summary") or "",
            "source": (content.get("provider") or {}).get("displayName") or "",
            "url": url, "published_at": content.get("pubDate") or "",
        })
    if not items:
        return []
    return [{"type": "ticker_news", "items": items[:MAX_NEWS_ITEMS]}]


DISPLAY_NORMALIZERS["yfinance_get_price_history"] = normalize_price_history
DISPLAY_NORMALIZERS["yfinance_get_ticker_info"] = normalize_ticker_info
DISPLAY_NORMALIZERS["yfinance_get_ticker_news"] = normalize_ticker_news


_SOURCE_HEADER = re.compile(r"\[Source: (.*?), page (.*?)\]\s*")
_PNG_PATH = re.compile(r"([\w./\\-]+\.png)")


def normalize_rag_sources(text: str, args: dict) -> list[dict]:
    matches = list(_SOURCE_HEADER.finditer(text))
    if not matches:
        return []
    sources = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sources.append({"filename": m.group(1), "page": m.group(2), "excerpt": text[start:end].strip()})
    return [{"type": "rag_sources", "sources": sources}]


def normalize_screenshot(text: str, args: dict) -> list[dict]:
    match = _PNG_PATH.search(text)
    if not match:
        return []
    filename = Path(match.group(1)).name
    return [{"type": "screenshot", "url": f"/workspace/screenshots/{filename}"}]


DISPLAY_NORMALIZERS["search_knowledge_base"] = normalize_rag_sources
DISPLAY_NORMALIZERS["browser_take_screenshot"] = normalize_screenshot
