"""build_client_summary computes a client's live P&L for GET
/data/clients/{id}/summary -- a view, not an agent tool: unlike
client_portfolio_tool (app/agent/tools/client_portfolio.py), which fails
closed if any ticker's price can't be fetched, this degrades: a bad ticker
is reported in unpriced_tickers and excluded from totals instead of
raising, so one stale ticker doesn't blank the whole page.
"""
import asyncio

import pytest

from app.data_import.client_summary import build_client_summary

_CLIENT = {
    "client_id": 1, "name": "Jane Doe", "email": "jane@x.com", "segment": "VIP",
    "risk_profile": "balanced", "advisor": "Sam", "city": "Paris",
    "holdings": [
        {"ticker": "AAPL", "shares": 10.0, "avg_cost": 150.0},
        {"ticker": "MSFT", "shares": 5.0, "avg_cost": 300.0},
    ],
}
_PRICES = {"AAPL": 200.0, "MSFT": 350.0}


def _run(client=_CLIENT, prices=_PRICES, failing: set[str] = frozenset()):
    async def get_price(ticker):
        if ticker in failing:
            raise ValueError("no data")
        return prices[ticker]

    return asyncio.run(build_client_summary(client=client, get_price=get_price))


def test_computes_totals_from_live_prices():
    result = _run()
    assert result["totals"]["market_value"] == pytest.approx(200.0 * 10 + 350.0 * 5)
    assert result["client_id"] == 1
    assert result["name"] == "Jane Doe"


def test_client_with_no_holdings_has_no_totals_and_does_not_crash():
    client = {**_CLIENT, "holdings": []}
    result = _run(client=client)
    assert result["totals"] is None
    assert result["positions"] == []
    assert result["unpriced_tickers"] == []


def test_one_unpriced_ticker_is_excluded_and_reported_but_totals_still_compute():
    result = _run(failing={"MSFT"})
    assert result["unpriced_tickers"] == ["MSFT"]
    assert [p["ticker"] for p in result["positions"]] == ["AAPL"]
    assert result["totals"]["market_value"] == pytest.approx(200.0 * 10)


def test_every_ticker_unpriced_gives_none_totals_not_a_crash():
    result = _run(failing={"AAPL", "MSFT"})
    assert result["totals"] is None
    assert result["positions"] == []
    assert sorted(result["unpriced_tickers"]) == ["AAPL", "MSFT"]
