"""yfinance MCP Lambda — three read-only tools for ticker data.

Invoked by AgentCore Gateway with `{"tool": <name>, "args": {...}}`.
Returns `{"ok": True, "result": ...}` on success or `{"ok": False, "error": "..."}`
on failure. Gateway wraps the result into the MCP tool-call response shape.

Mirrors the yfmcp tools exposed locally in dev:
- yfinance_get_ticker_info(ticker: str)
- yfinance_get_price_history(ticker: str, period: str = "1mo")
- yfinance_get_ticker_news(ticker: str, limit: int = 5)
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def _info(ticker: str) -> dict[str, Any]:
    t = yf.Ticker(ticker)
    info = t.info or {}
    keep = (
        "symbol", "shortName", "longName", "currency", "exchange",
        "sector", "industry", "marketCap", "regularMarketPrice",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "trailingPE", "forwardPE",
        "dividendYield", "beta", "longBusinessSummary",
    )
    return {k: info.get(k) for k in keep}


def _history(ticker: str, period: str = "1mo") -> list[dict[str, Any]]:
    df = yf.Ticker(ticker).history(period=period)
    rows = []
    for ts, row in df.iterrows():
        rows.append({
            "date": ts.isoformat(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        })
    return rows


def _news(ticker: str, limit: int = 5) -> list[dict[str, Any]]:
    # yf.Ticker(t).news returns 0 articles for every ticker (dead Yahoo
    # endpoint); yf.Search still works. Same filter and output shape as the
    # agent's app/agent/mcp_clients/yfinance_news.py, so the news card renders.
    symbol = ticker.strip().upper()
    result = yf.Search(symbol, news_count=20)
    quote = next((q for q in result.quotes or [] if q.get("symbol") == symbol), {})
    company = quote.get("shortname") or quote.get("longname") or ""
    names = [re.escape(symbol)]
    if company:
        names.append(re.escape(company.split()[0].strip(",.")))
    about = re.compile(r"\b(" + "|".join(names) + ")", re.IGNORECASE)
    out = []
    for n in result.news or []:
        if not (n.get("title") and n.get("link") and about.search(n["title"])):
            continue
        published = n.get("providerPublishTime")
        out.append({
            "id": n.get("uuid", ""),
            "content": {
                "title": n["title"],
                "summary": "",
                "pubDate": datetime.fromtimestamp(published, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if isinstance(published, (int, float)) else "",
                "provider": {"displayName": n.get("publisher", "")},
                "canonicalUrl": {"url": n["link"]},
            },
        })
    return out[:limit]


_DISPATCH = {
    "yfinance_get_ticker_info":    lambda a: _info(a["ticker"]),
    "yfinance_get_price_history":  lambda a: _history(a["ticker"], a.get("period", "1mo")),
    "yfinance_get_ticker_news":    lambda a: _news(a["ticker"], int(a.get("limit", 5))),
}


def _tool_name_from_context(context) -> str | None:
    try:
        raw = context.client_context.custom["bedrockAgentCoreToolName"]
    except (AttributeError, KeyError, TypeError):
        return None
    return raw.split("___", 1)[1] if "___" in raw else raw


def lambda_handler(event, context):
    tool = _tool_name_from_context(context)
    args = event if isinstance(event, dict) else {}
    logger.info("yfinance lambda invoked: tool=%s", tool)
    fn = _DISPATCH.get(tool)
    if fn is None:
        return {"ok": False, "error": f"unknown tool: {tool!r}"}
    try:
        result = fn(args)
        return {"ok": True, "result": result}
    except KeyError as e:
        return {"ok": False, "error": f"missing required arg: {e.args[0]}"}
    except Exception as e:
        logger.exception("yfinance tool %s failed", tool)
        return {"ok": False, "error": str(e)}
