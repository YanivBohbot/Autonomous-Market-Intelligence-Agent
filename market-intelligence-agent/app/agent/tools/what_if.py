"""`simulate_portfolio_change` — a what-if on one client's portfolio.

Loads the real portfolio (live prices), applies hypothetical buys/sells in
Python, and returns before/after weights, totals, cash raised or needed, and
single-stock concentration before/after. A simulation only: nothing is ever
written to the client database."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator

from app.agent.tools.client_portfolio import load_client_portfolio
from app.agent.tools.concentration import parse_tool_payload, price_from_quote
from app.agent.tools.finance_calc import Position, compute_portfolio_metrics


class Trade(BaseModel):
    ticker: str = Field(description="Ticker to buy or sell, e.g. 'NVDA'.")
    action: Literal["buy", "sell"]
    pct: float | None = Field(default=None, gt=0, le=100, description="Sell this % of the current position (sell only).")
    shares: float | None = Field(default=None, gt=0, description="Number of shares to buy or sell.")

    @model_validator(mode="after")
    def _one_size(self) -> "Trade":
        if (self.pct is None) == (self.shares is None):
            raise ValueError("give exactly one of pct or shares")
        if self.pct is not None and self.action == "buy":
            raise ValueError("pct is only valid for a sell")
        return self


def _side(metrics: dict) -> dict:
    return {
        "totals": metrics["totals"],
        "positions": [
            {"ticker": p["ticker"], "weight_pct": p["weight_pct"], "market_value": p["market_value"]}
            for p in metrics["positions"]
        ],
    }


def _breaches(metrics: dict, threshold_pct: float) -> list[str]:
    # Same rule as compute_concentration_screen's default: ETFs never breach.
    return [p["ticker"] for p in metrics["positions"] if p["sector"] != "ETF" and p["weight_pct"] > threshold_pct]


async def simulate_change(
    *,
    run_sql: Callable[[str], Awaitable[list[dict]]],
    get_price: Callable[[str], Awaitable[float]],
    client_name: str,
    trades: list[Trade],
    threshold_pct: float = 30.0,
) -> dict:
    before = await load_client_portfolio(run_sql=run_sql, get_price=get_price, client_name=client_name)
    if "error" in before:
        return before

    book = {p["ticker"]: {"shares": p["shares"], "avg_cost": p["avg_cost"], "price": p["price"], "sector": p["sector"]}
            for p in before["positions"]}
    applied, cash_delta = [], 0.0
    for trade in trades:
        ticker = trade.ticker.strip().upper()
        if trade.action == "sell":
            held = book.get(ticker)
            if held is None:
                return {"error": f"{before['client_name']} does not hold {ticker}; cannot sell it."}
            shares = held["shares"] * trade.pct / 100 if trade.pct is not None else trade.shares
            if shares > held["shares"] + 1e-9:
                return {"error": f"Cannot sell {shares:g} {ticker}: {before['client_name']} holds {held['shares']:g}."}
            held["shares"] -= shares
            if held["shares"] <= 1e-9:
                del book[ticker]
            cash_delta += shares * held["price"]
            applied.append({"ticker": ticker, "action": "sell", "shares": round(shares, 4), "price": held["price"]})
        else:
            price = book[ticker]["price"] if ticker in book else float(await get_price(ticker))
            if ticker in book:
                held = book[ticker]
                held["avg_cost"] = (held["avg_cost"] * held["shares"] + price * trade.shares) / (held["shares"] + trade.shares)
                held["shares"] += trade.shares
            else:
                safe = ticker.replace("'", "")
                rows = await run_sql(f"SELECT ticker, sector FROM companies WHERE ticker = '{safe}'")
                book[ticker] = {"shares": trade.shares, "avg_cost": price, "price": price,
                                "sector": rows[0]["sector"] if rows else None}
            cash_delta -= trade.shares * price
            applied.append({"ticker": ticker, "action": "buy", "shares": trade.shares, "price": price})

    if not book:
        return {"error": "The simulated trades would sell every position; nothing left to analyse."}
    after = compute_portfolio_metrics([Position(ticker=t, **v) for t, v in book.items()])
    return {
        "client_name": before["client_name"],
        "before": _side(before),
        "after": _side(after),
        "cash_delta": round(cash_delta, 2),
        "breaches_before": _breaches(before, threshold_pct),
        "breaches_after": _breaches(after, threshold_pct),
        "trades": applied,
    }


class SimulateInput(BaseModel):
    client_name: str = Field(description="Full or partial client name, e.g. 'Margaret Collins'.")
    trades: list[Trade] = Field(min_length=1, max_length=10, description="Hypothetical trades, applied in order.")


@tool("simulate_portfolio_change", args_schema=SimulateInput)
async def simulate_portfolio_change_tool(client_name: str, trades: list[Trade]) -> dict:
    """SIMULATE (never execute) buys/sells on one client's portfolio and show
    before/after weights, value, cash raised or needed, and concentration.
    Use for any "what if <client> sold/bought ..." question. Each trade is
    {ticker, action: buy|sell, pct (sell only) OR shares}."""
    from app.agent.mcp_clients.crm_client import crm_tool
    from app.agent.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"

    async def run_sql(sql: str) -> list[dict]:
        return parse_tool_payload(await crm_tool.ainvoke({"query": sql}))

    async def get_price(ticker: str) -> float:
        return price_from_quote(parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: ticker})))

    trades = [t if isinstance(t, Trade) else Trade(**t) for t in trades]
    return await simulate_change(run_sql=run_sql, get_price=get_price, client_name=client_name, trades=trades)
