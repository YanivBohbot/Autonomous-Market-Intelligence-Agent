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

    if settings.MCP_TRANSPORT.lower() == "gateway":
        # Unlike the old generate_portfolio_report + write_file flow (which
        # delegated persistence to the S3-backed filesystem Lambda behind
        # AgentCore Gateway), this tool writes to local disk itself -- in
        # gateway mode that's the container's own ephemeral storage, not
        # S3. A silent "saved successfully" for a file that vanishes when
        # the microVM recycles is worse than an explicit error: there is no
        # S3 write path implemented yet for this tool.
        return {
            "error": "save_portfolio_report is not available in this deployment "
            "(MCP_TRANSPORT=gateway has no S3 write path for this tool yet)."
        }

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
