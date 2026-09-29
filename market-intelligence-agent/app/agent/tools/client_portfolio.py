"""`client_portfolio` — deterministic single-client portfolio snapshot.

Same rationale as concentration_screen (concentration.py): live QA showed
gpt-4o-mini skip the documented portfolio recipe (read holdings -> fetch live
prices -> portfolio_metrics) for a plain "what's this client's portfolio
worth" question, instead writing its own SQL --
`SUM(holdings.shares * holdings.avg_cost)`, cost basis, not market value --
giving $64,179 for Margaret Collins instead of the correct $156,780. Nothing
for the LLM to shortcut here: it passes a client name, the tool resolves the
client, loads holdings + sector, fetches live prices, and returns the same
shape compute_portfolio_metrics always has.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools.concentration import build_holdings_query, parse_tool_payload, price_from_quote
from app.agent.tools.finance_calc import Position, compute_portfolio_metrics


async def load_client_portfolio(
    *,
    run_sql: Callable[[str], Awaitable[list[dict]]],
    get_price: Callable[[str], Awaitable[float]],
    client_name: str,
) -> dict:
    rows = await run_sql(build_holdings_query(risk_profile=None, client_names=[client_name]))
    if not rows:
        return {"error": f"No client matching {client_name!r} found, or they have no holdings."}

    matched_names = sorted({r["name"] for r in rows})
    if len(matched_names) > 1:
        return {"error": f"{client_name!r} matches multiple clients: {', '.join(matched_names)}. Ask which one."}

    tickers = sorted({r["ticker"] for r in rows})
    results = await asyncio.gather(*(get_price(t) for t in tickers), return_exceptions=True)
    failed = [t for t, r in zip(tickers, results) if isinstance(r, BaseException)]
    if failed:
        raise ValueError(f"could not get a current price for: {', '.join(failed)}")
    prices = dict(zip(tickers, (float(r) for r in results)))

    positions = [
        Position(ticker=r["ticker"], shares=r["shares"], avg_cost=r["avg_cost"], price=prices[r["ticker"]], sector=r["sector"])
        for r in rows
    ]
    result = compute_portfolio_metrics(positions)
    result["client_name"] = matched_names[0]
    return result


class ClientPortfolioInput(BaseModel):
    client_name: str = Field(description="Full or partial client name, e.g. 'Margaret Collins' or 'Collins'.")


@tool("client_portfolio", args_schema=ClientPortfolioInput)
async def client_portfolio_tool(client_name: str) -> dict:
    """Compute one named client's full portfolio snapshot -- market value,
    cost basis, unrealized P&L, weights and sector allocation. Use this for
    ANY question about a named client's portfolio value, holdings, or
    performance. The tool itself resolves the client, loads their holdings
    from the database, and fetches live prices -- do NOT query holdings or
    prices first, and do NOT compute the total yourself."""
    from app.agent.tools.mcp_clients.mcp_client import crm_tool
    from app.agent.tools.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"

    async def run_sql(sql: str) -> list[dict]:
        return parse_tool_payload(await crm_tool.ainvoke({"query": sql}))

    async def get_price(ticker: str) -> float:
        return price_from_quote(parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: ticker})))

    return await load_client_portfolio(run_sql=run_sql, get_price=get_price, client_name=client_name)
