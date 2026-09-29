"""client_portfolio loads one client's holdings and live prices itself.

Regression: live QA showed gpt-4o-mini skip the portfolio recipe entirely
for a simple "what's this client's portfolio worth" question and write its
own SQL (`SUM(shares * avg_cost)`) -- cost basis, not market value -- giving
$64,179 instead of the correct $156,780 for Margaret Collins. Same fix as
concentration_screen: the tool resolves the client, loads holdings, and
fetches live prices itself, so there's nothing left for the LLM to shortcut.
"""

import asyncio

import pytest

from app.agent.tools.client_portfolio import load_client_portfolio

_ROWS = [
    {"name": "Margaret Collins", "ticker": "BND", "shares": 300.0, "avg_cost": 73.33, "sector": "ETF"},
    {"name": "Margaret Collins", "ticker": "JNJ", "shares": 100.0, "avg_cost": 175.0, "sector": "Health Care"},
    {"name": "Margaret Collins", "ticker": "KO", "shares": 200.0, "avg_cost": 62.0, "sector": "Consumer Staples"},
    {"name": "Margaret Collins", "ticker": "NVDA", "shares": 400.0, "avg_cost": 30.7, "sector": "Technology"},
]
_PRICES = {"BND": 70.075, "JNJ": 266.577, "KO": 86.98, "NVDA": 229.26}


def _run(rows=_ROWS, prices=_PRICES, **kwargs):
    seen_sql = []

    async def run_sql(sql):
        seen_sql.append(sql)
        return rows

    async def get_price(ticker):
        return prices[ticker]

    result = asyncio.run(load_client_portfolio(run_sql=run_sql, get_price=get_price, **kwargs))
    return result, seen_sql


def test_computes_market_value_from_live_prices_not_cost_basis():
    result, _ = _run(client_name="Margaret Collins")
    # Matches the real market-value figure seen earlier in the same live
    # session via the portfolio_metrics recipe -- $64,179 (cost basis) would
    # be the bug this tool exists to prevent.
    assert result["totals"]["market_value"] == pytest.approx(156780.20, abs=0.01)


def test_returns_the_resolved_client_name():
    result, _ = _run(client_name="Collins")
    assert result["client_name"] == "Margaret Collins"


def test_every_position_present_with_sector():
    result, _ = _run(client_name="Margaret Collins")
    tickers = {p["ticker"] for p in result["positions"]}
    assert tickers == {"BND", "JNJ", "KO", "NVDA"}


def test_no_matching_client_returns_an_error_not_a_crash():
    result, _ = _run(rows=[], client_name="Nobody Real")
    assert "error" in result


def test_ambiguous_client_name_returns_an_error_listing_matches():
    rows = _ROWS + [
        {"name": "Margaret Collinsworth", "ticker": "AAPL", "shares": 10.0, "avg_cost": 100.0, "sector": "Technology"},
    ]
    result, _ = _run(rows=rows, client_name="Collins")
    assert "error" in result
    assert "Margaret Collins" in result["error"]
    assert "Margaret Collinsworth" in result["error"]


def test_query_filters_to_the_one_client():
    _, seen_sql = _run(client_name="Margaret Collins")
    assert "c.name LIKE '%Margaret Collins%'" in seen_sql[0]


def test_missing_price_raises_naming_the_ticker():
    async def run_sql(sql):
        return _ROWS

    async def get_price(ticker):
        if ticker == "KO":
            raise ValueError("no data")
        return _PRICES[ticker]

    with pytest.raises(ValueError, match="KO"):
        asyncio.run(load_client_portfolio(run_sql=run_sql, get_price=get_price, client_name="Margaret Collins"))


def test_tool_name_and_llm_facing_args():
    from app.agent.tools.client_portfolio import client_portfolio_tool
    assert client_portfolio_tool.name == "client_portfolio"
    assert set(client_portfolio_tool.args) == {"client_name"}
