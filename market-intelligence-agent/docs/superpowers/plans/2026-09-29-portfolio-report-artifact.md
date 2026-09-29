# Portfolio Report Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the advisor ask for a client's portfolio brief and get a downloadable, self-contained HTML report (positions table + an SVG pie chart of position weights) with a download button right in the Market Desk chat.

**Architecture:** A new deterministic, read-only LangChain tool (`generate_portfolio_report`) loads a named client's holdings and live prices itself (reusing `client_portfolio.py`'s data loader) and renders a self-contained HTML string with an inline, hand-computed SVG pie chart — no LLM arithmetic, no new dependency. `portfolio_agent` gains this tool plus `write_file` (with its own HITL approval gate) so it can compute and save in one turn. A new `GET /workspace/files/{filename}` route serves anything saved under `reports/`, and a new `report_file` display type renders a compact download card in the chat, following the exact same `useRenderTool` pattern already used for portfolio tables, screenshots, and RAG sources.

**Tech Stack:** Python (LangChain tools, FastAPI, pytest), TypeScript/React (Vite, Vitest, Tailwind), no new dependencies on either side.

**Spec:** `docs/superpowers/specs/2026-09-29-portfolio-report-artifact-design.md`

## Global Constraints

- Reports are self-contained HTML: inline SVG chart, inline `<style>`, no external assets, no network calls at render time.
- No new Python or npm dependencies — the chart is hand-computed SVG (arc geometry only), not `matplotlib`/`weasyprint`/a charting library.
- `generate_portfolio_report` is read-only (added to `READ_ONLY_TOOLS`); `write_file` remains the only HITL-gated write path in the app — the new tool never writes anything itself.
- Reports always live under `WORKSPACE_ROOT/reports/`; `generate_portfolio_report`'s `suggested_path` always starts with `"reports/"`.
- The chat card is a download button only — no inline chart/table preview in the card (explicitly declined during brainstorming).
- Full backend (`uv run pytest tests/`) and frontend (`npx vitest run`) suites must be green before every commit — no exceptions, matching this project's established discipline.

## Review Focus

- A client name matching zero or multiple clients when generating a report — must return the same `{"error": ...}` shape `load_client_portfolio` already produces, never crash or write a garbage file (Task 3).
- A client with exactly one position (100% weight) — the SVG pie chart's single-slice case; an SVG arc can't express a full 360° sweep as one path, so this needs an explicit special case, not silent breakage (Task 1).
- `write_file` called with a path that does **not** start with `"reports/"` (e.g. `filesystem_agent` still writing `notes.txt`) — the new normalizer must return `[]` so no download card appears, and must not error just because a different specialist called the same shared tool name (Task 7).
- The new `/workspace/files/{filename}` route must reject path traversal (`../`) exactly like the existing screenshots route already does — a new route is a new place to regress that protection if copied carelessly (Task 6).
- A client name with characters unsafe for a filename (e.g. `"O'Brien"`) — the slug builder must never let a raw apostrophe or path separator reach `write_file`'s `path` argument (Task 3).

---

### Task 1: SVG pie chart builder (pure function)

**Files:**
- Create: `app/agent/tools/portfolio_report.py`
- Test: `tests/unit/test_portfolio_report.py`

**Interfaces:**
- Produces: `build_pie_chart_svg(positions: list[dict], *, size: int = 220) -> str`, where each position dict has at least `{"ticker": str, "weight_pct": float}`. Returns a complete `<svg ...>...</svg>` string. Raises `ValueError` if `positions` is empty.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_portfolio_report.py`:

```python
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
    assert "-" not in re.sub(r"weight|width|height", "", svg).replace("stroke", "")  # no negative numbers outside those words


def test_empty_positions_raises():
    with pytest.raises(ValueError, match="at least one position"):
        build_pie_chart_svg([])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_portfolio_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agent.tools.portfolio_report'`

- [ ] **Step 3: Write the minimal implementation**

Create `app/agent/tools/portfolio_report.py`:

```python
"""`generate_portfolio_report` — a self-loading, deterministic tool that
builds a downloadable HTML portfolio brief (positions table + an inline SVG
pie chart) for one named client.

Same rationale as concentration_screen and client_portfolio: a chart needs
real arc-angle math, which an LLM asked to hand-write SVG path data is just
as unreliable at as an LLM asked to sum a portfolio's market value itself
(the bug client_portfolio.py exists to prevent). This module computes the
chart in pure Python -- no LLM arithmetic, no matplotlib/weasyprint
dependency, one self-contained HTML file with the chart inlined as SVG.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

# Same categorical palette PortfolioPieChart.tsx already uses in the chat --
# copied here (not shared/imported; there is no shared Python/TS config
# layer in this codebase) so the report's chart looks like the app's other
# charts rather than inventing a second palette.
_CHART_COLORS = ["#34d399", "#fbbf24", "#f87171", "#6b7a8d", "#1e3a5f", "#2563eb"]


def _polar_to_cartesian(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    # -90 so 0% starts at the top (12 o'clock), matching the app's other pie chart.
    angle_rad = math.radians(angle_deg - 90)
    return cx + r * math.cos(angle_rad), cy + r * math.sin(angle_rad)


def build_pie_chart_svg(positions: list[dict], *, size: int = 220) -> str:
    if not positions:
        raise ValueError("build_pie_chart_svg needs at least one position")

    cx = cy = size / 2
    r = size / 2 - 10

    if len(positions) == 1:
        # An SVG arc can't express a full 360° sweep as one path (the start
        # and end points coincide) -- draw a plain circle instead.
        arcs = f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{_CHART_COLORS[0]}" />'
    else:
        parts = []
        angle = 0.0
        for i, p in enumerate(positions):
            sweep = p["weight_pct"] / 100 * 360
            end_angle = angle + sweep
            start_x, start_y = _polar_to_cartesian(cx, cy, r, angle)
            end_x, end_y = _polar_to_cartesian(cx, cy, r, end_angle)
            large_arc = 1 if sweep > 180 else 0
            color = _CHART_COLORS[i % len(_CHART_COLORS)]
            parts.append(
                f'<path d="M {cx:.2f} {cy:.2f} L {start_x:.2f} {start_y:.2f} '
                f'A {r:.2f} {r:.2f} 0 {large_arc} 1 {end_x:.2f} {end_y:.2f} Z" fill="{color}" />'
            )
            angle = end_angle
        arcs = "".join(parts)

    legend_parts = []
    for i, p in enumerate(positions):
        color = _CHART_COLORS[i % len(_CHART_COLORS)]
        y = 20 + i * 18
        legend_parts.append(
            f'<circle cx="{size + 15}" cy="{y}" r="5" fill="{color}" />'
            f'<text x="{size + 28}" y="{y + 4}" font-size="12" font-family="sans-serif">'
            f'{p["ticker"]} {p["weight_pct"]:.1f}%</text>'
        )
    legend = "".join(legend_parts)

    width = size + 140
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{size}" '
        f'viewBox="0 0 {width} {size}">{arcs}{legend}</svg>'
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_portfolio_report.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd market-intelligence-agent
git add app/agent/tools/portfolio_report.py tests/unit/test_portfolio_report.py
git commit -m "feat(multi-agent): add build_pie_chart_svg, a pure SVG pie-chart builder"
```

---

### Task 2: HTML report builder (pure function)

**Files:**
- Modify: `app/agent/tools/portfolio_report.py`
- Test: `tests/unit/test_portfolio_report.py`

**Interfaces:**
- Consumes: `build_pie_chart_svg` (Task 1).
- Produces: `build_portfolio_report_html(portfolio: dict, *, threshold_pct: float = 30.0) -> str`, where `portfolio` is exactly the dict `load_client_portfolio` (`app/agent/tools/client_portfolio.py`) returns on success: `{"client_name": str, "positions": [{"ticker", "shares", "price", "market_value", "weight_pct", ...}], "totals": {"market_value": float, ...}, "sector_allocation": ...}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_portfolio_report.py`:

```python
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
    assert "http://" not in html and "https://" not in html
    assert "<img" not in html  # the only image-like content is the inline <svg>
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_portfolio_report.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_portfolio_report_html'`

- [ ] **Step 3: Write the minimal implementation**

Append to `app/agent/tools/portfolio_report.py`:

```python
def build_portfolio_report_html(portfolio: dict, *, threshold_pct: float = 30.0) -> str:
    client_name = portfolio["client_name"]
    positions = portfolio["positions"]
    totals = portfolio["totals"]
    today = datetime.now(timezone.utc).date().isoformat()

    rows = "".join(
        f'<tr><td>{p["ticker"]}</td><td>{p["shares"]:g}</td>'
        f'<td>${p["price"]:,.2f}</td><td>${p["market_value"]:,.2f}</td>'
        f'<td>{p["weight_pct"]:.1f}%</td></tr>'
        for p in positions
    )

    breaches = [p for p in positions if p["weight_pct"] > threshold_pct]
    concentration_note = ""
    if breaches:
        names = ", ".join(f'{p["ticker"]} ({p["weight_pct"]:.1f}%)' for p in breaches)
        verb = "exceeds" if len(breaches) == 1 else "exceed"
        concentration_note = (
            f'<p class="warning">Concentration note: {names} {verb} '
            f'{threshold_pct:g}% of the portfolio.</p>'
        )

    chart_svg = build_pie_chart_svg([
        {"ticker": p["ticker"], "weight_pct": p["weight_pct"]} for p in positions
    ])

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Portfolio Brief — {client_name}</title>
<style>
body {{ font-family: -apple-system, Arial, sans-serif; color: #1a1a1a; background: #fff; max-width: 720px; margin: 40px auto; padding: 0 20px; }}
h1 {{ font-size: 20px; }}
table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #e2e2e2; font-size: 13px; }}
th {{ color: #666; font-weight: 600; }}
.warning {{ color: #b45309; font-size: 13px; }}
.total {{ font-weight: 600; margin-top: 8px; }}
</style></head>
<body>
<h1>Portfolio Brief — {client_name}</h1>
<p>Generated {today}</p>
<table><thead><tr><th>Ticker</th><th>Shares</th><th>Price</th><th>Market Value</th><th>Weight</th></tr></thead>
<tbody>{rows}</tbody></table>
<p class="total">Total market value: ${totals["market_value"]:,.2f}</p>
{concentration_note}
{chart_svg}
</body></html>"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_portfolio_report.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
cd market-intelligence-agent
git add app/agent/tools/portfolio_report.py tests/unit/test_portfolio_report.py
git commit -m "feat(multi-agent): add build_portfolio_report_html, self-contained HTML brief"
```

---

### Task 3: `generate_portfolio_report` tool (self-loading, like `client_portfolio`)

**Files:**
- Modify: `app/agent/tools/portfolio_report.py`
- Test: `tests/unit/test_portfolio_report.py`

**Interfaces:**
- Consumes: `load_client_portfolio` (`app/agent/tools/client_portfolio.py`, existing: `async def load_client_portfolio(*, run_sql, get_price, client_name: str) -> dict`), `build_portfolio_report_html` (Task 2), `parse_tool_payload` and `price_from_quote` (`app/agent/tools/concentration.py`, existing, both public).
- Produces: `async def generate_portfolio_report(*, run_sql, get_price, client_name: str) -> dict` — the testable core, returning either `{"error": str}` (client not resolved) or `{"client_name": str, "suggested_path": str, "html": str}` where `suggested_path` always starts with `"reports/"`. Also produces the LangChain tool `generate_portfolio_report_tool` (name `"generate_portfolio_report"`, single arg `client_name: str`), the thin MCP-wiring wrapper other code imports.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_portfolio_report.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_portfolio_report.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate_portfolio_report'`

- [ ] **Step 3: Write the minimal implementation**

Append to `app/agent/tools/portfolio_report.py` (add these imports to the top of the file alongside the existing ones):

```python
from collections.abc import Awaitable, Callable

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools.client_portfolio import load_client_portfolio
```

Then append:

```python
def _slugify(name: str) -> str:
    # Lowercase, spaces to hyphens, drop anything that isn't alnum/hyphen --
    # a client name can contain an apostrophe (O'Brien) that must never
    # reach a filesystem path unescaped.
    cleaned = "".join(c if c.isalnum() or c in (" ", "-") else "" for c in name.lower())
    return "-".join(cleaned.split())


async def generate_portfolio_report(
    *,
    run_sql: Callable[[str], Awaitable[list[dict]]],
    get_price: Callable[[str], Awaitable[float]],
    client_name: str,
) -> dict:
    portfolio = await load_client_portfolio(run_sql=run_sql, get_price=get_price, client_name=client_name)
    if "error" in portfolio:
        return portfolio

    html = build_portfolio_report_html(portfolio)
    today = datetime.now(timezone.utc).date().isoformat()
    suggested_path = f"reports/{_slugify(portfolio['client_name'])}-portfolio-brief-{today}.html"
    return {"client_name": portfolio["client_name"], "suggested_path": suggested_path, "html": html}


class GeneratePortfolioReportInput(BaseModel):
    client_name: str = Field(description="Full or partial client name, e.g. 'Margaret Collins' or 'Collins'.")


@tool("generate_portfolio_report", args_schema=GeneratePortfolioReportInput)
async def generate_portfolio_report_tool(client_name: str) -> dict:
    """Build a downloadable HTML portfolio brief (positions table + a weight
    pie chart) for one named client. Resolves the client and fetches
    holdings and live prices itself -- do NOT call client_portfolio or fetch
    prices first, just pass client_name. Returns {"client_name",
    "suggested_path" (always under "reports/"), "html"} or {"error"} if the
    name matches zero or multiple clients. Pass the html value UNEDITED as
    write_file's content and suggested_path as its path -- do not
    summarize, truncate, or reformat the HTML yourself."""
    from app.agent.tools.concentration import parse_tool_payload, price_from_quote
    from app.agent.tools.mcp_clients.mcp_client import crm_tool
    from app.agent.tools.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"

    async def run_sql(sql: str) -> list[dict]:
        return parse_tool_payload(await crm_tool.ainvoke({"query": sql}))

    async def get_price(ticker: str) -> float:
        return price_from_quote(parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: ticker})))

    return await generate_portfolio_report(run_sql=run_sql, get_price=get_price, client_name=client_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_portfolio_report.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
cd market-intelligence-agent
git add app/agent/tools/portfolio_report.py tests/unit/test_portfolio_report.py
git commit -m "feat(multi-agent): add generate_portfolio_report, a self-loading report tool"
```

---

### Task 4: Register the tool (`TOOLS`, `READ_ONLY_TOOLS`, `docs/TOOLS.md`)

**Files:**
- Modify: `app/agent/tools/__init__.py`
- Modify: `docs/TOOLS.md`

**Interfaces:**
- Consumes: `generate_portfolio_report_tool` (Task 3).

- [ ] **Step 1: Add the import and registrations**

In `app/agent/tools/__init__.py`, add the import next to the other finance/concentration imports:

```python
from app.agent.tools.portfolio_report import generate_portfolio_report_tool
```

Add to the `TOOLS` list, right after `client_portfolio_tool`:

```python
    client_portfolio_tool,
    generate_portfolio_report_tool,
```

Add to `_BASE_READ_ONLY_TOOLS`, right after `"client_portfolio"`:

```python
    "client_portfolio",
    "generate_portfolio_report",
```

Add to `__all__`, right after `"client_portfolio_tool"`:

```python
    "client_portfolio_tool",
    "generate_portfolio_report_tool",
```

- [ ] **Step 2: Run the backend suite to confirm nothing broke**

Run: `cd market-intelligence-agent && uv run pytest tests/ -q`
Expected: all passing (the integrity check in `__init__.py` — `READ_ONLY_TOOLS` names must all exist in `TOOLS` — fails loudly at import time if this step is wrong, so a passing collection already proves the wiring is consistent)

- [ ] **Step 3: Update `docs/TOOLS.md`**

Add a row to the summary table (after the `client_portfolio` row, so it becomes row 23):

```markdown
| 23 | `generate_portfolio_report` | read-only | Native (`portfolio_report.py`) — loads data via `read_query` + `yfinance_get_ticker_info` | client_name (full or partial) | Resolves the named client, loads holdings + live prices itself, and returns a self-contained downloadable HTML brief (positions table + an inline SVG pie chart of position weights) plus a `reports/`-prefixed suggested filename. Never writes anything itself -- `write_file` is the actual write path. | An advisor-facing deliverable for a client meeting. The chart needs real arc-angle math, the same reason `concentration_screen`/`client_portfolio` compute their own numbers instead of trusting the LLM to: an LLM hand-writing SVG path data is exactly as unreliable as one summing a portfolio itself. |
```

Update the `READ_ONLY_TOOLS` line to add `"generate_portfolio_report"` after `"client_portfolio"`.

Add a "Per-tool details" sub-section after the `client_portfolio` one:

```markdown
### 23. `generate_portfolio_report`
- **File:** `app/agent/tools/portfolio_report.py` (reuses `client_portfolio.py`'s `load_client_portfolio` for data loading, `concentration.py`'s `parse_tool_payload`/`price_from_quote` for MCP wiring)
- **What:** The LLM passes only `client_name`. The tool resolves the client, loads holdings + live prices the same way `client_portfolio` does, and renders a self-contained HTML report: a positions table, a concentration note for any position over 30% of the portfolio, and an inline SVG pie chart of position weights (pure Python arc-angle math, no external chart library or image). Returns `{client_name, suggested_path, html}` (`suggested_path` always under `reports/`) or `{error}` on zero/multiple client matches. Read-only; in `READ_ONLY_TOOLS`.
- **Why:** Gives the advisor a real, downloadable deliverable (a client-meeting brief) instead of only chat text. The chart is built by code for the same reason `concentration_screen`/`client_portfolio` compute their own figures: arc-angle math hand-written by an LLM is the same failure class as arithmetic hand-written by an LLM.
```

- [ ] **Step 4: Commit**

```bash
cd market-intelligence-agent
git add app/agent/tools/__init__.py docs/TOOLS.md
git commit -m "feat(tools): register generate_portfolio_report in TOOLS/READ_ONLY_TOOLS"
```

---

### Task 5: Wire `portfolio_agent` (tool list, HITL on `write_file`, prompt)

**Files:**
- Modify: `app/agent/multi_agent/portfolio_agent.py`
- Modify: `app/agent/prompts/specialist_agent_prompts.py`
- Modify: `tests/unit/test_multi_agent_portfolio_agent.py`

**Interfaces:**
- Consumes: `generate_portfolio_report_tool` (Task 3/4), `fs_write_file_tool` (existing, `app/agent/tools/__init__.py`), `HumanInTheLoopMiddleware` (existing import, `langchain.agents.middleware`).

- [ ] **Step 1: Update the existing tests (RED)**

In `tests/unit/test_multi_agent_portfolio_agent.py`, replace `test_tools` and `test_create_agent_call`:

```python
def test_tools():
    names = {t.name.rsplit("___", 1)[-1] for t in mod._TOOLS}
    assert names == {"read_query", "list_tables", "describe_table", "yfinance_get_ticker_info",
                     "portfolio_metrics", "pct_change", "concentration_screen", "client_portfolio",
                     "generate_portfolio_report", "write_file"}


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
    assert set(hitl.interrupt_on) == {"write_file"}
    assert kw["middleware"][-1] is market_desk_display
    assert len(kw["middleware"]) == len(base) + 2
```

(`HumanInTheLoopMiddleware` is already imported at the top of this test file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_multi_agent_portfolio_agent.py -v`
Expected: FAIL — `test_tools` missing `generate_portfolio_report`/`write_file`; `test_create_agent_call` finds no `HumanInTheLoopMiddleware` in `kw["middleware"]`

- [ ] **Step 3: Update `portfolio_agent.py`**

Replace the full file:

```python
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.multi_agent.display import market_desk_display
from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT
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


def build_portfolio_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=PORTFOLIO_SYSTEM_PROMPT,
        middleware=[
            *base_middleware(),
            HumanInTheLoopMiddleware(interrupt_on={"write_file": True}),
            market_desk_display,
        ],
        name="portfolio_agent",
    )
```

- [ ] **Step 4: Update `PORTFOLIO_SYSTEM_PROMPT`**

In `app/agent/prompts/specialist_agent_prompts.py`, add tool #9 to the `PORTFOLIO_SYSTEM_PROMPT` tool list (after the `client_portfolio` entry, item 8):

```
9. `write_file` — save the report `generate_portfolio_report` built (args: `path: str`, `content: str`). This is a side-effect tool and requires human approval — the platform itself pauses and shows the user an approve/edit/reject card before it runs. Just call the tool directly with the path and content; do not ask the user to confirm in your reply first — that only adds an extra back-and-forth before the real approval card even appears.
```

Add a new instruction bullet under `🧠 INSTRUCTIONS`, after the concentration recipe bullet:

```
- Report recipe: for any "save/export/generate a brief or report" request about a named client, call `generate_portfolio_report` (it loads its own data -- no `client_portfolio` call needed first) then `write_file` with its `html` and `suggested_path` values exactly as returned -- do not edit, summarize, or reformat the HTML.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_multi_agent_portfolio_agent.py -v`
Expected: all passing

- [ ] **Step 6: Run the full backend suite**

Run: `cd market-intelligence-agent && uv run pytest tests/ -q`
Expected: all passing

- [ ] **Step 7: Commit**

```bash
cd market-intelligence-agent
git add app/agent/multi_agent/portfolio_agent.py app/agent/prompts/specialist_agent_prompts.py tests/unit/test_multi_agent_portfolio_agent.py
git commit -m "feat(multi-agent): give portfolio_agent generate_portfolio_report + write_file"
```

---

### Task 6: `GET /workspace/files/{filename}` download route

**Files:**
- Modify: `app/api/routers/workspace.py`
- Test: `tests/unit/test_workspace_files.py` (new)

**Interfaces:**
- Produces: `GET /workspace/files/{filename}` — 200 with the file's bytes and `Content-Disposition: attachment` when found under `WORKSPACE_ROOT/reports/`, 404 otherwise. `filename` is sanitized with `Path(filename).name` exactly like the existing screenshots route.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_workspace_files.py`:

```python
"""GET /workspace/files/{filename} -- serves reports generate_portfolio_report
+ write_file save into WORKSPACE_ROOT/reports, so the chat's download card
(ReportFileCard.tsx) has something to link to."""
from fastapi.testclient import TestClient

from app.core.config import settings


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", tmp_path)
    from fastapi import FastAPI

    from app.api.routers.workspace import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_serves_a_report_and_forces_download(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    (reports / "margaret-collins-portfolio-brief-2026-09-29.html").write_text("<html>brief</html>")

    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/files/margaret-collins-portfolio-brief-2026-09-29.html")

    assert res.status_code == 200
    assert res.text == "<html>brief</html>"
    assert "attachment" in res.headers["content-disposition"]


def test_missing_file_returns_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/files/does-not-exist.html")
    assert res.status_code == 404


def test_path_traversal_is_blocked(tmp_path, monkeypatch):
    secret = tmp_path / "secret.txt"
    secret.write_text("do not leak me")
    (tmp_path / "reports").mkdir(parents=True)

    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/files/..%2Fsecret.txt")
    assert res.status_code in (403, 404)
    assert b"do not leak me" not in res.content


def test_a_file_outside_reports_is_not_served(tmp_path, monkeypatch):
    # Only WORKSPACE_ROOT/reports is in scope -- a root-level file (like an
    # upload, or a plain filesystem_agent write) must not be reachable here.
    (tmp_path / "reports").mkdir(parents=True)
    (tmp_path / "notes.txt").write_text("not a report")

    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/files/notes.txt")
    assert res.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_workspace_files.py -v`
Expected: FAIL with 404 on all routes (route doesn't exist yet — FastAPI returns 404 for an unmatched path, so `test_missing_file_returns_404` and `test_path_traversal_is_blocked` may already superficially pass; `test_serves_a_report_and_forces_download` and `test_a_file_outside_reports_is_not_served` fail)

- [ ] **Step 3: Add the route**

In `app/api/routers/workspace.py`, add after the existing `get_screenshot` route:

```python
@router.get("/files/{filename}")
async def get_report_file(filename: str) -> FileResponse:
    # Path(...).name strips any directory components (including "..") the
    # same way the screenshots route above sanitizes its filename.
    safe_name = Path(filename).name
    candidate = Path(settings.WORKSPACE_ROOT) / "reports" / safe_name
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # filename= forces Content-Disposition: attachment (a real download,
    # not the browser rendering the file inline).
    return FileResponse(candidate, filename=safe_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_workspace_files.py -v`
Expected: 4 passed

- [ ] **Step 5: Run the full backend suite**

Run: `cd market-intelligence-agent && uv run pytest tests/ -q`
Expected: all passing

- [ ] **Step 6: Commit**

```bash
cd market-intelligence-agent
git add app/api/routers/workspace.py tests/unit/test_workspace_files.py
git commit -m "feat(api): add GET /workspace/files/{filename} to download reports"
```

---

### Task 7: `report_file` display normalizer

**Files:**
- Modify: `app/agent/multi_agent/display.py`
- Modify: `tests/unit/test_display_normalizers.py`

**Interfaces:**
- Produces: `normalize_report_file(text: str, args: dict) -> list[dict]`, registered as `DISPLAY_NORMALIZERS["write_file"]`. Returns `[{"type": "report_file", "filename": str, "url": str}]` when `args["path"]` starts with `"reports/"`, else `[]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_display_normalizers.py`:

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

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_display_normalizers.py -v`
Expected: FAIL with `KeyError: 'write_file'` (not yet registered)

- [ ] **Step 3: Add the normalizer**

In `app/agent/multi_agent/display.py`, add after `normalize_screenshot` (before the final `DISPLAY_NORMALIZERS["search_knowledge_base"] = ...` line, alongside it):

```python
def normalize_report_file(text: str, args: dict) -> list[dict]:
    path = args.get("path", "")
    if not path.startswith("reports/"):
        return []  # a plain filesystem_agent write (e.g. notes.txt) -- not a report, no card
    filename = Path(path).name
    return [{"type": "report_file", "filename": filename, "url": f"/workspace/files/{filename}"}]


DISPLAY_NORMALIZERS["write_file"] = normalize_report_file
```

(`Path` is already imported at the top of `display.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd market-intelligence-agent && uv run pytest tests/unit/test_display_normalizers.py -v`
Expected: all passing

- [ ] **Step 5: Run the full backend suite**

Run: `cd market-intelligence-agent && uv run pytest tests/ -q`
Expected: all passing

- [ ] **Step 6: Commit**

```bash
cd market-intelligence-agent
git add app/agent/multi_agent/display.py tests/unit/test_display_normalizers.py
git commit -m "feat(multi-agent): normalize write_file into a report_file display"
```

---

### Task 8: Frontend types + payload validation

**Files:**
- Modify: `frontend/src/desk/displays/types.ts`
- Modify: `frontend/src/desk/displays/parseDisplay.ts`
- Modify: `frontend/src/desk/displays/parseDisplay.test.ts`

**Interfaces:**
- Produces: `DisplayPayload` gains `{ type: "report_file"; filename: string; url: string }`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/desk/displays/parseDisplay.test.ts`, inside the `describe` block:

```ts
  it("validates a report_file display", () => {
    const reportFile = { type: "report_file", filename: "brief.html", url: "/workspace/files/brief.html" };
    const envelope = parseDisplay(JSON.stringify({ summary: "text", displays: [reportFile] }));
    expect(envelope?.displays).toEqual([reportFile]);
  });

  it("drops a report_file entry missing url", () => {
    const envelope = parseDisplay(JSON.stringify({
      summary: "text",
      displays: [portfolioTable, { type: "report_file", filename: "brief.html" }],
    }));
    expect(envelope?.displays).toEqual([portfolioTable]);
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd market-intelligence-agent/frontend && npx vitest run src/desk/displays/parseDisplay.test.ts`
Expected: FAIL — `report_file` isn't a recognized type, so `isValidDisplay` rejects it via the `VALIDATORS[...]` lookup returning `undefined`, and TypeScript itself will flag the literal as not assignable to `DisplayPayload` once `types.ts` is updated in the next step (run the test first to see the runtime failure)

- [ ] **Step 3: Add the type and validator**

In `frontend/src/desk/displays/types.ts`, find this exact tail of the `DisplayPayload` union:

```ts
  | { type: "rag_sources"; sources: { filename: string; page: string; excerpt: string }[] };
```

Replace it with:

```ts
  | { type: "rag_sources"; sources: { filename: string; page: string; excerpt: string }[] }
  | { type: "report_file"; filename: string; url: string };
```

In `frontend/src/desk/displays/parseDisplay.ts`, add to the `VALIDATORS` map (after `rag_sources`):

```ts
  report_file: (d) => typeof d.filename === "string" && typeof d.url === "string",
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd market-intelligence-agent/frontend && npx vitest run src/desk/displays/parseDisplay.test.ts`
Expected: all passing

- [ ] **Step 5: Commit**

```bash
cd market-intelligence-agent
git add frontend/src/desk/displays/types.ts frontend/src/desk/displays/parseDisplay.ts frontend/src/desk/displays/parseDisplay.test.ts
git commit -m "feat(frontend): add report_file to the display payload contract"
```

---

### Task 9: `ReportFileCard` component

**Files:**
- Create: `frontend/src/desk/displays/ReportFileCard.tsx`
- Create: `frontend/src/desk/displays/ReportFileCard.test.tsx`

**Interfaces:**
- Consumes: `DisplayPayload` (Task 8).
- Produces: `ReportFileCard({ display }: { display: Extract<DisplayPayload, { type: "report_file" }> })`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/desk/displays/ReportFileCard.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReportFileCard } from "./ReportFileCard";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "report_file" }> = {
  type: "report_file",
  filename: "margaret-collins-portfolio-brief-2026-09-29.html",
  url: "/workspace/files/margaret-collins-portfolio-brief-2026-09-29.html",
};

describe("ReportFileCard", () => {
  it("shows the filename", () => {
    render(<ReportFileCard display={display} />);
    expect(screen.getByText(display.filename)).toBeInTheDocument();
  });

  it("links the download button at the report's url", () => {
    render(<ReportFileCard display={display} />);
    const link = screen.getByRole("link", { name: /download/i });
    expect(link).toHaveAttribute("href", display.url);
    expect(link).toHaveAttribute("download");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd market-intelligence-agent/frontend && npx vitest run src/desk/displays/ReportFileCard.test.tsx`
Expected: FAIL — `Failed to resolve import "./ReportFileCard"`

- [ ] **Step 3: Write the component**

Create `frontend/src/desk/displays/ReportFileCard.tsx`:

```tsx
import type { DisplayPayload } from "./types";

export function ReportFileCard({ display }: { display: Extract<DisplayPayload, { type: "report_file" }> }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-terminal-border bg-terminal-panel p-3">
      <div className="flex min-w-0 items-center gap-2.5">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" className="shrink-0 text-terminal-accent">
          <path d="M6 2h9l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Z" stroke="currentColor" strokeWidth="1.5" />
          <path d="M14 2v5h5" stroke="currentColor" strokeWidth="1.5" />
        </svg>
        <span className="truncate font-mono text-xs text-terminal-text">{display.filename}</span>
      </div>
      <a
        href={display.url}
        download
        className="shrink-0 rounded-lg border border-terminal-accent/40 px-3 py-1.5 font-mono text-xs text-terminal-accent hover:bg-terminal-accent/10"
      >
        Download
      </a>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd market-intelligence-agent/frontend && npx vitest run src/desk/displays/ReportFileCard.test.tsx`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd market-intelligence-agent
git add frontend/src/desk/displays/ReportFileCard.tsx frontend/src/desk/displays/ReportFileCard.test.tsx
git commit -m "feat(frontend): add ReportFileCard, a download button for saved reports"
```

---

### Task 10: Wire `write_file` into `useToolDisplay`

**Files:**
- Modify: `frontend/src/desk/displays/useToolDisplay.tsx`
- Modify: `frontend/src/desk/displays/useToolDisplay.test.tsx`

**Interfaces:**
- Consumes: `ReportFileCard` (Task 9).

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

Add a new test after the existing "renders the matching component" test:

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

Change the file's existing top-of-file import line from:

```tsx
import { render } from "@testing-library/react";
```

to:

```tsx
import { render, screen } from "@testing-library/react";
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd market-intelligence-agent/frontend && npx vitest run src/desk/displays/useToolDisplay.test.tsx`
Expected: FAIL — `write_file` missing from the registered tool list; second new test fails because `registrations["write_file"]` is `undefined`

- [ ] **Step 3: Wire it up**

In `frontend/src/desk/displays/useToolDisplay.tsx`:

Add the import:

```tsx
import { ReportFileCard } from "./ReportFileCard";
```

Add a case to `Rendered`'s switch (after `rag_sources`):

```tsx
          case "report_file": return <ReportFileCard key={i} display={d} />;
```

Add `"write_file"` to `DISPLAYABLE_TOOLS`:

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
```

Update the comment above `useToolDisplay` (it currently says `write_file` is left to CopilotKit's default card — no longer true):

```tsx
// One named registration per tool — leaves every other tool call (read_query,
// save_memory, browser_navigate, browser_snapshot, send_email, ...) to
// CopilotKit's own default card, completely untouched. write_file is
// registered too, but its normalizer (display.py) only produces a display
// for a path under "reports/" -- a plain filesystem_agent write still falls
// through to the default card via the same "no displays" path every other
// unregistered tool uses.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd market-intelligence-agent/frontend && npx vitest run src/desk/displays/useToolDisplay.test.tsx`
Expected: all passing

- [ ] **Step 5: Run the full frontend suite**

Run: `cd market-intelligence-agent/frontend && npx vitest run`
Expected: all passing

- [ ] **Step 6: Commit**

```bash
cd market-intelligence-agent
git add frontend/src/desk/displays/useToolDisplay.tsx frontend/src/desk/displays/useToolDisplay.test.tsx
git commit -m "feat(frontend): render ReportFileCard for write_file report results"
```

---

### Task 11: Full-suite verification and live QA

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite**

Run: `cd market-intelligence-agent && uv run pytest tests/ -q`
Expected: all passing, no warnings beyond the pre-existing deprecation notices already present before this feature

- [ ] **Step 2: Run the full frontend suite**

Run: `cd market-intelligence-agent/frontend && npx vitest run`
Expected: all passing

- [ ] **Step 3: Restart the backend so the new tool/route are live**

Kill the running `uvicorn` process and relaunch it (the project's `--reload` flag does not reliably reload every change, per this session's established pattern — always verify with a fresh `GET /health` before live-testing):

```bash
cd market-intelligence-agent
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload
```

- [ ] **Step 4: Live-test in the browser**

Against the running Market Desk chat (`npm run dev` in `frontend/`), on a fresh session, send: `Generate a portfolio report for Margaret Collins and save it`. Confirm:
- The `write_file` HITL approval card appears directly (no prose pre-confirmation — this specialist gets the same fix `filesystem_agent` already has, since Task 5 copied that prompt wording).
- After approving, a `ReportFileCard` appears in the chat with the correct filename and a working "Download" button.
- Clicking "Download" actually downloads the `.html` file; opening it shows the positions table and the pie chart rendering correctly, with the right client name and numbers matching what an equivalent `client_portfolio` call would show.
- Ask a plain `Write a file called notes.txt with 'test'` in the same session and confirm it still gets the plain-text default card, not a `ReportFileCard` — the `reports/` scoping in Task 7 must hold.

- [ ] **Step 5: Report findings**

If anything diverges from the expected behavior above, treat it as a bug: diagnose against the actual checkpoint state (the technique used throughout this session — `AsyncSqliteSaver.from_conn_string` against `data/checkpoints.db`) before guessing, fix with its own RED/GREEN cycle, and re-verify live before considering this plan done.
