import asyncio

import pytest
from pydantic import ValidationError

from app.agent.tools.what_if import Trade, simulate_change

HOLDINGS = [
    {"client_id": 1, "name": "Margaret Collins", "ticker": "NVDA", "shares": 100.0, "avg_cost": 50.0, "sector": "Technology"},
    {"client_id": 1, "name": "Margaret Collins", "ticker": "BND", "shares": 100.0, "avg_cost": 70.0, "sector": "ETF"},
]
PRICES = {"NVDA": 200.0, "BND": 70.0, "MSFT": 400.0}


async def run_sql(sql):
    if "FROM holdings" in sql:
        return HOLDINGS if "Collins" in sql else []
    if "FROM companies" in sql:
        return [{"ticker": "MSFT", "sector": "Technology"}] if "MSFT" in sql else []
    raise AssertionError(sql)


async def get_price(ticker):
    return PRICES[ticker]


def sim(trades, name="Collins"):
    return asyncio.run(simulate_change(run_sql=run_sql, get_price=get_price, client_name=name,
                                       trades=[Trade(**t) for t in trades]))


def weights(side):
    return {p["ticker"]: p["weight_pct"] for p in side["positions"]}


def test_sell_half_by_pct_raises_cash_and_keeps_breach():
    out = sim([{"ticker": " nvda ", "action": "sell", "pct": 50}])
    assert out["client_name"] == "Margaret Collins"
    assert weights(out["before"]) == {"NVDA": 74.07, "BND": 25.93}
    assert weights(out["after"]) == {"NVDA": 58.82, "BND": 41.18}
    assert out["cash_delta"] == 10000.0
    assert out["breaches_before"] == ["NVDA"] and out["breaches_after"] == ["NVDA"]
    assert out["trades"] == [{"ticker": "NVDA", "action": "sell", "shares": 50.0, "price": 200.0}]


def test_sell_everything_by_pct_removes_the_position():
    out = sim([{"ticker": "NVDA", "action": "sell", "pct": 100}])
    assert weights(out["after"]) == {"BND": 100.0}
    assert out["breaches_after"] == []  # BND is an ETF: never a breach


def test_sell_exact_shares_removes_the_position():
    assert "NVDA" not in weights(sim([{"ticker": "NVDA", "action": "sell", "shares": 100}])["after"])


def test_buy_new_ticker_uses_live_price_and_companies_sector():
    out = sim([{"ticker": "MSFT", "action": "buy", "shares": 10}])
    assert out["cash_delta"] == -4000.0
    assert "MSFT" in weights(out["after"])


def test_oversell_is_an_error_and_nothing_applies():
    out = sim([{"ticker": "BND", "action": "sell", "pct": 50}, {"ticker": "NVDA", "action": "sell", "shares": 101}])
    assert "error" in out and "NVDA" in out["error"]


def test_selling_an_unheld_ticker_is_an_error():
    assert "error" in sim([{"ticker": "TSLA", "action": "sell", "shares": 1}])


def test_unknown_client_is_an_error():
    assert "error" in sim([{"ticker": "NVDA", "action": "sell", "pct": 10}], name="Nobody")


def test_trade_needs_exactly_one_of_pct_and_shares():
    with pytest.raises(ValidationError):
        Trade(ticker="NVDA", action="sell", pct=10, shares=5)
    with pytest.raises(ValidationError):
        Trade(ticker="NVDA", action="sell")
    with pytest.raises(ValidationError):
        Trade(ticker="NVDA", action="buy", pct=10)
