"""Pure str -> list[dict] normalizers, each tested against the real shape its
tool actually produces (captured live where the tool is MCP-backed and this
repo has no fixture of its own)."""
import json

from app.agent.multi_agent import display

# Trimmed real output of compute_portfolio_metrics (finance_calc.py) for one
# client — field names and value shapes copied verbatim.
PORTFOLIO_METRICS_JSON = json.dumps({
    "positions": [
        {"ticker": "BND", "shares": 300.0, "avg_cost": 73.33, "price": 70.63, "sector": "ETF",
         "market_value": 21189.0, "cost_basis": 21999.0, "unrealized_pnl": -810.0,
         "unrealized_pnl_pct": -3.68, "weight_pct": 13.62},
        {"ticker": "NVDA", "shares": 71.0, "avg_cost": 172.96, "price": 1259.66, "sector": "Technology",
         "market_value": 89436.0, "cost_basis": 12280.0, "unrealized_pnl": 77156.0,
         "unrealized_pnl_pct": 628.31, "weight_pct": 57.5},
    ],
    "totals": {"market_value": 155564.81, "cost_basis": 64179.0, "unrealized_pnl": 91385.81,
               "unrealized_pnl_pct": 142.39},
    "sector_allocation": {"ETF": 13.62, "Technology": 57.5},
})


def test_normalize_portfolio_produces_table_and_chart():
    displays = display.DISPLAY_NORMALIZERS["portfolio_metrics"](PORTFOLIO_METRICS_JSON, {})
    assert [d["type"] for d in displays] == ["portfolio_table", "portfolio_chart"]

    table = displays[0]
    assert table["totals"] == {"market_value": 155564.81, "cost_basis": 64179.0,
                                "unrealized_pnl": 91385.81, "unrealized_pnl_pct": 142.39}
    assert table["positions"][0] == {
        "ticker": "BND", "shares": 300.0, "price": 70.63, "market_value": 21189.0,
        "cost_basis": 21999.0, "unrealized_pnl": -810.0, "unrealized_pnl_pct": -3.68,
        "weight_pct": 13.62, "sector": "ETF",
    }

    chart = displays[1]
    assert chart["slices"] == [{"ticker": "BND", "weight_pct": 13.62}, {"ticker": "NVDA", "weight_pct": 57.5}]
