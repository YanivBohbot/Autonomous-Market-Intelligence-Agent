import pytest

from app.agent.tools.finance_calc import (
    Position,
    compute_pct_change,
    compute_portfolio_metrics,
    pct_change_tool,
    portfolio_metrics_tool,
)


def _positions(with_sector=True):
    return [
        Position(ticker="AAA", shares=10, avg_cost=50, price=60, sector="Tech" if with_sector else None),
        Position(ticker="BBB", shares=5, avg_cost=100, price=80, sector="Energy" if with_sector else None),
    ]


def test_per_position_metrics():
    result = compute_portfolio_metrics(_positions())
    aaa, bbb = result["positions"]
    assert (aaa["market_value"], aaa["cost_basis"], aaa["unrealized_pnl"], aaa["unrealized_pnl_pct"], aaa["weight_pct"]) == (600.0, 500.0, 100.0, 20.0, 60.0)
    assert (bbb["market_value"], bbb["cost_basis"], bbb["unrealized_pnl"], bbb["unrealized_pnl_pct"], bbb["weight_pct"]) == (400.0, 500.0, -100.0, -20.0, 40.0)


def test_totals():
    assert compute_portfolio_metrics(_positions())["totals"] == {
        "market_value": 1000.0, "cost_basis": 1000.0, "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0,
    }


def test_sector_allocation_when_every_position_has_a_sector():
    assert compute_portfolio_metrics(_positions())["sector_allocation"] == {"Tech": 60.0, "Energy": 40.0}


def test_sector_allocation_is_none_when_a_sector_is_missing():
    assert compute_portfolio_metrics(_positions(with_sector=False))["sector_allocation"] is None


def test_rounding_to_two_decimals():
    result = compute_portfolio_metrics([Position(ticker="X", shares=3, avg_cost=10.006, price=33.333)])
    p = result["positions"][0]
    assert p["market_value"] == 100.0
    assert p["cost_basis"] == 30.02
    assert p["weight_pct"] == 100.0


def test_duplicate_ticker_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        compute_portfolio_metrics([Position(ticker="X", shares=1, avg_cost=1, price=1), Position(ticker="x", shares=1, avg_cost=1, price=1)])


def test_empty_positions_rejected():
    with pytest.raises(ValueError, match="at least one"):
        compute_portfolio_metrics([])


def test_non_positive_values_rejected_by_schema():
    with pytest.raises(ValueError):
        Position(ticker="X", shares=0, avg_cost=1, price=1)
    with pytest.raises(ValueError):
        Position(ticker="X", shares=1, avg_cost=1, price=-5)


def test_pct_change():
    assert compute_pct_change(22387, 28236) == {"old": 22387.0, "new": 28236.0, "change": 5849.0, "pct_change": 26.13}
    assert compute_pct_change(-100, -50)["pct_change"] == 50.0


def test_pct_change_rejects_zero_base():
    with pytest.raises(ValueError, match="old"):
        compute_pct_change(0, 10)


def test_tools_accept_plain_dicts_from_the_llm():
    out = portfolio_metrics_tool.invoke({"positions": [
        {"ticker": "AAA", "shares": 10, "avg_cost": 50, "price": 60, "sector": "Tech"},
        {"ticker": "BBB", "shares": 5, "avg_cost": 100, "price": 80, "sector": "Energy"},
    ]})
    assert out["totals"]["market_value"] == 1000.0
    assert pct_change_tool.invoke({"old": 100, "new": 110})["pct_change"] == 10.0


def test_tool_names():
    assert portfolio_metrics_tool.name == "portfolio_metrics"
    assert pct_change_tool.name == "pct_change"
