"""Deterministic portfolio math for the agent.

LLMs make arithmetic mistakes on multi-position portfolios, so every value,
P&L, weight and growth rate the agent reports must come from these pure
functions. The LLM only copies numbers it already has (shares/avg_cost from
the client DB, prices from yfinance) into the tool arguments.
"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class Position(BaseModel):
    ticker: str = Field(description="Ticker symbol, e.g. 'NVDA'.")
    shares: float = Field(gt=0, description="Number of shares held.")
    avg_cost: float = Field(gt=0, description="Average cost per share (holdings.avg_cost).")
    price: float = Field(gt=0, description="Current price per share (from yfinance).")
    sector: str | None = Field(default=None, description="companies.sector, for sector allocation.")


def _r(value: float) -> float:
    return round(value + 0.0, 2)


def compute_portfolio_metrics(positions: list[Position]) -> dict:
    if not positions:
        raise ValueError("portfolio_metrics needs at least one position")
    tickers = [p.ticker.upper() for p in positions]
    if len(set(tickers)) != len(tickers):
        raise ValueError(f"duplicate ticker in positions: {tickers}")

    total_mv = sum(p.shares * p.price for p in positions)
    total_cb = sum(p.shares * p.avg_cost for p in positions)

    rows = []
    for p in positions:
        mv = p.shares * p.price
        cb = p.shares * p.avg_cost
        rows.append({
            "ticker": p.ticker.upper(),
            "shares": p.shares,
            "avg_cost": p.avg_cost,
            "price": p.price,
            "sector": p.sector,
            "market_value": _r(mv),
            "cost_basis": _r(cb),
            "unrealized_pnl": _r(mv - cb),
            "unrealized_pnl_pct": _r((mv - cb) / cb * 100),
            "weight_pct": _r(mv / total_mv * 100),
        })

    sector_allocation = None
    if all(p.sector for p in positions):
        by_sector: dict[str, float] = {}
        for p in positions:
            by_sector[p.sector] = by_sector.get(p.sector, 0.0) + p.shares * p.price
        sector_allocation = {s: _r(v / total_mv * 100) for s, v in by_sector.items()}

    return {
        "positions": rows,
        "totals": {
            "market_value": _r(total_mv),
            "cost_basis": _r(total_cb),
            "unrealized_pnl": _r(total_mv - total_cb),
            "unrealized_pnl_pct": _r((total_mv - total_cb) / total_cb * 100),
        },
        "sector_allocation": sector_allocation,
    }


def compute_pct_change(old: float, new: float) -> dict:
    if old == 0:
        raise ValueError("pct_change is undefined when old is 0")
    return {
        "old": float(old),
        "new": float(new),
        "change": _r(new - old),
        "pct_change": _r((new - old) / abs(old) * 100),
    }


class PortfolioMetricsInput(BaseModel):
    positions: list[Position] = Field(description="Every position of the portfolio.")


@tool("portfolio_metrics", args_schema=PortfolioMetricsInput)
def portfolio_metrics_tool(positions: list) -> dict:
    """Compute per-position and total market value, cost basis, unrealized
    P&L (amount and %), portfolio weights and sector allocation. Use it for
    ANY portfolio value/performance question instead of doing math yourself."""
    parsed = [p if isinstance(p, Position) else Position.model_validate(p) for p in positions]
    return compute_portfolio_metrics(parsed)


class PctChangeInput(BaseModel):
    old: float = Field(description="Starting value.")
    new: float = Field(description="Ending value.")


@tool("pct_change", args_schema=PctChangeInput)
def pct_change_tool(old: float, new: float) -> dict:
    """Compute the change and % change from `old` to `new` (growth rates,
    quarter-over-quarter, price moves). Use it instead of doing math yourself."""
    return compute_pct_change(old, new)
