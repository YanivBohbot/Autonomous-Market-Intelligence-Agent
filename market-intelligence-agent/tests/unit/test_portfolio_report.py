"""Portfolio report artifact generation — chart math, HTML rendering, and the
self-loading tool wrapper, in that order (each layer tested independently,
same discipline as finance_calc.py / concentration.py / client_portfolio.py)."""
import re

import pytest

from app.agent.tools.portfolio_report import build_pie_chart_svg


def test_single_position_renders_a_full_circle_not_a_degenerate_arc():
    svg = build_pie_chart_svg([{"ticker": "NVDA", "weight_pct": 100.0}])
    assert "<circle" in svg
    assert "<path" not in svg


def test_multiple_positions_render_one_arc_path_each():
    svg = build_pie_chart_svg([
        {"ticker": "BND", "weight_pct": 40.0},
        {"ticker": "NVDA", "weight_pct": 60.0},
    ])
    assert svg.count("<path") == 2


def test_includes_a_legend_entry_per_position_with_ticker_and_percent():
    svg = build_pie_chart_svg([
        {"ticker": "BND", "weight_pct": 40.0},
        {"ticker": "NVDA", "weight_pct": 60.0},
    ])
    assert "BND 40.0%" in svg
    assert "NVDA 60.0%" in svg


def test_no_nan_or_negative_coordinates_for_a_three_way_split():
    svg = build_pie_chart_svg([
        {"ticker": "A", "weight_pct": 33.3},
        {"ticker": "B", "weight_pct": 33.3},
        {"ticker": "C", "weight_pct": 33.4},
    ])
    assert "nan" not in svg.lower()
    assert re.search(r"-\d", svg) is None  # a hyphen directly before a digit would be a real negative number (font-size/font-family have no digit after their hyphen)


def test_empty_positions_raises():
    with pytest.raises(ValueError, match="at least one position"):
        build_pie_chart_svg([])


from app.agent.tools.portfolio_report import build_portfolio_report_html

_PORTFOLIO = {
    "client_name": "Margaret Collins",
    "positions": [
        {"ticker": "BND", "shares": 300.0, "avg_cost": 73.33, "price": 70.075, "sector": "ETF",
         "market_value": 21022.5, "cost_basis": 21999.0, "unrealized_pnl": -976.5,
         "unrealized_pnl_pct": -4.44, "weight_pct": 13.41},
        {"ticker": "NVDA", "shares": 400.0, "avg_cost": 30.7, "price": 229.26, "sector": "Technology",
         "market_value": 91704.0, "cost_basis": 12280.0, "unrealized_pnl": 79424.0,
         "unrealized_pnl_pct": 646.7, "weight_pct": 58.51},
    ],
    "totals": {"market_value": 156780.20, "cost_basis": 64179.0, "unrealized_pnl": 92601.2, "unrealized_pnl_pct": 144.3},
    "sector_allocation": {"ETF": 13.41, "Technology": 58.51},
}


def test_report_contains_client_name_and_exact_copied_numbers():
    html = build_portfolio_report_html(_PORTFOLIO)
    assert "Margaret Collins" in html
    assert "156,780.20" in html  # copied verbatim from totals, never recomputed
    assert "NVDA" in html and "58.5%" in html


def test_report_embeds_an_svg_chart():
    html = build_portfolio_report_html(_PORTFOLIO)
    assert "<svg" in html


def test_concentration_note_appears_only_above_threshold():
    html = build_portfolio_report_html(_PORTFOLIO, threshold_pct=30.0)
    assert "NVDA" in html.split("Concentration note")[1]

    below_threshold = build_portfolio_report_html(_PORTFOLIO, threshold_pct=90.0)
    assert "Concentration note" not in below_threshold


def test_report_is_self_contained_no_external_assets():
    html = build_portfolio_report_html(_PORTFOLIO)
    # "http://www.w3.org/2000/svg" is the SVG xmlns namespace, a required
    # identifier the browser never fetches -- not an external asset load.
    # A real external reference would show up as src="http..." or url(http...).
    assert 'src="http' not in html and "url(http" not in html
    assert "<img" not in html  # the only image-like content is the inline <svg>


import asyncio

from app.agent.tools.portfolio_report import generate_portfolio_report

_ROWS = [
    {"name": "Margaret Collins", "ticker": "BND", "shares": 300.0, "avg_cost": 73.33, "sector": "ETF"},
    {"name": "Margaret Collins", "ticker": "NVDA", "shares": 400.0, "avg_cost": 30.7, "sector": "Technology"},
]
_PRICES = {"BND": 70.075, "NVDA": 229.26}


def _run(rows=_ROWS, prices=_PRICES, client_name="Margaret Collins"):
    async def run_sql(sql):
        return rows

    async def get_price(ticker):
        return prices[ticker]

    return asyncio.run(generate_portfolio_report(run_sql=run_sql, get_price=get_price, client_name=client_name))


def test_suggested_path_is_under_reports_and_ends_in_html():
    result = _run()
    assert result["suggested_path"].startswith("reports/")
    assert result["suggested_path"].endswith(".html")


def test_html_contains_the_resolved_client_name():
    result = _run()
    assert "Margaret Collins" in result["html"]


def test_apostrophe_in_client_name_never_reaches_the_filename():
    rows = [{"name": "Pat O'Brien", "ticker": "AAPL", "shares": 10.0, "avg_cost": 100.0, "sector": "Technology"}]
    result = _run(rows=rows, prices={"AAPL": 150.0}, client_name="O'Brien")
    assert "'" not in result["suggested_path"]
    assert "/" not in result["suggested_path"].removeprefix("reports/")


def test_unresolved_client_returns_the_same_error_shape_load_client_portfolio_uses():
    result = _run(rows=[], client_name="Nobody Real")
    assert result == {"error": "No client matching 'Nobody Real' found, or they have no holdings."}
    assert "html" not in result


def test_tool_name_and_llm_facing_args():
    from app.agent.tools.portfolio_report import generate_portfolio_report_tool
    assert generate_portfolio_report_tool.name == "generate_portfolio_report"
    assert set(generate_portfolio_report_tool.args) == {"client_name"}
