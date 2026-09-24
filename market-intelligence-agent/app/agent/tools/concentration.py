"""`concentration_screen` — screens clients for single-stock concentration.

The tool loads every position itself: holdings + sector from the client DB
(through the same `read_query` MCP tool the agent uses, so it works over
local stdio and over the AgentCore Gateway) and live prices from yfinance.
The LLM only passes the filter (risk profile / client names / threshold).

Why: when the LLM had to copy every client's positions into the tool call,
gpt-4o-mini intermittently dropped a line (typically the ETF), which shrank
that portfolio's total and corrupted every weight. Nothing to copy, nothing
to drop. The math itself stays in `finance_calc.compute_concentration_screen`.
"""

from __future__ import annotations

import ast
import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools.finance_calc import LabeledPortfolio, Position, compute_concentration_screen

RiskProfile = Literal["conservative", "balanced", "aggressive"]
_RISK_PROFILES = ("conservative", "balanced", "aggressive")


def build_holdings_query(risk_profile: str | None, client_names: list[str] | None) -> str:
    """SELECT every holding with its sector, optionally filtered. Only a
    whitelisted risk_profile and quote-escaped names reach the SQL."""
    where = []
    if risk_profile is not None:
        if risk_profile not in _RISK_PROFILES:
            raise ValueError(f"risk_profile must be one of {_RISK_PROFILES}, got {risk_profile!r}")
        where.append(f"c.risk_profile = '{risk_profile}'")
    if client_names:
        likes = " OR ".join("c.name LIKE '%" + n.replace("'", "''") + "%'" for n in client_names)
        where.append(f"({likes})")
    sql = (
        "SELECT c.name, h.ticker, h.shares, h.avg_cost, co.sector "
        "FROM holdings h JOIN clients c ON c.client_id = h.client_id "
        "JOIN companies co ON co.ticker = h.ticker"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    return sql + " ORDER BY c.name, h.ticker"


def parse_tool_payload(result: Any) -> Any:
    """Normalize an MCP tool result from either transport into plain data.

    Local stdio returns content blocks whose text is JSON (yfmcp) or a Python
    repr (mcp-server-sqlite); the Gateway's Lambdas wrap results in
    `{"ok": bool, "result"|"error": ...}`.
    """
    if isinstance(result, list) and result and all(isinstance(b, dict) and "type" in b for b in result):
        result = "".join(b.get("text", "") for b in result if b.get("type") == "text")
    if isinstance(result, str):
        text = result.strip()
        try:
            result = json.loads(text)
        except ValueError:
            try:
                result = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                raise ValueError(f"unreadable tool output: {text[:200]!r}") from None
    if isinstance(result, dict) and "ok" in result:
        if not result["ok"]:
            raise ValueError(str(result.get("error", "tool reported an error")))
        result = result.get("result")
    return result


def price_from_quote(info: dict) -> float:
    for key in ("currentPrice", "regularMarketPrice"):
        value = info.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    raise ValueError("no current price in quote")


async def screen_clients(
    *,
    run_sql: Callable[[str], Awaitable[list[dict]]],
    get_price: Callable[[str], Awaitable[float]],
    risk_profile: str | None = None,
    client_names: list[str] | None = None,
    threshold_pct: float = 30.0,
    exclude_sectors: list[str] | None = None,
) -> dict:
    rows = await run_sql(build_holdings_query(risk_profile, client_names))
    if not rows:
        return {"threshold_pct": float(threshold_pct), "screened_count": 0, "screened_labels": [],
                "breach_count": 0, "breaches": [], "prices": {}}

    tickers = sorted({r["ticker"] for r in rows})
    results = await asyncio.gather(*(get_price(t) for t in tickers), return_exceptions=True)
    failed = [t for t, r in zip(tickers, results) if isinstance(r, BaseException)]
    if failed:
        raise ValueError(f"could not get a current price for: {', '.join(failed)}")
    prices = dict(zip(tickers, (float(r) for r in results)))

    by_client: dict[str, list[Position]] = {}
    for r in rows:
        by_client.setdefault(r["name"], []).append(Position(
            ticker=r["ticker"], shares=r["shares"], avg_cost=r["avg_cost"],
            price=prices[r["ticker"]], sector=r["sector"],
        ))
    portfolios = [LabeledPortfolio(label=name, positions=pos) for name, pos in by_client.items()]
    return {**compute_concentration_screen(portfolios, threshold_pct, exclude_sectors), "prices": prices}


class ConcentrationScreenInput(BaseModel):
    risk_profile: RiskProfile | None = Field(
        default=None, description="Only screen clients with this risk profile. Omit to screen all clients.")
    client_names: list[str] | None = Field(
        default=None, description="Only screen these clients (full or partial names). Omit to screen all clients.")
    threshold_pct: float = Field(
        default=30.0, gt=0,
        description="Flag any position whose weight exceeds this percentage of its client's portfolio market value.")
    exclude_sectors: list[str] = Field(
        default_factory=lambda: ["ETF"],
        description="Sectors kept in totals/weights but never listed in `breaches` (default [\"ETF\"]: a diversified "
        "ETF is not a single-stock risk). Pass [] to also flag ETF concentration.")


@tool("concentration_screen", args_schema=ConcentrationScreenInput)
async def concentration_screen_tool(
    risk_profile: str | None = None,
    client_names: list[str] | None = None,
    threshold_pct: float = 30.0,
    exclude_sectors: list[str] | None = None,
) -> dict:
    """Find which clients hold more than threshold_pct (default 30%) of their
    portfolio in a single stock. The tool itself reads every client's holdings
    from the database and fetches live prices -- do NOT query holdings or
    prices first and do NOT pass positions. Just pass the filter (risk_profile
    and/or client_names) and the threshold. Report exactly the clients and
    tickers in `breaches`; `screened_labels` lists every client checked."""
    from app.agent.tools.mcp_clients.mcp_client import crm_tool
    from app.agent.tools.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"

    async def run_sql(sql: str) -> list[dict]:
        return parse_tool_payload(await crm_tool.ainvoke({"query": sql}))

    async def get_price(ticker: str) -> float:
        return price_from_quote(parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: ticker})))

    return await screen_clients(
        run_sql=run_sql, get_price=get_price, risk_profile=risk_profile,
        client_names=client_names, threshold_pct=threshold_pct, exclude_sectors=exclude_sectors,
    )
