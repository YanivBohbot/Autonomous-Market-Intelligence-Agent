# Portfolio Report Excel + Atomic Save Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the portfolio report's HTML+SVG output with a generated `.xlsx` file (styled table + native pie chart), and collapse the current two-step `generate_portfolio_report` → `write_file` flow into one atomic, self-writing tool so nothing passes through the LLM to be retyped.

**Architecture:** One new tool, `save_portfolio_report_tool(client_name)`, loads a client's portfolio (reusing `load_client_portfolio`, unchanged), builds `.xlsx` bytes in memory (`xlsxwriter`), and writes them directly to `WORKSPACE_ROOT/reports/` itself — no `write_file` call, no HTML/bytes ever appear in a tool argument. Still HITL-gated, but the approval card is a plain action confirmation (no content to preview, by the user's explicit choice during brainstorming).

**Tech Stack:** Python 3.12, LangGraph/LangChain (`create_agent`, `HumanInTheLoopMiddleware`), `xlsxwriter` (new runtime dependency), `openpyxl` (new, test-only dependency), pytest, React/TypeScript/Vite frontend (no changes needed there beyond a tool-name list).

**Spec:** `docs/superpowers/specs/2026-09-30-portfolio-report-excel-design.md`

## Global Constraints

- `xlsxwriter` is a **runtime** dependency (`pyproject.toml` `dependencies`, and `requirements.agentcore.txt`, per `CLAUDE.md`'s dependency-pinning rule for the prod image).
- `openpyxl` is a **test-only** dependency (`pyproject.toml` `[dependency-groups].dev`) — never imported by production code, never added to `requirements.agentcore.txt`.
- No content (HTML, bytes, cell values) is ever passed through an LLM-facing tool argument for this feature — the tool that builds the report is the same tool that writes it to disk.
- `xlsxwriter`'s `Workbook.close()` is a synchronous, blocking call — it must run inside `asyncio.to_thread` so it never blocks the event loop.
- Every tool addition/removal updates `docs/TOOLS.md` in the same change, per `CLAUDE.md`'s "keep `docs/TOOLS.md` in sync" project rule (table row + per-tool section + `READ_ONLY_TOOLS` mention if applicable).
- Full backend (`uv run pytest tests/`) and frontend (`cd frontend && npx vitest run`) suites green before every commit.

## Review Focus

- `save_portfolio_report` must never end up in the single-agent graph's `READ_ONLY_TOOLS` set (`app/agent/tools/__init__.py`) the way its read-only predecessor `generate_portfolio_report` did — it now writes to disk itself, and `READ_ONLY_TOOLS` membership is exactly what lets `approval_node` skip the HITL interrupt. Missing this removal, or (worse) someone reflexively re-adding the new name to that set, ships a side-effect tool with no approval gate in single-agent mode (Task 8).
- Downloading the binary `.xlsx` via `GET /workspace/files/{filename}` must be asserted against raw bytes (`response.content`), not text/string comparison — the existing HTML-era test used `res.text`, which silently mangles or fails to meaningfully compare binary content; a copy-pasted test would give false confidence (Task 3).
- A failure while building the report (bad data, a `xlsxwriter` error) must leave **no** file on disk — the write only happens after the complete bytes are already in hand in memory, so this should hold by construction, but needs a test proving it rather than an assumption (Task 3).
- The client-name resolution that flows through `load_client_portfolio` (e.g. a partial match like `"Collins"` resolving to `"Margaret Collins"`) must produce a filename slug from the **resolved** full name, not the partial input the user typed — this was implicitly true in the old two-call flow and must still hold now that one tool does load+build+write together (Task 3).
- The HITL approval card for `save_portfolio_report` must actually show a client-name-based confirmation once `portfolio_agent.py`'s `interrupt_on` key changes — not assumed from the spec's prose, verified by a test reading the middleware's configured `interrupt_on` mapping (Task 4).

---

### Task 1: Add `xlsxwriter` (runtime) and `openpyxl` (test-only) dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements.agentcore.txt`

**Interfaces:**
- Produces: `xlsxwriter` importable in production code; `openpyxl` importable in test code only.

- [ ] **Step 1: Add the dependencies**

Run:
```bash
cd market-intelligence-agent
uv add xlsxwriter
uv add --group dev openpyxl
```

This updates `pyproject.toml`'s `dependencies` list with `xlsxwriter`, adds `openpyxl` to `[dependency-groups].dev`, and re-resolves `uv.lock`.

- [ ] **Step 2: Verify both import cleanly**

Run: `uv run python -c "import xlsxwriter, openpyxl; print(xlsxwriter.__version__, openpyxl.__version__)"`
Expected: prints two version strings, no `ImportError`.

- [ ] **Step 3: Pin `xlsxwriter` in the AgentCore requirements file**

Read the exact version `uv add` resolved into `uv.lock` (search `uv.lock` for `name = "xlsxwriter"`, note its `version`). In `requirements.agentcore.txt`, add a new line under the `# Tools` section (next to `emails>=0.6`):

```
xlsxwriter==<the exact version from uv.lock>
```

Do **not** add `openpyxl` to this file — it is test-only and must never ship in the prod image.

- [ ] **Step 4: Run the full backend suite**

Run: `uv run pytest tests/ -q`
Expected: all existing tests still pass (no behavior changed yet, this task only adds dependencies).

- [ ] **Step 5: Commit**

```bash
cd market-intelligence-agent
git add pyproject.toml uv.lock requirements.agentcore.txt
git commit -m "build: add xlsxwriter (runtime) and openpyxl (test-only) dependencies"
```

---

### Task 2: `build_portfolio_report_xlsx` — the pure chart+table builder

**Files:**
- Modify: `app/agent/tools/portfolio_report.py` (remove `build_pie_chart_svg`, `build_portfolio_report_html`, and the `_CHART_COLORS`/`_polar_to_cartesian` helpers they used; add `build_portfolio_report_xlsx` and its own `_CHART_COLORS`)
- Modify: `tests/unit/test_portfolio_report.py` (remove every SVG/HTML-era test in this file — `test_single_position_renders_a_full_circle_not_a_degenerate_arc`, `test_multiple_positions_render_one_arc_path_each`, `test_includes_a_legend_entry_per_position_with_ticker_and_percent`, `test_no_nan_or_negative_coordinates_for_a_three_way_split`, `test_empty_positions_raises`, `test_report_contains_client_name_and_exact_copied_numbers`, `test_report_embeds_an_svg_chart`, `test_concentration_note_appears_only_above_threshold`, `test_concentration_note_excludes_etfs_same_as_concentration_screen`, `test_report_is_self_contained_no_external_assets` — all replaced by the xlsx-era tests in Step 1 below)

**Interfaces:**
- Consumes: nothing new — same `portfolio: dict` shape `build_portfolio_report_html` used to take: `{"client_name": str, "positions": [{"ticker", "shares", "price", "market_value", "weight_pct", "sector", ...}], "totals": {"market_value", ...}}`.
- Produces: `build_portfolio_report_xlsx(portfolio: dict, *, threshold_pct: float = 30.0) -> bytes` — Task 3 calls this directly.

- [ ] **Step 1: Write the failing tests**

Replace the entire top portion of `tests/unit/test_portfolio_report.py` (everything above the `import asyncio` / `generate_portfolio_report` section, i.e. lines 1–119 of the current file) with:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_portfolio_report.py -v`
Expected: `ImportError: cannot import name 'build_portfolio_report_xlsx'` (the old tests below this point in the file, still referencing `build_pie_chart_svg`/`build_portfolio_report_html`, will also fail to collect — that's expected, they're deleted in this step, not yet in the file you just wrote if you replaced the whole top section as instructed).

- [ ] **Step 3: Implement `build_portfolio_report_xlsx`**

In `app/agent/tools/portfolio_report.py`, replace the file's docstring, imports, `_CHART_COLORS`, `_polar_to_cartesian`, `build_pie_chart_svg`, and `build_portfolio_report_html` (everything from the top of the file through the end of `build_portfolio_report_html`, i.e. lines 1–129 of the current file) with:

```python
"""`save_portfolio_report` -- a self-loading, deterministic, and
self-writing tool that builds a downloadable Excel portfolio brief
(styled table + a native pie chart) for one named client and saves it to
disk itself.

Same rationale as concentration_screen and client_portfolio: nothing
about this report should depend on an LLM reproducing data correctly. The
chart is a native Excel pie chart built from cell ranges (no hand-computed
arc geometry needed, unlike the SVG version this replaces), and the tool
writes the file itself -- there is no `content` argument for an LLM to
mistype, unlike the write_file-based flow this replaces.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import xlsxwriter
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools.client_portfolio import load_client_portfolio

# Same categorical palette PortfolioPieChart.tsx already uses in the chat --
# copied here (not shared/imported; there is no shared Python/TS config
# layer in this codebase) so the report's chart looks like the app's other
# charts rather than inventing a second palette.
_CHART_COLORS = ["#34d399", "#fbbf24", "#f87171", "#6b7a8d", "#1e3a5f", "#2563eb"]

_SHEET_NAME = "Portfolio Brief"


def build_portfolio_report_xlsx(portfolio: dict, *, threshold_pct: float = 30.0) -> bytes:
    positions = portfolio["positions"]
    if not positions:
        raise ValueError("build_portfolio_report_xlsx needs at least one position")

    client_name = portfolio["client_name"]
    totals = portfolio["totals"]
    today = datetime.now(timezone.utc).date().isoformat()

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    worksheet = workbook.add_worksheet(_SHEET_NAME)

    title_fmt = workbook.add_format({"bold": True, "font_size": 16})
    header_fmt = workbook.add_format({
        "bold": True, "bg_color": "#1e3a5f", "font_color": "#ffffff", "border": 1,
    })
    money_fmt = workbook.add_format({"num_format": "$#,##0.00", "border": 1})
    pct_fmt = workbook.add_format({"num_format": "0.0%", "border": 1})
    cell_fmt = workbook.add_format({"border": 1})
    warn_fmt = workbook.add_format({"font_color": "#b45309", "italic": True})

    worksheet.merge_range("A1:E1", f"Portfolio Brief — {client_name}", title_fmt)
    worksheet.write(1, 0, f"Generated {today}")

    headers = ["Ticker", "Shares", "Price", "Market Value", "Weight"]
    header_row = 3
    for col, header in enumerate(headers):
        worksheet.write(header_row, col, header, header_fmt)

    row = header_row + 1
    for p in positions:
        worksheet.write(row, 0, p["ticker"], cell_fmt)
        worksheet.write(row, 1, p["shares"], cell_fmt)
        worksheet.write(row, 2, p["price"], money_fmt)
        worksheet.write(row, 3, p["market_value"], money_fmt)
        worksheet.write(row, 4, p["weight_pct"] / 100, pct_fmt)
        row += 1

    total_row = row + 1
    worksheet.write(total_row, 0, "Total market value:")
    worksheet.write(total_row, 3, totals["market_value"], money_fmt)

    # Same default exclusion as finance_calc.compute_concentration_screen
    # (exclude_sectors=["ETF"]): a diversified fund over threshold is not
    # the single-stock overweight risk this note exists to flag.
    breaches = [p for p in positions if p["weight_pct"] > threshold_pct and p.get("sector") != "ETF"]
    note_row = total_row + 2
    if breaches:
        names = ", ".join(f'{p["ticker"]} ({p["weight_pct"]:.1f}%)' for p in breaches)
        verb = "exceeds" if len(breaches) == 1 else "exceed"
        worksheet.write(
            note_row, 0,
            f"Concentration note: {names} {verb} {threshold_pct:g}% of the portfolio.",
            warn_fmt,
        )

    # A separate small data table feeds the chart -- Excel charts reference
    # cell ranges, not literal values, so the weights need their own cells.
    chart_data_row = note_row + 2
    worksheet.write(chart_data_row, 0, "Ticker")
    worksheet.write(chart_data_row, 1, "Weight %")
    for i, p in enumerate(positions):
        worksheet.write(chart_data_row + 1 + i, 0, p["ticker"])
        worksheet.write(chart_data_row + 1 + i, 1, p["weight_pct"])
    chart_data_last_row = chart_data_row + len(positions)

    chart = workbook.add_chart({"type": "pie"})
    chart.add_series({
        "name": "Weight %",
        "categories": [_SHEET_NAME, chart_data_row + 1, 0, chart_data_last_row, 0],
        "values": [_SHEET_NAME, chart_data_row + 1, 1, chart_data_last_row, 1],
        "data_labels": {"percentage": True},
        "points": [{"fill": {"color": _CHART_COLORS[i % len(_CHART_COLORS)]}} for i in range(len(positions))],
    })
    chart.set_title({"name": f"{client_name} — Position Weights"})
    worksheet.insert_chart(header_row, 6, chart)

    for col, width in enumerate([12, 10, 12, 14, 10]):
        worksheet.set_column(col, col, width)

    workbook.close()
    return output.getvalue()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_portfolio_report.py -v`
Expected: all tests in the file pass (the `generate_portfolio_report`-era tests further down the file will fail at this point — that's expected, Task 3 replaces them).

- [ ] **Step 5: Commit**

```bash
cd market-intelligence-agent
git add app/agent/tools/portfolio_report.py tests/unit/test_portfolio_report.py
git commit -m "feat(portfolio-report): build the report as a native Excel file, not SVG+HTML"
```

---

### Task 3: `save_portfolio_report` async core + `save_portfolio_report_tool` (atomic load+build+write)

**Files:**
- Modify: `app/agent/tools/portfolio_report.py` (remove `generate_portfolio_report`, `generate_portfolio_report_tool`, `GeneratePortfolioReportInput`; add `save_portfolio_report`, `SavePortfolioReportInput`, `save_portfolio_report_tool`)
- Modify: `tests/unit/test_portfolio_report.py` (remove the `generate_portfolio_report`-era tests at the bottom of the current file — `test_suggested_path_is_under_reports_and_ends_in_html`, `test_html_contains_the_resolved_client_name`, `test_apostrophe_in_client_name_never_reaches_the_filename`, `test_unresolved_client_returns_the_same_error_shape_load_client_portfolio_uses`, `test_tool_name_and_llm_facing_args` — replaced by Step 1 below)
- Modify: `tests/unit/test_workspace_files.py` (add a binary-download regression test)
- Modify: `docs/TOOLS.md`

**Interfaces:**
- Consumes: `build_portfolio_report_xlsx(portfolio: dict, *, threshold_pct: float = 30.0) -> bytes` (Task 2); `load_client_portfolio(*, run_sql, get_price, client_name) -> dict` (`app/agent/tools/client_portfolio.py`, unchanged, returns `{"error": ...}` or `{"client_name", "positions", "totals", "sector_allocation"}`).
- Produces: `async def save_portfolio_report(*, run_sql, get_price, client_name: str, reports_dir: Path) -> dict` returning `{"client_name": str, "filename": str}` or `{"error": str}`. `save_portfolio_report_tool` (LangChain `@tool`, args: `client_name: str` only) — Task 4 registers it on `portfolio_agent`, Task 6 reads its result.

- [ ] **Step 1: Write the failing tests**

Replace everything from `import asyncio` (originally line 121) to the end of `tests/unit/test_portfolio_report.py` with:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_portfolio_report.py -v`
Expected: `ImportError: cannot import name 'save_portfolio_report'`.

- [ ] **Step 3: Implement `save_portfolio_report` and `save_portfolio_report_tool`**

In `app/agent/tools/portfolio_report.py`, replace `generate_portfolio_report`, `GeneratePortfolioReportInput`, and `generate_portfolio_report_tool` (the last three definitions in the current file, everything from `async def generate_portfolio_report` to the end of the file) with:

```python
def _slugify(name: str) -> str:
    # Lowercase, spaces to hyphens, drop anything that isn't alnum/hyphen --
    # a client name can contain an apostrophe (O'Brien) that must never
    # reach a filesystem path unescaped.
    cleaned = "".join(c if c.isalnum() or c in (" ", "-") else "" for c in name.lower())
    return "-".join(cleaned.split())


async def save_portfolio_report(
    *,
    run_sql: Callable[[str], Awaitable[list[dict]]],
    get_price: Callable[[str], Awaitable[float]],
    client_name: str,
    reports_dir: Path,
) -> dict:
    portfolio = await load_client_portfolio(run_sql=run_sql, get_price=get_price, client_name=client_name)
    if "error" in portfolio:
        return portfolio

    # build_portfolio_report_xlsx's Workbook.close() is the actual blocking
    # work (compiling XML, chart data, zipping the file) -- run it in a
    # thread so it never blocks the event loop.
    xlsx_bytes = await asyncio.to_thread(build_portfolio_report_xlsx, portfolio)

    today = datetime.now(timezone.utc).date().isoformat()
    filename = f"{_slugify(portfolio['client_name'])}-portfolio-brief-{today}.xlsx"

    def _write() -> None:
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / filename).write_bytes(xlsx_bytes)

    await asyncio.to_thread(_write)

    return {"client_name": portfolio["client_name"], "filename": filename}


class SavePortfolioReportInput(BaseModel):
    client_name: str = Field(description="Full or partial client name, e.g. 'Margaret Collins' or 'Collins'.")


@tool("save_portfolio_report", args_schema=SavePortfolioReportInput)
async def save_portfolio_report_tool(client_name: str) -> dict:
    """Build and save a downloadable Excel portfolio brief (styled table +
    a native pie chart) for one named client, in one atomic step -- resolves
    the client, fetches holdings and live prices, builds the file, and
    writes it to the workspace itself. There is no separate write_file
    step and no content to pass anywhere. Returns {"client_name",
    "filename"} or {"error"} if the name matches zero or multiple clients."""
    from app.core.config import settings
    from app.agent.tools.concentration import parse_tool_payload, price_from_quote
    from app.agent.tools.mcp_clients.mcp_client import crm_tool
    from app.agent.tools.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"

    async def run_sql(sql: str) -> list[dict]:
        return parse_tool_payload(await crm_tool.ainvoke({"query": sql}))

    async def get_price(ticker: str) -> float:
        return price_from_quote(parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: ticker})))

    reports_dir = settings.WORKSPACE_ROOT.resolve() / "reports"
    return await save_portfolio_report(
        run_sql=run_sql, get_price=get_price, client_name=client_name, reports_dir=reports_dir,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_portfolio_report.py -v`
Expected: all tests pass.

- [ ] **Step 5: Add and verify the binary-download regression test**

In `tests/unit/test_workspace_files.py`, add (after `test_serves_a_report_and_forces_download`):

```python
def test_serves_a_binary_report_byte_for_byte(tmp_path, monkeypatch):
    # Regression: the HTML-era version of this test used res.text (string
    # comparison), which is meaningless for a binary .xlsx file -- a
    # naive copy-paste of that test would give false confidence. Must
    # compare raw bytes.
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    fake_xlsx = b"PK\x03\x04not a real zip but binary enough for this test\x00\xff\xfe"
    (reports / "margaret-collins-portfolio-brief-2026-09-30.xlsx").write_bytes(fake_xlsx)

    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/files/margaret-collins-portfolio-brief-2026-09-30.xlsx")

    assert res.status_code == 200
    assert res.content == fake_xlsx
    assert "attachment" in res.headers["content-disposition"]
```

Run: `uv run pytest tests/unit/test_workspace_files.py -v`
Expected: all tests pass (this route needs no code change — `FileResponse` already streams raw bytes and sets `Content-Disposition: attachment` regardless of file type; this step only proves it with the right kind of assertion).

- [ ] **Step 6: Update `docs/TOOLS.md`**

Replace the `generate_portfolio_report` row (currently row `| 23 |`) in the summary table with:

```
| 23 | `save_portfolio_report` | side-effect | Native (`portfolio_report.py`) -- loads data via `read_query` + `yfinance_get_ticker_info`, writes the file itself | client_name (full or partial) | Resolves the named client, loads holdings + live prices itself, builds a downloadable Excel portfolio brief (positions table + a native pie chart of position weights), and writes it directly to `reports/` -- no separate write step. Gated by HITL approval. | An advisor-facing deliverable for a client meeting, generated and saved in one atomic, deterministic step so nothing an LLM might mistype ever reaches the file. |
```

Remove `"generate_portfolio_report"` from the `READ_ONLY_TOOLS` line (it is no longer read-only — see Task 8).

Replace the `### 23. \`generate_portfolio_report\`` per-tool section with:

```markdown
### 23. `save_portfolio_report`

- **File:** `app/agent/tools/portfolio_report.py`
- **What:** Resolves a named client, loads their holdings and live prices, builds a styled Excel workbook (positions table + native pie chart of position weights) entirely in memory, and writes it directly to `data/workspace/reports/<slug>-portfolio-brief-<date>.xlsx` -- one atomic tool call, gated by HITL approval, no separate write step.
- **Why:** An advisor-facing deliverable for a client meeting. Like `concentration_screen`/`client_portfolio`, nothing here is left to the LLM to compute or reproduce -- the tool that builds the report is the same tool that saves it, so there is no content argument an LLM could mistype on the way to disk.
```

- [ ] **Step 7: Run the full backend suite**

Run: `uv run pytest tests/ -q`
Expected: failures only in `test_multi_agent_portfolio_agent.py` (still references the old tool name/list — fixed in Task 4) and any other file still importing `generate_portfolio_report_tool` (fixed in Task 8). No failures in `test_portfolio_report.py` or `test_workspace_files.py`.

- [ ] **Step 8: Commit**

```bash
cd market-intelligence-agent
git add app/agent/tools/portfolio_report.py tests/unit/test_portfolio_report.py tests/unit/test_workspace_files.py docs/TOOLS.md
git commit -m "feat(portfolio-report): atomic save_portfolio_report tool -- loads, builds, writes in one call"
```

---

### Task 4: Wire `save_portfolio_report_tool` into `portfolio_agent`

**Files:**
- Modify: `app/agent/multi_agent/portfolio_agent.py`
- Modify: `tests/unit/test_multi_agent_portfolio_agent.py`

**Interfaces:**
- Consumes: `save_portfolio_report_tool` (Task 3).
- Produces: `portfolio_agent`'s `_TOOLS` list and `HumanInTheLoopMiddleware` config, read by Task 5 (prompt) and by the graph.

- [ ] **Step 1: Update the failing tests**

In `tests/unit/test_multi_agent_portfolio_agent.py`, replace `test_tools`:

```python
def test_tools():
    names = {t.name.rsplit("___", 1)[-1] for t in mod._TOOLS}
    assert names == {"read_query", "list_tables", "describe_table", "yfinance_get_ticker_info",
                     "portfolio_metrics", "pct_change", "concentration_screen", "client_portfolio",
                     "save_portfolio_report"}
```

Replace `test_create_agent_call`'s `interrupt_on` assertion:

```python
def test_create_agent_call():
    kw = _kwargs()
    from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT
    assert kw["system_prompt"] == PORTFOLIO_SYSTEM_PROMPT
    assert kw["tools"] == mod._TOOLS
    assert kw["name"] == "portfolio_agent"
    base = base_middleware()
    assert [type(m) for m in kw["middleware"][:len(base)]] == [type(m) for m in base]
    hitl = kw["middleware"][len(base)]
    assert isinstance(hitl, HumanInTheLoopMiddleware)
    assert set(hitl.interrupt_on) == {"save_portfolio_report"}
    assert kw["middleware"][-1] is market_desk_display
    assert len(kw["middleware"]) == len(base) + 2
```

Add a new test confirming the approval card shows a plain confirmation, not raw content:

```python
def test_hitl_gate_has_no_content_argument_to_preview():
    # The user explicitly chose a plain action-confirmation card (no data
    # summary) over previewing content, since HITL fires before the tool
    # runs and there is no result yet to show. save_portfolio_report's
    # only argument is client_name -- there is nothing content-shaped in
    # the approval card by construction.
    save_tool = next(t for t in mod._TOOLS if t.name == "save_portfolio_report")
    assert set(save_tool.args) == {"client_name"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_multi_agent_portfolio_agent.py -v`
Expected: `test_tools` and `test_create_agent_call` FAIL (still importing/expecting `generate_portfolio_report`, `write_file`); `test_hitl_gate_has_no_content_argument_to_preview` FAILS with `ImportError` (module still references old tools).

- [ ] **Step 3: Update `portfolio_agent.py`**

In `app/agent/multi_agent/portfolio_agent.py`, replace:

```python
from app.agent.tools import (
    client_portfolio_tool,
    concentration_screen_tool,
    crm_describe_table_tool,
    crm_list_tables_tool,
    crm_tool,
    fs_write_file_tool,
    generate_portfolio_report_tool,
    pct_change_tool,
    portfolio_metrics_tool,
    yf_quote_tool,
)

# Everything a portfolio computation needs lives in this one specialist: the
# supervisor finishes as soon as a specialist returns a plain answer, so
# chaining crm -> finance -> calc across specialists would not work. Same
# reasoning extends to write_file: portfolio_agent needs it directly so
# "generate a report, then save it" happens in one turn, not a two-hop
# handoff to filesystem_agent that depends on the router recognizing the
# answer as incomplete.
_TOOLS = [
    crm_tool,
    crm_list_tables_tool,
    crm_describe_table_tool,
    yf_quote_tool,
    portfolio_metrics_tool,
    pct_change_tool,
    concentration_screen_tool,
    client_portfolio_tool,
    generate_portfolio_report_tool,
    fs_write_file_tool,
]
```

with:

```python
from app.agent.tools import (
    client_portfolio_tool,
    concentration_screen_tool,
    crm_describe_table_tool,
    crm_list_tables_tool,
    crm_tool,
    pct_change_tool,
    portfolio_metrics_tool,
    save_portfolio_report_tool,
    yf_quote_tool,
)

# Everything a portfolio computation needs lives in this one specialist: the
# supervisor finishes as soon as a specialist returns a plain answer, so
# chaining crm -> finance -> calc across specialists would not work.
# save_portfolio_report_tool loads, builds, and writes the report itself in
# one atomic call -- no write_file, no chaining to filesystem_agent, and
# nothing content-shaped for the LLM to touch.
_TOOLS = [
    crm_tool,
    crm_list_tables_tool,
    crm_describe_table_tool,
    yf_quote_tool,
    portfolio_metrics_tool,
    pct_change_tool,
    concentration_screen_tool,
    client_portfolio_tool,
    save_portfolio_report_tool,
]
```

Replace `HumanInTheLoopMiddleware(interrupt_on={"write_file": True})` with `HumanInTheLoopMiddleware(interrupt_on={"save_portfolio_report": True})`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_multi_agent_portfolio_agent.py -v`
Expected: all pass.

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest tests/ -q`
Expected: failures only in `test_multi_agent_supervisor_routing.py`-adjacent files that still assert on the old prompt text (Task 5) and `app/agent/tools/__init__.py`-dependent files (Task 8).

- [ ] **Step 6: Commit**

```bash
cd market-intelligence-agent
git add app/agent/multi_agent/portfolio_agent.py tests/unit/test_multi_agent_portfolio_agent.py
git commit -m "feat(multi-agent): portfolio_agent uses the atomic save_portfolio_report tool"
```

---

### Task 5: Rewrite `PORTFOLIO_SYSTEM_PROMPT`'s tool list and Report recipe

**Files:**
- Modify: `app/agent/prompts/specialist_agent_prompts.py`
- Modify: `tests/unit/test_multi_agent_portfolio_agent.py`

**Interfaces:**
- Consumes: nothing new (prose only).
- Produces: `PORTFOLIO_SYSTEM_PROMPT` (str), read by `portfolio_agent.py` (already wired via `build_portfolio_agent`, no signature change).

- [ ] **Step 1: Update the failing test**

In `tests/unit/test_multi_agent_portfolio_agent.py`, replace the two prompt-content tests added in the previous session's final review:

```python
def test_portfolio_recipe_defers_to_report_recipe_for_save_or_export_requests():
    from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT

    portfolio_bullet = PORTFOLIO_SYSTEM_PROMPT.split("Portfolio recipe:")[1].split("\n-")[0]
    assert "report recipe" in portfolio_bullet.lower()


def test_report_recipe_calls_the_single_atomic_save_tool():
    # Regression: the old two-tool recipe (generate_portfolio_report then
    # write_file with its output pasted in) is gone -- there is exactly
    # one tool call now, and nothing about "unedited"/"pass its output"
    # should remain, since there is no longer any content to pass.
    from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT

    report_section = PORTFOLIO_SYSTEM_PROMPT.split("Report recipe:")[1]
    assert "save_portfolio_report" in report_section
    assert "generate_portfolio_report" not in PORTFOLIO_SYSTEM_PROMPT
    assert "write_file" not in PORTFOLIO_SYSTEM_PROMPT
    example = report_section.split("Example:", 1)[1]
    assert "save_portfolio_report" in example
    assert "client_portfolio" in example
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_multi_agent_portfolio_agent.py::test_report_recipe_calls_the_single_atomic_save_tool -v`
Expected: FAIL — `PORTFOLIO_SYSTEM_PROMPT` still contains `generate_portfolio_report` and `write_file`.

- [ ] **Step 3: Rewrite the prompt**

In `app/agent/prompts/specialist_agent_prompts.py`, replace tool-list entries #9 and #10:

```
9. `generate_portfolio_report` — build a downloadable HTML portfolio brief (positions table + a weight pie chart) for one named client (args: `client_name: str`, full or partial). The tool itself resolves the client, reads their holdings, and fetches live prices — do NOT call `client_portfolio` or fetch prices first. Returns `{client_name, suggested_path, html}` or `{error: ...}` on zero/multiple client matches. Never writes the file itself — pass `html`/`suggested_path` to `write_file` below.
10. `write_file` — save the report `generate_portfolio_report` built (args: `path: str`, `content: str`). This is a side-effect tool and requires human approval — the platform itself pauses and shows the user an approve/edit/reject card before it runs. Just call the tool directly with the path and content; do not ask the user to confirm in your reply first — that only adds an extra back-and-forth before the real approval card even appears.
```

with one entry:

```
9. `save_portfolio_report` — build AND save a downloadable Excel portfolio brief (positions table + a native pie chart) for one named client, in one call (args: `client_name: str`, full or partial). The tool itself resolves the client, reads their holdings, fetches live prices, builds the file, and writes it to the workspace — there is nothing else to call afterward and nothing to pass it. This is a side-effect tool and requires human approval — the platform pauses and shows an approve/edit/reject card before it runs. Just call the tool directly with `client_name`; do not ask the user to confirm in your reply first — that only adds an extra back-and-forth before the real approval card even appears.
```

Replace the "Report recipe" bullet and its worked example:

```
- Report recipe: for any "save/export/generate a brief or report" request about a named client, call `generate_portfolio_report` (it loads its own data -- no `client_portfolio` call needed first) then `write_file` with its `html` and `suggested_path` values exactly as returned -- do not edit, summarize, or reformat the HTML.

Example:
  User: "Generate a portfolio report for Margaret Collins and save it"
  Correct: call `generate_portfolio_report(client_name="Margaret Collins")`, then `write_file` with its returned `suggested_path`/`html`. Do NOT call `client_portfolio` -- the request asks to generate and save a report, not just view a breakdown, even though it says "portfolio".
  Wrong: calling only `client_portfolio` and replying "I've generated the portfolio report" without ever calling `generate_portfolio_report` or `write_file` -- this shows a table but saves nothing, and the claim of having generated a report is false.
```

with:

```
- Report recipe: for any "save/export/generate a brief or report" request about a named client, call `save_portfolio_report` directly with `client_name` (it loads its own data, builds the file, and writes it -- no `client_portfolio` call needed first, and no second call afterward).

Example:
  User: "Generate a portfolio report for Margaret Collins and save it"
  Correct: call `save_portfolio_report(client_name="Margaret Collins")` — one call, nothing else needed. Do NOT call `client_portfolio` -- the request asks to generate and save a report, not just view a breakdown, even though it says "portfolio".
  Wrong: calling only `client_portfolio` and replying "I've generated the portfolio report" without ever calling `save_portfolio_report` -- this shows a table but saves nothing, and the claim of having generated a report is false.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_multi_agent_portfolio_agent.py -v`
Expected: all pass.

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest tests/ -q`
Expected: no remaining failures caused by `PORTFOLIO_SYSTEM_PROMPT` content. `test_multi_agent_supervisor_routing.py` should already be unaffected — its own worked example was about the supervisor's routing prompt, not `PORTFOLIO_SYSTEM_PROMPT`, and doesn't reference `generate_portfolio_report`/`write_file` in a way that changed. Remaining failures should only be in `app/agent/tools/__init__.py`-dependent files (Task 8).

- [ ] **Step 6: Commit**

```bash
cd market-intelligence-agent
git add app/agent/prompts/specialist_agent_prompts.py tests/unit/test_multi_agent_portfolio_agent.py
git commit -m "feat(prompts): portfolio_agent's Report recipe calls the single atomic save tool"
```

---

### Task 6: Replace the `write_file`-keyed display normalizer with a `save_portfolio_report`-keyed one

**Files:**
- Modify: `app/agent/multi_agent/display.py`
- Modify: `tests/unit/test_display_normalizers.py`

**Interfaces:**
- Consumes: `save_portfolio_report_tool`'s result shape `{"client_name": str, "filename": str}` (Task 3) — read from the tool's **result** (JSON text), not its args, since the only argument is `client_name`.
- Produces: `DISPLAY_NORMALIZERS["save_portfolio_report"]`, read by `useToolDisplay.tsx` (Task 7) via the `report_file` display type (unchanged payload shape: `{"type": "report_file", "filename": str, "url": str}`).

- [ ] **Step 1: Update the failing tests**

In `tests/unit/test_display_normalizers.py`, replace the three `normalize_report_file` tests:

```python
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
```

with:

```python
def test_normalize_saved_report_reads_the_filename_from_the_tool_result():
    # save_portfolio_report has no "path" argument -- its only argument is
    # client_name -- so the normalizer reads the filename from the tool's
    # RESULT (its JSON text), unlike the old write_file-args-based version.
    text = json.dumps({"client_name": "Margaret Collins", "filename": "margaret-collins-portfolio-brief-2026-09-30.xlsx"})
    displays = display.DISPLAY_NORMALIZERS["save_portfolio_report"](text, {"client_name": "Margaret Collins"})
    assert displays == [{
        "type": "report_file",
        "filename": "margaret-collins-portfolio-brief-2026-09-30.xlsx",
        "url": "/workspace/files/margaret-collins-portfolio-brief-2026-09-30.xlsx",
    }]


def test_normalize_saved_report_on_a_resolution_error_shows_nothing():
    text = json.dumps({"error": "No client matching 'Nobody Real' found, or they have no holdings."})
    assert display.DISPLAY_NORMALIZERS["save_portfolio_report"](text, {"client_name": "Nobody Real"}) == []


def test_write_file_has_no_special_casing_anymore():
    # portfolio_agent no longer calls write_file at all -- it reverts to
    # having no normalizer, exactly as it was before the original HTML
    # report feature existed. filesystem_agent's plain writes fall through
    # to CopilotKit's default card via the same "unregistered tool" path
    # every other tool uses.
    assert "write_file" not in display.DISPLAY_NORMALIZERS
```

(`json` is already imported at the top of this test file — check before adding a duplicate import.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_display_normalizers.py -v`
Expected: `test_normalize_saved_report_reads_the_filename_from_the_tool_result` and `test_normalize_saved_report_on_a_resolution_error_shows_nothing` FAIL with `KeyError: 'save_portfolio_report'`; `test_write_file_has_no_special_casing_anymore` FAILS (currently `"write_file"` IS in `DISPLAY_NORMALIZERS`).

- [ ] **Step 3: Replace the normalizer**

In `app/agent/multi_agent/display.py`, replace:

```python
def normalize_report_file(text: str, args: dict) -> list[dict]:
    path = args.get("path", "")
    if not path.startswith("reports/"):
        return []  # a plain filesystem_agent write (e.g. notes.txt) -- not a report, no card
    filename = Path(path).name
    return [{"type": "report_file", "filename": filename, "url": f"/workspace/files/{filename}"}]


DISPLAY_NORMALIZERS["search_knowledge_base"] = normalize_rag_sources
DISPLAY_NORMALIZERS["browser_take_screenshot"] = normalize_screenshot
DISPLAY_NORMALIZERS["write_file"] = normalize_report_file
```

with:

```python
def normalize_saved_report(text: str, args: dict) -> list[dict]:
    data = json.loads(text)
    if "error" in data:
        return []
    filename = data["filename"]
    return [{"type": "report_file", "filename": filename, "url": f"/workspace/files/{filename}"}]


DISPLAY_NORMALIZERS["search_knowledge_base"] = normalize_rag_sources
DISPLAY_NORMALIZERS["browser_take_screenshot"] = normalize_screenshot
DISPLAY_NORMALIZERS["save_portfolio_report"] = normalize_saved_report
```

`Path` is still used by `normalize_screenshot` above, so keep the `from pathlib import Path` import.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_display_normalizers.py -v`
Expected: all pass.

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest tests/ -q`
Expected: no remaining failures in `display.py`-dependent files. Remaining failures should only be in `app/agent/tools/__init__.py`-dependent files (Task 8).

- [ ] **Step 6: Commit**

```bash
cd market-intelligence-agent
git add app/agent/multi_agent/display.py tests/unit/test_display_normalizers.py
git commit -m "feat(multi-agent): display normalizer reads the saved report's filename from the tool result"
```

---

### Task 7: Update the frontend's displayable-tools list

**Files:**
- Modify: `frontend/src/desk/displays/useToolDisplay.tsx`
- Modify: `frontend/src/desk/displays/useToolDisplay.test.tsx`

**Interfaces:**
- Consumes: nothing new — `ReportFileCard` (already generic, unchanged) still renders `{filename, url}`.
- Produces: nothing new for later tasks — this is the last file this plan touches.

- [ ] **Step 1: Update the failing test**

In `frontend/src/desk/displays/useToolDisplay.test.tsx`, replace the tool-count test:

```tsx
  it("registers a renderer for all 9 displayable tools", () => {
    render(<Harness />);
    expect(Object.keys(registrations).sort()).toEqual([
      "browser_take_screenshot", "client_portfolio", "concentration_screen", "portfolio_metrics",
      "search_knowledge_base", "write_file", "yfinance_get_price_history", "yfinance_get_ticker_info",
      "yfinance_get_ticker_news",
    ]);
  });
```

with:

```tsx
  it("registers a renderer for all 9 displayable tools", () => {
    render(<Harness />);
    expect(Object.keys(registrations).sort()).toEqual([
      "browser_take_screenshot", "client_portfolio", "concentration_screen", "portfolio_metrics",
      "save_portfolio_report", "search_knowledge_base", "yfinance_get_price_history",
      "yfinance_get_ticker_info", "yfinance_get_ticker_news",
    ]);
  });
```

Update the existing report-card test to use `"save_portfolio_report"` instead of `"write_file"`:

```tsx
  it("renders a download card for a report_file display", () => {
    render(<Harness />);
    const envelope = JSON.stringify({
      summary: "Report saved.",
      displays: [{ type: "report_file", filename: "brief.html", url: "/workspace/files/brief.html" }],
    });
    render(<>{registrations["write_file"]({ status: "complete", result: envelope })}</>);
    expect(screen.getByText("brief.html")).toBeInTheDocument();
  });
```

becomes:

```tsx
  it("renders a download card for a report_file display", () => {
    render(<Harness />);
    const envelope = JSON.stringify({
      summary: "Report saved.",
      displays: [{ type: "report_file", filename: "brief.xlsx", url: "/workspace/files/brief.xlsx" }],
    });
    render(<>{registrations["save_portfolio_report"]({ status: "complete", result: envelope })}</>);
    expect(screen.getByText("brief.xlsx")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd market-intelligence-agent/frontend && npx vitest run src/desk/displays/useToolDisplay.test.tsx`
Expected: FAIL — `"write_file"` still in the registered list, `"save_portfolio_report"` missing, `registrations["save_portfolio_report"]` is `undefined`.

- [ ] **Step 3: Update `useToolDisplay.tsx`**

In `frontend/src/desk/displays/useToolDisplay.tsx`, replace:

```tsx
const DISPLAYABLE_TOOLS = [
  "portfolio_metrics",
  "concentration_screen",
  "client_portfolio",
  "yfinance_get_price_history",
  "yfinance_get_ticker_info",
  "yfinance_get_ticker_news",
  "search_knowledge_base",
  "browser_take_screenshot",
  "write_file",
] as const;

// One named registration per tool — leaves every other tool call (read_query,
// save_memory, browser_navigate, browser_snapshot, send_email, ...) to
// CopilotKit's own default card, completely untouched. write_file is
// registered too, but its normalizer (display.py) only produces a display
// for a path under "reports/" -- a plain filesystem_agent write still falls
// through to the default card via the same "no displays" path every other
// unregistered tool uses.
```

with:

```tsx
const DISPLAYABLE_TOOLS = [
  "portfolio_metrics",
  "concentration_screen",
  "client_portfolio",
  "yfinance_get_price_history",
  "yfinance_get_ticker_info",
  "yfinance_get_ticker_news",
  "search_knowledge_base",
  "browser_take_screenshot",
  "save_portfolio_report",
] as const;

// One named registration per tool — leaves every other tool call (read_query,
// save_memory, browser_navigate, browser_snapshot, send_email, write_file,
// ...) to CopilotKit's own default card, completely untouched.
// save_portfolio_report is the only write-shaped tool registered here: it
// builds and saves the report in one atomic call, so there is exactly one
// tool name to watch for the report_file card.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd market-intelligence-agent/frontend && npx vitest run src/desk/displays/useToolDisplay.test.tsx`
Expected: all passing.

- [ ] **Step 5: Run the full frontend suite**

Run: `cd market-intelligence-agent/frontend && npx vitest run`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
cd market-intelligence-agent
git add frontend/src/desk/displays/useToolDisplay.tsx frontend/src/desk/displays/useToolDisplay.test.tsx
git commit -m "feat(frontend): watch save_portfolio_report for the ReportFileCard, not write_file"
```

---

### Task 8: Single-agent registry — swap the tool, and keep it OFF `READ_ONLY_TOOLS`

**Files:**
- Modify: `app/agent/tools/__init__.py`
- Modify: `tests/unit/test_wealth_tools_registration.py` (or a new adjacent test — see Step 1)

**Interfaces:**
- Consumes: `save_portfolio_report_tool` (Task 3).
- Produces: nothing further — this is the plan's final task.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_wealth_tools_registration.py`, add (this test targets the Review Focus item at the top of this plan — `save_portfolio_report` must never be treated as read-only, since it now writes to disk itself):

```python
def test_save_portfolio_report_is_registered_but_not_read_only():
    # Regression risk this plan introduces: generate_portfolio_report (the
    # tool this replaces) WAS read-only, since it never wrote anything
    # itself. save_portfolio_report DOES write to disk now -- if it were
    # ever added to READ_ONLY_TOOLS (by habit, copying the old entry), the
    # single-agent graph's approval_node would skip the HITL interrupt
    # entirely and the tool would execute with no approval gate at all.
    assert "save_portfolio_report" in _names()
    assert "save_portfolio_report" not in READ_ONLY_TOOLS
    assert not is_read_only("save_portfolio_report")
    assert not is_read_only("sqlite-crm___save_portfolio_report")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_wealth_tools_registration.py::test_save_portfolio_report_is_registered_but_not_read_only -v`
Expected: FAIL — `save_portfolio_report` not yet in `_names()` (module still imports `generate_portfolio_report_tool`).

- [ ] **Step 3: Update `app/agent/tools/__init__.py`**

Replace the import:

```python
from app.agent.tools.portfolio_report import generate_portfolio_report_tool
```

with:

```python
from app.agent.tools.portfolio_report import save_portfolio_report_tool
```

In the `TOOLS` list, replace `generate_portfolio_report_tool,` with `save_portfolio_report_tool,` (same position).

In `_BASE_READ_ONLY_TOOLS`, remove the `"generate_portfolio_report",` line entirely — do **not** add `"save_portfolio_report"` in its place; it is a side-effect tool now and must stay gated.

In `__all__`, replace `"generate_portfolio_report_tool",` with `"save_portfolio_report_tool",`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_wealth_tools_registration.py -v`
Expected: all pass.

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest tests/ -q`
Expected: all tests pass, no remaining references to `generate_portfolio_report_tool` anywhere in the codebase.

Run: `grep -rn "generate_portfolio_report" app/ tests/ docs/TOOLS.md` — expected: no output (only comment/docstring references in `test_multi_agent_supervisor_routing.py`'s regression-comment prose and `test_workspace_files.py`'s module docstring are acceptable to remain, since they describe historical context, not code that runs — if grep finds anything else, it's a leftover reference that needs fixing before this task is done).

- [ ] **Step 6: Commit**

```bash
cd market-intelligence-agent
git add app/agent/tools/__init__.py tests/unit/test_wealth_tools_registration.py
git commit -m "feat(tools): register save_portfolio_report in the single-agent graph, kept off READ_ONLY_TOOLS"
```

---
