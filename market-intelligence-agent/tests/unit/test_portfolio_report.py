"""Portfolio report artifact generation -- Excel table+chart building, then
the self-loading atomic tool, in that order (each layer tested
independently, same discipline as finance_calc.py / concentration.py /
client_portfolio.py)."""
import io

import openpyxl
import pytest

from app.agent.tools.portfolio_report import build_portfolio_report_xlsx

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


def _load(data: bytes):
    return openpyxl.load_workbook(io.BytesIO(data))


def _all_cell_values(ws):
    return [c.value for row in ws.iter_rows() for c in row if c.value is not None]


def test_report_contains_client_name_and_exact_copied_numbers():
    wb = _load(build_portfolio_report_xlsx(_PORTFOLIO))
    ws = wb["Portfolio Brief"]
    values = _all_cell_values(ws)
    assert any("Margaret Collins" in str(v) for v in values)
    assert 156780.20 in [v for v in values if isinstance(v, (int, float))]
    assert "NVDA" in values


def test_report_includes_a_native_chart():
    wb = _load(build_portfolio_report_xlsx(_PORTFOLIO))
    ws = wb["Portfolio Brief"]
    assert len(ws._charts) == 1


def test_single_position_renders_a_chart_without_error():
    # Unlike hand-computed SVG arcs, a native Excel pie chart has no
    # "can't express a full 360 degree sweep as one path" special case --
    # this just needs to not raise and to still produce a chart.
    single = {
        "client_name": "Solo Holder",
        "positions": [
            {"ticker": "NVDA", "shares": 100.0, "avg_cost": 30.0, "price": 229.26, "sector": "Technology",
             "market_value": 22926.0, "cost_basis": 3000.0, "unrealized_pnl": 19926.0,
             "unrealized_pnl_pct": 664.2, "weight_pct": 100.0},
        ],
        "totals": {"market_value": 22926.0, "cost_basis": 3000.0, "unrealized_pnl": 19926.0, "unrealized_pnl_pct": 664.2},
        "sector_allocation": {"Technology": 100.0},
    }
    wb = _load(build_portfolio_report_xlsx(single))
    ws = wb["Portfolio Brief"]
    assert len(ws._charts) == 1


def test_empty_positions_raises():
    with pytest.raises(ValueError, match="at least one position"):
        build_portfolio_report_xlsx({**_PORTFOLIO, "positions": []})


def test_concentration_note_appears_only_above_threshold():
    wb_above = _load(build_portfolio_report_xlsx(_PORTFOLIO, threshold_pct=30.0))
    values_above = " ".join(str(v) for v in _all_cell_values(wb_above["Portfolio Brief"]))
    assert "Concentration note" in values_above
    assert "NVDA" in values_above.split("Concentration note")[1]

    wb_below = _load(build_portfolio_report_xlsx(_PORTFOLIO, threshold_pct=90.0))
    values_below = " ".join(str(v) for v in _all_cell_values(wb_below["Portfolio Brief"]))
    assert "Concentration note" not in values_below


def test_concentration_note_excludes_etfs_same_as_concentration_screen():
    # Same rationale as the HTML-era version of this test: concentration_screen
    # excludes ETF-sector positions from breaches by default, so the report
    # must not disagree with it for the same client.
    etf_heavy = {
        "client_name": "Christopher Lee",
        "positions": [
            {"ticker": "BND", "shares": 100.0, "avg_cost": 70.0, "price": 70.0, "sector": "ETF",
             "market_value": 70000.0, "cost_basis": 70000.0, "unrealized_pnl": 0.0,
             "unrealized_pnl_pct": 0.0, "weight_pct": 71.6},
            {"ticker": "JNJ", "shares": 100.0, "avg_cost": 150.0, "price": 150.0, "sector": "Healthcare",
             "market_value": 15000.0, "cost_basis": 15000.0, "unrealized_pnl": 0.0,
             "unrealized_pnl_pct": 0.0, "weight_pct": 15.3},
        ],
        "totals": {"market_value": 85000.0, "cost_basis": 85000.0, "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0},
        "sector_allocation": {"ETF": 71.6, "Healthcare": 15.3},
    }
    wb = _load(build_portfolio_report_xlsx(etf_heavy, threshold_pct=30.0))
    values = " ".join(str(v) for v in _all_cell_values(wb["Portfolio Brief"]))
    assert "Concentration note" not in values


import asyncio
from pathlib import Path

from app.agent.tools.portfolio_report import save_portfolio_report

_ROWS = [
    {"name": "Margaret Collins", "ticker": "BND", "shares": 300.0, "avg_cost": 73.33, "sector": "ETF"},
    {"name": "Margaret Collins", "ticker": "NVDA", "shares": 400.0, "avg_cost": 30.7, "sector": "Technology"},
]
_PRICES = {"BND": 70.075, "NVDA": 229.26}


def _run(tmp_path, rows=_ROWS, prices=_PRICES, client_name="Margaret Collins"):
    async def run_sql(sql):
        return rows

    async def get_price(ticker):
        return prices[ticker]

    return asyncio.run(save_portfolio_report(
        run_sql=run_sql, get_price=get_price, client_name=client_name, reports_dir=tmp_path / "reports",
    ))


def test_writes_a_real_xlsx_file_to_reports_dir(tmp_path):
    result = _run(tmp_path)
    written = tmp_path / "reports" / result["filename"]
    assert written.is_file()
    assert written.read_bytes()[:2] == b"PK"  # .xlsx is a zip archive


def test_filename_is_under_reports_and_ends_in_xlsx(tmp_path):
    result = _run(tmp_path)
    assert result["filename"].endswith(".xlsx")
    assert "/" not in result["filename"]  # filename only -- reports_dir is where it lives, not part of the name


def test_creates_reports_dir_when_missing(tmp_path):
    reports_dir = tmp_path / "reports"
    assert not reports_dir.exists()
    _run(tmp_path)
    assert reports_dir.is_dir()


def test_apostrophe_in_client_name_never_reaches_the_filename(tmp_path):
    rows = [{"name": "Pat O'Brien", "ticker": "AAPL", "shares": 10.0, "avg_cost": 100.0, "sector": "Technology"}]
    result = _run(tmp_path, rows=rows, prices={"AAPL": 150.0}, client_name="O'Brien")
    assert "'" not in result["filename"]


def test_partial_name_match_resolves_to_the_full_client_name_in_the_filename(tmp_path):
    # "Collins" resolves to "Margaret Collins" via load_client_portfolio --
    # the filename must reflect the resolved name, not the partial input.
    result = _run(tmp_path, client_name="Collins")
    assert result["client_name"] == "Margaret Collins"
    assert "margaret-collins" in result["filename"]


def test_unresolved_client_returns_the_same_error_shape_load_client_portfolio_uses(tmp_path):
    result = _run(tmp_path, rows=[], client_name="Nobody Real")
    assert result == {"error": "No client matching 'Nobody Real' found, or they have no holdings."}
    assert not (tmp_path / "reports").exists()  # nothing written on error


def test_a_build_failure_leaves_no_file_on_disk(tmp_path, monkeypatch):
    # The write only happens after build_portfolio_report_xlsx fully
    # returns bytes -- a failure during the build must not leave a
    # partial or empty file behind.
    import app.agent.tools.portfolio_report as mod

    def boom(portfolio, *, threshold_pct=30.0):
        raise RuntimeError("simulated build failure")

    monkeypatch.setattr(mod, "build_portfolio_report_xlsx", boom)
    try:
        _run(tmp_path)
    except RuntimeError:
        pass
    reports_dir = tmp_path / "reports"
    assert not reports_dir.exists() or list(reports_dir.iterdir()) == []


def test_tool_name_and_llm_facing_args():
    from app.agent.tools.portfolio_report import save_portfolio_report_tool
    assert save_portfolio_report_tool.name == "save_portfolio_report"
    assert set(save_portfolio_report_tool.args) == {"client_name"}


def test_gateway_mode_returns_a_clear_error_instead_of_silently_losing_the_file(monkeypatch):
    # Regression (final review): the tool writes directly to local disk via
    # Path.write_bytes. In gateway mode (MCP_TRANSPORT=gateway, the
    # AgentCore/S3 prod deployment) that disk is the container's own
    # ephemeral storage, not the S3-backed workspace write_file uses --
    # unlike the old generate_portfolio_report + write_file flow, which
    # delegated persistence to the S3-backed MCP filesystem server. A
    # silent "saved successfully" for a file that vanishes when the
    # microVM recycles is worse than an explicit error.
    from app.agent.tools.portfolio_report import save_portfolio_report_tool
    from app.core.config import settings

    monkeypatch.setattr(settings, "MCP_TRANSPORT", "gateway")
    result = asyncio.run(save_portfolio_report_tool.ainvoke({"client_name": "Margaret Collins"}))
    assert "error" in result
    assert "gateway" in result["error"].lower()
