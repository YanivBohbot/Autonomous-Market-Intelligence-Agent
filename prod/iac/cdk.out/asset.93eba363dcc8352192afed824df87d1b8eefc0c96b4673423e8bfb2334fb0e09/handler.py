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
    items = yf.Ticker(ticker).news or []
    out = []
    for n in items[:limit]:
        out.append({
            "title": n.get("title"),
            "publisher": n.get("publisher"),
            "link": n.get("link"),
            "providerPublishTime": n.get("providerPublishTime"),
        })
    return out


_DISPATCH = {
    "yfinance_get_ticker_info":    lambda a: _info(a["ticker"]),
    "yfinance_get_price_history":  lambda a: _history(a["ticker"], a.get("period", "1mo")),
    "yfinance_get_ticker_news":    lambda a: _news(a["ticker"], int(a.get("limit", 5))),
}


def lambda_handler(event, context):
    logger.info("yfinance lambda invoked: tool=%s", event.get("tool"))
    tool = event.get("tool")
    args = event.get("args") or {}
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
