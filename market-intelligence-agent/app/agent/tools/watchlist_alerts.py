"""`watchlist_alerts` — which client price alerts have fired, are close, or
are still waiting, against live prices. The status logic lives here so the
alert card is never an LLM's reading of a price table."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools.concentration import parse_tool_payload, price_from_quote

_ORDER = {"triggered": 0, "near": 1, "watching": 2}


def build_watchlist_query(client_names: list[str] | None) -> str:
    sql = (
        "SELECT c.name AS client, w.ticker, co.name AS company, w.alert_price, w.direction "
        "FROM watchlists w JOIN clients c ON c.client_id = w.client_id "
        "JOIN companies co ON co.ticker = w.ticker"
    )
    if client_names:
        likes = " OR ".join("c.name LIKE '%" + n.replace("'", "''") + "%'" for n in client_names)
        sql += f" WHERE ({likes})"
    return sql + " ORDER BY c.name, w.ticker"


def classify(price: float, alert_price: float, direction: str, near_pct: float) -> tuple[str, float]:
    distance = round((price - alert_price) / alert_price * 100, 2)
    crossed = price >= alert_price if direction == "above" else price <= alert_price
    if crossed:
        return "triggered", distance
    return ("near" if abs(distance) <= near_pct else "watching"), distance


async def watchlist_alerts(
    *,
    run_sql: Callable[[str], Awaitable[list[dict]]],
    get_price: Callable[[str], Awaitable[float]],
    client_names: list[str] | None = None,
    near_pct: float = 5.0,
) -> dict:
    alerts = await run_sql(build_watchlist_query(client_names))
    tickers = sorted({a["ticker"] for a in alerts})
    results = await asyncio.gather(*(get_price(t) for t in tickers), return_exceptions=True)
    prices = {t: float(r) for t, r in zip(tickers, results) if not isinstance(r, BaseException)}

    rows = []
    for a in alerts:
        if a["ticker"] not in prices:
            continue
        status, distance = classify(prices[a["ticker"]], float(a["alert_price"]), a["direction"], near_pct)
        rows.append({**a, "price": prices[a["ticker"]], "status": status, "distance_pct": distance})
    rows.sort(key=lambda r: (_ORDER[r["status"]], abs(r["distance_pct"]), r["client"]))
    return {"near_pct": float(near_pct), "rows": rows, "unpriced": sorted(set(tickers) - set(prices))}


class WatchlistAlertsInput(BaseModel):
    client_names: list[str] | None = Field(default=None, description="Only these clients (full or partial names). Omit for all clients.")
    near_pct: float = Field(default=5.0, gt=0, le=50, description="Within this % of the alert price counts as 'near'.")


@tool("watchlist_alerts", args_schema=WatchlistAlertsInput)
async def watchlist_alerts_tool(client_names: list[str] | None = None, near_pct: float = 5.0) -> dict:
    """Check clients' watchlist price alerts against live prices: which are
    triggered, near (within near_pct) or still watching. Use for any
    watchlist / price-alert question. Loads the alerts and prices itself --
    no SQL or price lookups first."""
    from app.agent.mcp_clients.crm_client import crm_tool
    from app.agent.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"

    async def run_sql(sql: str) -> list[dict]:
        return parse_tool_payload(await crm_tool.ainvoke({"query": sql}))

    async def get_price(ticker: str) -> float:
        return price_from_quote(parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: ticker})))

    return await watchlist_alerts(run_sql=run_sql, get_price=get_price, client_names=client_names, near_pct=near_pct)
