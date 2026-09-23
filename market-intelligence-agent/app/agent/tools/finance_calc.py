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


class LabeledPortfolio(BaseModel):
    label: str = Field(description="Human-readable identifier for this portfolio, e.g. the client's full name.")
    positions: list[Position] = Field(description="Every position of this portfolio.")


def compute_concentration_screen(
    portfolios: list[LabeledPortfolio],
    threshold_pct: float = 30.0,
    exclude_sectors: list[str] | None = None,
) -> dict:
    """Deterministically flag every position, across any number of labeled
    portfolios, whose weight exceeds `threshold_pct` of that portfolio's own
    market value. Reuses compute_portfolio_metrics per portfolio so weights
    are computed the same way as `portfolio_metrics`.

    This exists so "which clients/portfolios have more than X% in a single
    stock" answers are built by code, not by an LLM re-reading several
    separate portfolio_metrics results and enumerating the qualifying ones
    itself -- a step that, in production testing, intermittently dropped a
    qualifying portfolio even though its tool result had the right
    weight_pct.

    `exclude_sectors` (default `["ETF"]`) keeps positions in that sector in
    the portfolio totals/weights -- every position's `weight_pct` is still
    computed over the full portfolio market value -- but never lists them in
    `breaches`. A diversified ETF (BND, SPY, ...) legitimately dominating a
    conservative client's portfolio is not a single-stock concentration risk;
    without this, ETFs produced false-positive breaches that buried the real
    single-stock overweights an advisor needs to see. Pass `exclude_sectors=[]`
    to screen every sector, including ETFs.
    """
    if not portfolios:
        raise ValueError("concentration_screen needs at least one portfolio")
    if threshold_pct <= 0:
        raise ValueError("threshold_pct must be positive")
    labels = [pf.label for pf in portfolios]
    if len(set(labels)) != len(labels):
        raise ValueError(f"duplicate label in portfolios: {labels}")
    if exclude_sectors is None:
        exclude_sectors = ["ETF"]

    screened_labels = labels
    breaches = []
    for pf in portfolios:
        metrics = compute_portfolio_metrics(pf.positions)
        for row in metrics["positions"]:
            if row["sector"] in exclude_sectors:
                continue
            if row["weight_pct"] > threshold_pct:
                breaches.append({
                    "label": pf.label,
                    "ticker": row["ticker"],
                    "weight_pct": row["weight_pct"],
                    "market_value": row["market_value"],
                    "portfolio_market_value": metrics["totals"]["market_value"],
                })

    # Deterministic ordering: highest concentration first, tie-broken by
    # label, so repeated runs and repeated LLM copy-outs are stable.
    breaches.sort(key=lambda b: (-b["weight_pct"], b["label"]))

    return {
        "threshold_pct": float(threshold_pct),
        "screened_count": len(screened_labels),
        "screened_labels": screened_labels,
        "breach_count": len(breaches),
        "breaches": breaches,
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


class ConcentrationScreenInput(BaseModel):
    portfolios: list[LabeledPortfolio] = Field(
        description="One entry per client/portfolio to screen, each with a `label` "
        "(e.g. the client's full name) and its `positions` (ticker, shares, avg_cost, "
        "current price, sector). Each portfolio's `positions` MUST include EVERY "
        "position that client holds, including ETFs -- never omit a position just "
        "because its sector is in `exclude_sectors`. exclude_sectors only controls "
        "which positions can appear in the `breaches` output; every supplied position "
        "still counts toward that portfolio's total market value, so dropping one "
        "shrinks the total and inflates every other position's weight_pct."
    )
    threshold_pct: float = Field(
        default=30.0, gt=0,
        description="Flag any position whose weight exceeds this percentage of its own portfolio's market value.",
    )
    exclude_sectors: list[str] = Field(
        default_factory=lambda: ["ETF"],
        description="Sectors to keep in totals/weights but never list in `breaches` (default: [\"ETF\"], since a "
        "diversified ETF dominating a portfolio is not a single-stock concentration risk). Pass [] to screen every "
        "sector, including ETFs.",
    )


@tool("concentration_screen", args_schema=ConcentrationScreenInput)
def concentration_screen_tool(portfolios: list, threshold_pct: float = 30.0, exclude_sectors: list | None = None) -> dict:
    """Screen several labeled portfolios for any single position that exceeds
    threshold_pct (default 30%) of that portfolio's market value, EXCLUDING
    ETF positions from `breaches` by default (they still count toward
    totals/weights). Use this for ANY "which clients/portfolios have more
    than X% in a single stock" or "which clients are concentrated / over X%"
    screening question -- it REPLACES making a separate `portfolio_metrics`
    call per client and comparing the results yourself, because the
    qualifying list (`breaches`) is computed by code, so nothing is dropped
    or misclassified. Pass `exclude_sectors=[]` to also flag ETF
    concentration. Still requires the current price (from yfinance) for
    every position, same as portfolio_metrics; never pass avg_cost as the
    price. IMPORTANT: always include EVERY position of each portfolio,
    including ETFs -- exclude_sectors only filters what can appear in
    `breaches`, it is NOT a signal to omit those positions from the input.
    Omitting a position shrinks the portfolio total this tool computes
    weights from and inflates every remaining position's weight_pct."""
    parsed = [pf if isinstance(pf, LabeledPortfolio) else LabeledPortfolio.model_validate(pf) for pf in portfolios]
    return compute_concentration_screen(parsed, threshold_pct, exclude_sectors)


class PctChangeInput(BaseModel):
    old: float = Field(description="Starting value.")
    new: float = Field(description="Ending value.")


@tool("pct_change", args_schema=PctChangeInput)
def pct_change_tool(old: float, new: float) -> dict:
    """Compute the change and % change from `old` to `new` (growth rates,
    quarter-over-quarter, price moves). Use it instead of doing math yourself."""
    return compute_pct_change(old, new)
