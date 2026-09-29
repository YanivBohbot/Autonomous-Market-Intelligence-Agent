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


def test_client_portfolio_shares_the_portfolio_metrics_normalizer():
    """client_portfolio.py's result has the same positions/totals shape as
    portfolio_metrics (plus a client_name field the normalizer ignores), so
    it's registered against the identical normalize_portfolio function."""
    assert display.DISPLAY_NORMALIZERS["client_portfolio"] is display.DISPLAY_NORMALIZERS["portfolio_metrics"]
    displays = display.DISPLAY_NORMALIZERS["client_portfolio"](
        json.dumps({**json.loads(PORTFOLIO_METRICS_JSON), "client_name": "Margaret Collins"}), {},
    )
    assert [d["type"] for d in displays] == ["portfolio_table", "portfolio_chart"]


# Real shape of screen_clients()'s return (concentration.py) — "prices" is
# dropped by the normalizer, it's not display-relevant.
CONCENTRATION_JSON = json.dumps({
    "threshold_pct": 30.0, "screened_count": 2, "screened_labels": ["Margaret Collins", "Martin Levy"],
    "breach_count": 1,
    "breaches": [{"label": "Margaret Collins", "ticker": "NVDA", "weight_pct": 57.5,
                  "market_value": 89436.0, "portfolio_market_value": 155564.81}],
    "prices": {"NVDA": 1259.66},
})

CONCENTRATION_NO_BREACHES_JSON = json.dumps({
    "threshold_pct": 30.0, "screened_count": 1, "screened_labels": ["Diversified Dan"],
    "breach_count": 0, "breaches": [], "prices": {},
})


def test_normalize_concentration_produces_an_alert_per_breach():
    displays = display.DISPLAY_NORMALIZERS["concentration_screen"](CONCENTRATION_JSON, {})
    assert displays == [{
        "type": "concentration_alert", "threshold_pct": 30.0,
        "breaches": [{"label": "Margaret Collins", "ticker": "NVDA", "weight_pct": 57.5, "market_value": 89436.0}],
    }]


def test_normalize_concentration_with_no_breaches_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["concentration_screen"](CONCENTRATION_NO_BREACHES_JSON, {}) == []


# Real (trimmed) yfinance_get_price_history text — a markdown table, not
# JSON. Captured live: the raw MCP result is
# [{"type": "text", "text": THIS_STRING, "id": "..."}]; _content_text already
# extracts THIS_STRING before the normalizer runs. No ticker column exists in
# the table itself — the tool call's own args carry it.
PRICE_HISTORY_TEXT = (
    "| Date                      |   Open |   High |    Low |   Close |      Volume |   Dividends |   Stock Splits |\n"
    "|:--------------------------|-------:|-------:|-------:|--------:|------------:|------------:|---------------:|\n"
    "| 2026-09-21 00:00:00-04:00 | 335.28 | 339.64 | 333.05 |  338.98 | 3.49992e+07 |           0 |              0 |\n"
    "| 2026-09-22 00:00:00-04:00 | 340.14 | 345.34 | 338.75 |  339.75 | 4.07118e+07 |           0 |              0 |\n"
    "| 2026-09-23 00:00:00-04:00 | 341.08 | 341.8  | 335.5  |  337.02 | 3.16588e+07 |           0 |              0 |"
)


def test_normalize_price_history_parses_the_markdown_table():
    displays = display.DISPLAY_NORMALIZERS["yfinance_get_price_history"](PRICE_HISTORY_TEXT, {"symbol": "AAPL"})
    assert displays == [{
        "type": "price_chart", "ticker": "AAPL",
        "points": [
            {"date": "2026-09-21", "close": 338.98},
            {"date": "2026-09-22", "close": 339.75},
            {"date": "2026-09-23", "close": 337.02},
        ],
    }]


def test_normalize_price_history_falls_back_to_the_ticker_arg_name():
    displays = display.DISPLAY_NORMALIZERS["yfinance_get_price_history"](PRICE_HISTORY_TEXT, {"ticker": "aapl"})
    assert displays[0]["ticker"] == "AAPL"


def test_normalize_price_history_with_no_rows_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["yfinance_get_price_history"]("no data available", {"symbol": "XXXX"}) == []


# Trimmed real yfinance_get_ticker_info JSON text (captured live for AAPL) —
# only the fields the display needs, but with the exact real key names.
TICKER_INFO_JSON = json.dumps({
    "shortName": "Apple Inc.", "longName": "Apple Inc.", "sector": "Technology",
    "industry": "Consumer Electronics", "currentPrice": 341.07, "regularMarketPrice": 341.07,
    "currency": "USD", "marketCap": 4977636933632, "fiftyTwoWeekLow": 243.42, "fiftyTwoWeekHigh": 345.34,
})


def test_normalize_ticker_info():
    displays = display.DISPLAY_NORMALIZERS["yfinance_get_ticker_info"](TICKER_INFO_JSON, {"symbol": "AAPL"})
    assert displays == [{
        "type": "ticker_info", "ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology",
        "industry": "Consumer Electronics", "current_price": 341.07, "currency": "USD",
        "market_cap": 4977636933632, "fifty_two_week_low": 243.42, "fifty_two_week_high": 345.34,
    }]


def test_normalize_ticker_info_with_no_price_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["yfinance_get_ticker_info"](json.dumps({"shortName": "Delisted Co"}), {"symbol": "XXXX"}) == []


# Trimmed real yfinance_get_ticker_news JSON text (captured live for AAPL) —
# real nesting (content.title, content.provider.displayName, ...), one item
# missing a canonicalUrl to prove the clickThroughUrl fallback, one item
# missing a title entirely to prove it gets dropped rather than crashing.
TICKER_NEWS_JSON = json.dumps([
    {"id": "1", "content": {
        "title": "Does the S&P 500 Have a Magnificent Seven Problem?",
        "summary": "If the AI revolution doesn't live up to the hype, the whole market feels it.",
        "pubDate": "2026-09-27T13:09:00Z",
        "provider": {"displayName": "Motley Fool"},
        "canonicalUrl": {"url": "https://www.fool.com/a"},
        "clickThroughUrl": {"url": "https://finance.yahoo.com/a"},
    }},
    {"id": "2", "content": {
        "title": "Apple stock ticks up", "summary": "", "pubDate": "2026-09-27T10:00:00Z",
        "provider": {"displayName": "Reuters"}, "canonicalUrl": None,
        "clickThroughUrl": {"url": "https://finance.yahoo.com/b"},
    }},
    {"id": "3", "content": {"title": None, "summary": "no title, must be dropped", "provider": {}}},
])


def test_normalize_ticker_news():
    displays = display.DISPLAY_NORMALIZERS["yfinance_get_ticker_news"](TICKER_NEWS_JSON, {"symbol": "AAPL"})
    assert displays == [{"type": "ticker_news", "items": [
        {"title": "Does the S&P 500 Have a Magnificent Seven Problem?",
         "summary": "If the AI revolution doesn't live up to the hype, the whole market feels it.",
         "source": "Motley Fool", "url": "https://www.fool.com/a", "published_at": "2026-09-27T13:09:00Z"},
        {"title": "Apple stock ticks up", "summary": "", "source": "Reuters",
         "url": "https://finance.yahoo.com/b", "published_at": "2026-09-27T10:00:00Z"},
    ]}]


def test_normalize_ticker_news_with_no_usable_items_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["yfinance_get_ticker_news"]("[]", {"symbol": "XXXX"}) == []


def test_normalize_ticker_news_caps_at_7_items():
    # Live QA: the LLM can ask yfinance_get_ticker_news for more than the
    # default 5 (its `limit` arg is model-controlled), and a long list makes
    # the card unreadable. The card is capped regardless of what the tool
    # returned — a display concern, not a data concern.
    entries = [
        {"id": str(i), "content": {
            "title": f"Headline {i}", "summary": "", "provider": {"displayName": "Wire"},
            "canonicalUrl": {"url": f"https://example.com/{i}"}, "pubDate": "2026-09-27T00:00:00Z",
        }}
        for i in range(10)
    ]
    displays = display.DISPLAY_NORMALIZERS["yfinance_get_ticker_news"](json.dumps(entries), {"symbol": "AAPL"})
    assert len(displays[0]["items"]) == 7
    assert displays[0]["items"][0]["title"] == "Headline 0"
    assert displays[0]["items"][-1]["title"] == "Headline 6"


# Real format from search_knowledge_base_tool (knowledge_base.py): chunks
# joined by "\n\n", each "[Source: F, page N] excerpt". One excerpt here
# contains an internal blank line, to prove the parser doesn't split on it.
RAG_TEXT = (
    "[Source: Amazon-2024-10K.pdf, page 12] Net sales increased 11% to $637.9 billion.\n\n"
    "This growth was\n\ndriven by AWS.\n\n"
    "[Source: Amazon-2024-10K.pdf, page 45] Operating income was $68.6 billion."
)


def test_normalize_rag_sources_anchors_on_source_headers_not_blank_lines():
    displays = display.DISPLAY_NORMALIZERS["search_knowledge_base"](RAG_TEXT, {})
    assert displays == [{"type": "rag_sources", "sources": [
        {"filename": "Amazon-2024-10K.pdf", "page": "12",
         "excerpt": "Net sales increased 11% to $637.9 billion.\n\nThis growth was\n\ndriven by AWS."},
        {"filename": "Amazon-2024-10K.pdf", "page": "45", "excerpt": "Operating income was $68.6 billion."},
    ]}]


def test_normalize_rag_sources_with_no_results_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["search_knowledge_base"](
        "No relevant results found in the knowledge base for this query.", {}) == []


def test_normalize_rag_sources_on_a_search_failure_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["search_knowledge_base"]("Knowledge base search failed: timeout", {}) == []


# Real (post-StripToolImages) text for the local @playwright/mcp backend —
# verified in tests/unit/test_tool_output_image_stripping.py's own fixture.
SCREENSHOT_TEXT = "### Result\n- [Screenshot of viewport](screenshots/evidence.png)"


def test_normalize_screenshot_extracts_the_png_path():
    displays = display.DISPLAY_NORMALIZERS["browser_take_screenshot"](SCREENSHOT_TEXT, {})
    assert displays == [{"type": "screenshot", "url": "/workspace/screenshots/evidence.png"}]


def test_normalize_screenshot_with_no_png_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["browser_take_screenshot"]("no page loaded yet", {}) == []


def test_normalize_report_file_fires_only_for_paths_under_reports():
    displays = display.DISPLAY_NORMALIZERS["write_file"](
        "irrelevant success text", {"path": "reports/margaret-collins-portfolio-brief-2026-09-29.html"},
    )
    assert displays == [{
        "type": "report_file",
        "filename": "margaret-collins-portfolio-brief-2026-09-29.html",
        "url": "/workspace/files/margaret-collins-portfolio-brief-2026-09-29.html",
    }]


def test_normalize_report_file_ignores_a_plain_filesystem_write():
    # filesystem_agent's own write_file calls (e.g. notes.txt at the
    # workspace root) must not produce a download card.
    assert display.DISPLAY_NORMALIZERS["write_file"]("ok", {"path": "notes.txt"}) == []


def test_normalize_report_file_handles_missing_path_arg():
    assert display.DISPLAY_NORMALIZERS["write_file"]("ok", {}) == []
