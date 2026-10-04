"""Deterministic client P&L summary for GET /data/clients/{id}/summary --
no agent involved, same CRUD-not-agent philosophy as the rest of
app/data_import/. Unlike client_portfolio_tool
(app/agent/tools/client_portfolio.py), which fails closed (raises if any
ticker's price can't be fetched, so the agent never reports a silently
wrong total), this is a UI view: one bad ticker should not blank the
whole client's page, so a failed price is reported in unpriced_tickers
and excluded from totals instead of raising.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agent.tools.finance_calc import Position, compute_portfolio_metrics


async def build_client_summary(
    *,
    client: dict,
    get_price: Callable[[str], Awaitable[float]],
) -> dict:
    holdings = client["holdings"]
    tickers = [h["ticker"] for h in holdings]
    results = await asyncio.gather(*(get_price(t) for t in tickers), return_exceptions=True)

    positions = []
    unpriced: list[str] = []
    for holding, result in zip(holdings, results):
        if isinstance(result, BaseException):
            unpriced.append(holding["ticker"])
            continue
        positions.append(Position(
            ticker=holding["ticker"], shares=holding["shares"],
            avg_cost=holding["avg_cost"], price=float(result),
        ))

    totals = None
    position_rows: list[dict] = []
    if positions:
        metrics = compute_portfolio_metrics(positions)
        totals = metrics["totals"]
        position_rows = metrics["positions"]

    return {
        "client_id": client["client_id"], "name": client["name"], "email": client["email"],
        "segment": client["segment"], "risk_profile": client["risk_profile"],
        "advisor": client["advisor"], "city": client["city"],
        "totals": totals, "positions": position_rows, "unpriced_tickers": unpriced,
    }
