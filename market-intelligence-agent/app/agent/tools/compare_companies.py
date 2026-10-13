"""`compare_companies` — side-by-side metrics and rebased price series for
2-4 tickers, computed in Python so the comparison card never shows a number
the LLM produced. Data comes through the same yfinance tools the finance
agent uses (yfmcp locally, the yfinance Lambda behind the Gateway)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools.concentration import parse_tool_payload, price_from_quote

Period = Literal["1mo", "3mo", "6mo", "1y"]


def _r(value: float) -> float:
    return round(value + 0.0, 2)


def _markdown_closes(text: str) -> list[tuple[str, float]]:
    closes = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not cells[0][:4].isdigit():
            continue  # header and ':--' separator rows
        try:
            closes.append((cells[0][:10], float(cells[4])))
        except ValueError:
            continue
    return closes


def parse_closes(result: Any) -> list[tuple[str, float]]:
    """(date, close) pairs from yfmcp's markdown table (stdio) or the
    yfinance Lambda's row list (Gateway)."""
    if isinstance(result, list) and result and all(isinstance(b, dict) and "type" in b for b in result):
        result = "".join(b.get("text", "") for b in result if b.get("type") == "text")
    if isinstance(result, str) and "|" in result:
        return _markdown_closes(result)
    rows = parse_tool_payload(result)
    return [(str(r["date"])[:10], float(r["close"])) for r in rows or [] if r.get("close") is not None]


def _range_position(price: float, low: Any, high: Any) -> float | None:
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)) or high <= low:
        return None
    return _r((price - low) / (high - low) * 100)


async def compare_companies(
    *,
    symbols: list[str],
    period: str,
    get_info: Callable[[str], Awaitable[dict]],
    get_closes: Callable[[str, str], Awaitable[list[tuple[str, float]]]],
) -> dict:
    wanted = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    if not 2 <= len(wanted) <= 4:
        return {"error": f"compare_companies needs 2 to 4 distinct tickers, got {wanted}."}

    infos = await asyncio.gather(*(get_info(s) for s in wanted), return_exceptions=True)
    histories = await asyncio.gather(*(get_closes(s, period) for s in wanted), return_exceptions=True)

    companies, missing = [], []
    for symbol, info, closes in zip(wanted, infos, histories):
        try:
            if isinstance(info, BaseException) or isinstance(closes, BaseException) or not closes:
                raise ValueError(symbol)
            price = price_from_quote(info)
        except ValueError:
            missing.append(symbol)
            continue
        base = closes[0][1]
        companies.append({
            "symbol": symbol,
            "name": info.get("shortName") or info.get("longName") or symbol,
            "sector": info.get("sector"),
            "currency": info.get("currency") or "USD",
            "price": _r(price),
            "market_cap": info.get("marketCap"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "range_position_pct": _range_position(price, info.get("fiftyTwoWeekLow"), info.get("fiftyTwoWeekHigh")),
            "period_return_pct": _r((closes[-1][1] - base) / base * 100),
            "points": [{"date": d, "value": _r(c / base * 100)} for d, c in closes],
        })

    if len(companies) < 2:
        return {"error": f"Need at least 2 tickers with market data; missing: {', '.join(missing)}."}
    return {"period": period, "companies": companies, "missing": missing}


class CompareCompaniesInput(BaseModel):
    symbols: list[str] = Field(description="2 to 4 ticker symbols, e.g. ['NVDA', 'AMD'].")
    period: Period = Field(default="6mo", description="Window for the performance chart: 1mo, 3mo, 6mo or 1y.")


@tool("compare_companies", args_schema=CompareCompaniesInput)
async def compare_companies_tool(symbols: list[str], period: str = "6mo") -> dict:
    """Compare 2-4 companies side by side: price, market cap, P/E, position
    in the 52-week range, and performance over `period` with a rebased
    (=100) price chart. Use this for ANY "compare X and Y" / "X vs Y"
    question -- do not fetch each ticker separately."""
    from app.agent.mcp_clients.yfinance_client import yf_history_tool, yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"

    async def get_info(symbol: str) -> dict:
        return parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: symbol}))

    async def get_closes(symbol: str, window: str) -> list[tuple[str, float]]:
        return parse_closes(await yf_history_tool.ainvoke({symbol_arg: symbol, "period": window}))

    return await compare_companies(symbols=symbols, period=period, get_info=get_info, get_closes=get_closes)
