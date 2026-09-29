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
