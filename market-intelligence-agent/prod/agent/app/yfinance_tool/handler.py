"""Yahoo Finance MCP server (Lambda-hosted via AgentCore Gateway).

Exposes three read-only tools whose names match the dev project's existing
yfinance MCP server exactly, so the agent's system prompt and READ_ONLY_TOOLS
allowlist work without modification:

- yfinance_get_ticker_info(ticker)
- yfinance_get_price_history(ticker, period="1mo")
- yfinance_get_ticker_news(ticker, limit=5)

Each tool wraps yfinance calls in try/except: on failure we return a JSON-
serializable {"error": "..."} dict rather than raising, so Gateway returns a
clean tool response instead of a 500. A 10-second socket timeout guards against
Yahoo's occasional anti-scraping hangs.
"""

from __future__ import annotations

import socket
from typing import Any

import yfinance as yf
from mcp.server.fastmcp import FastMCP

# Yahoo's endpoints occasionally hang under anti-scraping. Bound every network
# call from yfinance with a 10s socket timeout (the dev project does the same
# via YFINANCE_TIMEOUT_S in core/config.py).
socket.setdefaulttimeout(10)

app = FastMCP("yfinance")


@app.tool()
def yfinance_get_ticker_info(ticker: str) -> dict[str, Any]:
    """Get current ticker info (price, volume, market cap, etc.) for a stock symbol."""
    try:
        info = yf.Ticker(ticker).info
        # yfinance returns a dict; ensure JSON-serializable
        return {k: v for k, v in info.items() if isinstance(v, (str, int, float, bool, type(None)))}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"yfinance_get_ticker_info({ticker!r}) failed: {exc}"}


@app.tool()
def yfinance_get_price_history(ticker: str, period: str = "1mo") -> Any:
    """Get historical OHLCV price data for a stock symbol over a period."""
    try:
        df = yf.Ticker(ticker).history(period=period)
        # Convert DataFrame to JSON-friendly list of dicts; preserve index as date string
        records = []
        for ts, row in df.iterrows():
            rec = {"date": str(ts)}
            for col in df.columns:
                val = row[col]
                rec[col] = float(val) if val is not None else None
            records.append(rec)
        return records
    except Exception as exc:  # noqa: BLE001
        return {"error": f"yfinance_get_price_history({ticker!r}, {period!r}) failed: {exc}"}


@app.tool()
def yfinance_get_ticker_news(ticker: str, limit: int = 5) -> Any:
    """Get recent news articles for a stock symbol."""
    try:
        news = yf.Ticker(ticker).news or []
        return news[:limit]
    except Exception as exc:  # noqa: BLE001
        return {"error": f"yfinance_get_ticker_news({ticker!r}, limit={limit}) failed: {exc}"}
