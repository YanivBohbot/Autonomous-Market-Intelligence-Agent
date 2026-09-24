"""concentration_screen loads every position itself (DB + live prices).

Regression: when the LLM had to copy every client's positions into the tool
call by hand, gpt-4o-mini intermittently dropped a line (typically the ETF),
which shrank that portfolio's total and corrupted every weight. The tool now
reads holdings and prices itself, so the LLM only passes the filter.
"""

import asyncio

import pytest

from app.agent.tools.concentration import (
    build_holdings_query,
    parse_tool_payload,
    price_from_quote,
    screen_clients,
)

# Margaret Collins: ~58% NVDA once BND/JNJ/KO are counted. Susan Grant: diversified.
_ROWS = [
    {"name": "Margaret Collins", "ticker": "BND", "shares": 300.0, "avg_cost": 73.33, "sector": "ETF"},
    {"name": "Margaret Collins", "ticker": "JNJ", "shares": 100.0, "avg_cost": 150.0, "sector": "Health Care"},
    {"name": "Margaret Collins", "ticker": "KO", "shares": 200.0, "avg_cost": 60.0, "sector": "Consumer Staples"},
    {"name": "Margaret Collins", "ticker": "NVDA", "shares": 400.0, "avg_cost": 30.7, "sector": "Technology"},
    {"name": "Susan Grant", "ticker": "JNJ", "shares": 50.0, "avg_cost": 150.0, "sector": "Health Care"},
    {"name": "Susan Grant", "ticker": "KO", "shares": 100.0, "avg_cost": 60.0, "sector": "Consumer Staples"},
    {"name": "Susan Grant", "ticker": "BND", "shares": 300.0, "avg_cost": 73.0, "sector": "ETF"},
]
_PRICES = {"BND": 74.0, "JNJ": 190.0, "KO": 70.0, "NVDA": 228.87}


def _run(rows=_ROWS, prices=_PRICES, **kwargs):
    seen_sql = []

    async def run_sql(sql):
        seen_sql.append(sql)
        return rows

    async def get_price(ticker):
        return prices[ticker]

    result = asyncio.run(screen_clients(run_sql=run_sql, get_price=get_price, **kwargs))
    return result, seen_sql


def test_flags_the_concentrated_client_with_every_position_counted():
    result, _ = _run(risk_profile="conservative")
    assert result["breach_count"] == 1
    breach = result["breaches"][0]
    assert breach["label"] == "Margaret Collins"
    assert breach["ticker"] == "NVDA"
    # 91,548 / (22,200 + 19,000 + 14,000 + 91,548) -- BND included in the total.
    assert breach["weight_pct"] == pytest.approx(62.38, abs=0.01)


def test_reports_every_screened_client_and_live_prices():
    result, _ = _run(risk_profile="conservative")
    assert result["screened_labels"] == ["Margaret Collins", "Susan Grant"]
    assert result["prices"] == _PRICES


def test_threshold_and_exclude_sectors_are_forwarded():
    result, _ = _run(threshold_pct=10, exclude_sectors=[])
    tickers = {(b["label"], b["ticker"]) for b in result["breaches"]}
    assert ("Margaret Collins", "BND") in tickers


def test_no_matching_clients_returns_empty_result_not_error():
    result, _ = _run(rows=[], risk_profile="aggressive")
    assert result["screened_count"] == 0
    assert result["breaches"] == []


def test_missing_price_raises_naming_the_ticker():
    async def run_sql(sql):
        return _ROWS

    async def get_price(ticker):
        if ticker == "KO":
            raise ValueError("no data")
        return _PRICES[ticker]

    with pytest.raises(ValueError, match="KO"):
        asyncio.run(screen_clients(run_sql=run_sql, get_price=get_price))


def test_each_ticker_price_fetched_once():
    calls = []

    async def run_sql(sql):
        return _ROWS

    async def get_price(ticker):
        calls.append(ticker)
        return _PRICES[ticker]

    asyncio.run(screen_clients(run_sql=run_sql, get_price=get_price))
    assert sorted(calls) == sorted(_PRICES)


# --- SQL building ---------------------------------------------------------

def test_query_is_select_only_and_joins_sector():
    sql = build_holdings_query(None, None)
    assert sql.lstrip().upper().startswith("SELECT")
    assert "companies" in sql and "sector" in sql
    assert "WHERE" not in sql


def test_query_filters_by_risk_profile():
    assert "c.risk_profile = 'conservative'" in build_holdings_query("conservative", None)


def test_query_rejects_unknown_risk_profile():
    with pytest.raises(ValueError, match="risk_profile"):
        build_holdings_query("x' OR 1=1 --", None)


def test_query_filters_by_client_names_and_escapes_quotes():
    sql = build_holdings_query(None, ["Margaret Collins", "O'Brien"])
    assert "c.name LIKE '%Margaret Collins%'" in sql
    assert "c.name LIKE '%O''Brien%'" in sql


# --- parsing both transports (local stdio MCP and AgentCore Gateway) ------

def test_parse_local_sqlite_content_blocks_with_python_repr():
    blocks = [{"type": "text", "text": "[{'name': 'A', 'shares': 1.0}]", "id": "lc_1"}]
    assert parse_tool_payload(blocks) == [{"name": "A", "shares": 1.0}]


def test_parse_gateway_lambda_envelope():
    blocks = [{"type": "text", "text": '{"ok": true, "result": [{"name": "A"}]}'}]
    assert parse_tool_payload(blocks) == [{"name": "A"}]


def test_parse_gateway_lambda_error_raises():
    with pytest.raises(ValueError, match="boom"):
        parse_tool_payload('{"ok": false, "error": "boom"}')


def test_parse_unreadable_text_raises_value_error():
    with pytest.raises(ValueError):
        parse_tool_payload("Error: something went wrong")


def test_price_prefers_current_then_regular_market_price():
    assert price_from_quote({"currentPrice": 10.5, "regularMarketPrice": 11}) == 10.5
    assert price_from_quote({"regularMarketPrice": 11}) == 11.0
    with pytest.raises(ValueError):
        price_from_quote({"sector": "Technology"})


# --- the LangChain tool itself -------------------------------------------

def test_tool_name_and_llm_facing_args():
    from app.agent.tools.concentration import concentration_screen_tool
    assert concentration_screen_tool.name == "concentration_screen"
    args = set(concentration_screen_tool.args)
    assert args == {"risk_profile", "client_names", "threshold_pct", "exclude_sectors"}
    assert "portfolios" not in args
