"""Native replacement for yfmcp's `get_ticker_news`.

Yahoo's per-ticker news endpoint (`yf.Ticker(sym).news` / `.get_news()`, which
yfmcp calls) returns 0 articles for every ticker; the search endpoint
(`yf.Search`) still returns them. Same tool name and same JSON shape as yfmcp
(`[{id, content: {title, summary, pubDate, provider, canonicalUrl}}]`) so
`display.normalize_ticker_news` and the Market Desk news card are unchanged.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from langchain_core.tools import tool
from pydantic import BaseModel, Field

NEWS_TOOL_NAME = "yfinance_get_ticker_news"


def _default_search(symbol: str, count: int) -> tuple[list[dict], str]:
    """(news items, company name) from one Yahoo search."""
    import yfinance as yf

    result = yf.Search(symbol, news_count=count)
    quote = next((q for q in result.quotes or [] if q.get("symbol") == symbol), {})
    return result.news or [], quote.get("shortname") or quote.get("longname") or ""


def _to_yfmcp_item(item: dict) -> dict[str, Any]:
    published = item.get("providerPublishTime")
    pub_date = (
        datetime.fromtimestamp(published, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if isinstance(published, (int, float))
        else ""
    )
    return {
        "id": item.get("uuid", ""),
        "content": {
            "title": item.get("title", ""),
            "summary": "",
            "pubDate": pub_date,
            "provider": {"displayName": item.get("publisher", "")},
            "canonicalUrl": {"url": item.get("link", "")},
        },
    }


def fetch_ticker_news(
    symbol: str,
    limit: int = 5,
    search: Callable[[str, int], tuple[list[dict], str]] = _default_search,
) -> list[dict[str, Any]]:
    """Headlines about `symbol`, in Yahoo's order.

    A ticker search also returns general market stories (earnings summaries
    of other companies list dozens of `relatedTickers`), so a story is kept
    only when its title names the ticker or the company's first name word
    ("Nvidia", "Goldman").
    """
    symbol = symbol.strip().upper()
    news, company = search(symbol, 20)
    names = [re.escape(symbol)]
    if company:
        names.append(re.escape(company.split()[0].strip(",.")))
    about = re.compile(r"\b(" +"|".join(names) + ")", re.IGNORECASE)
    items = [i for i in news if i.get("title") and i.get("link") and about.search(i["title"])]
    return [_to_yfmcp_item(i) for i in items[:limit]]


class TickerNewsInput(BaseModel):
    symbol: str = Field(description="Stock ticker symbol (e.g., 'AAPL', 'GOOGL', 'MSFT').")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum number of articles.")


@tool(NEWS_TOOL_NAME, args_schema=TickerNewsInput)
async def ticker_news_tool(symbol: str, limit: int = 5) -> str:
    """Fetch recent news headlines for a specific stock (title, publisher,
    link, publication date) as a JSON array. Use this to track company
    announcements, market sentiment and breaking news."""
    news = await asyncio.to_thread(fetch_ticker_news, symbol, limit)
    return json.dumps(news)
