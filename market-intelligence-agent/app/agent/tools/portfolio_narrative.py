"""`generate_portfolio_narrative` -- a single, direct LLM call (same
lightweight pattern: no tool-calling loop, no agent graph) that writes a grounded financial-
reasoning paragraph for the Reports dashboard.

The LLM is given the report's already-computed totals/positions/
sector_allocation/concentration as plain text in the prompt and told to
reason over them -- it never recomputes a number itself, same philosophy
as every other numeric surface in this codebase (finance_calc.py's own
docstring: "LLMs make arithmetic mistakes... every value must come from
these pure functions")."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings

_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0.3)

_SYSTEM_PROMPT = (
    "You are a financial advisor's assistant writing a short analysis for a "
    "client portfolio dashboard. You are given numbers that have already "
    "been computed exactly -- never recalculate or restate them differently "
    "than given. Write 2-3 short paragraphs of plain-English financial "
    "reasoning: how the portfolio is doing, whether its sector/position "
    "concentration fits the client's stated risk profile, and anything an "
    "advisor should flag. Do not invent holdings, prices, or facts not in "
    "the data below."
)


def _format_report_for_prompt(report: dict) -> str:
    lines = [
        f"Client: {report['name']} (risk profile: {report['risk_profile']})",
        f"Total market value: {report['totals']['market_value']}",
        f"Cost basis: {report['totals']['cost_basis']}",
        f"Unrealized P&L: {report['totals']['unrealized_pnl']} ({report['totals']['unrealized_pnl_pct']}%)",
        "Positions:",
    ]
    for p in report["positions"]:
        lines.append(f"  - {p['ticker']}: {p['weight_pct']}% of portfolio, sector {p['sector']}, P&L {p['unrealized_pnl_pct']}%")
    if report.get("sector_allocation"):
        lines.append("Sector allocation: " + ", ".join(f"{s} {w}%" for s, w in report["sector_allocation"].items()))
    concentration = report.get("concentration")
    if concentration and concentration["breaches"]:
        lines.append(
            f"Concentration breaches (> {concentration['threshold_pct']}% in one stock): "
            + ", ".join(f"{b['ticker']} ({b['weight_pct']}%)" for b in concentration["breaches"])
        )
    if report.get("unpriced_tickers"):
        lines.append("Could not be priced (excluded above): " + ", ".join(report["unpriced_tickers"]))
    return "\n".join(lines)


async def generate_portfolio_narrative(report: dict) -> str:
    if not report.get("totals"):
        return "No priced positions to analyze."
    prompt = _format_report_for_prompt(report)
    response = await _llm.ainvoke([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)])
    return response.content
