"""generate_market_narrative -- same lightweight direct-ChatOpenAI pattern
as portfolio_narrative.py, grounded only in index/sector quotes the
Briefing endpoint already computed. Kept as its own file rather than
generalizing portfolio_narrative.py: each stays focused on one grounding
shape (one client's portfolio vs. the whole market)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings

_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0.3)

_SYSTEM_PROMPT = (
    "You are a financial analyst writing a short market summary for an "
    "advisor's daily briefing dashboard. You are given index and sector "
    "numbers that have already been computed exactly -- never recalculate "
    "or restate them differently than given. Write 2-3 short paragraphs "
    "covering both macro movement (overall index levels, what VIX implies "
    "about market fear/complacency) and micro movement (which sectors "
    "moved and by how much, and what that dispersion suggests). Do not "
    "invent numbers, companies, or events not in the data below."
)


def _format_market_for_prompt(market: dict) -> str:
    lines = ["Indices:"]
    for idx in market["indices"]:
        lines.append(f"  - {idx['name']}: {idx['price']} ({idx['change_pct']}%)")
    lines.append("Sectors:")
    for sec in market["sectors"]:
        lines.append(f"  - {sec['name']}: {sec['change_pct']}%")
    return "\n".join(lines)


async def generate_market_narrative(market: dict) -> str:
    if not market.get("indices") and not market.get("sectors"):
        return "Market data unavailable right now."
    prompt = _format_market_for_prompt(market)
    response = await _llm.ainvoke([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)])
    return response.content
