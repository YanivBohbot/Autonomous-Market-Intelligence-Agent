"""generate_portfolio_narrative -- a single, lightweight, direct LLM call
(same pattern as the supervisor's own `_router`) that writes a grounded
financial-reasoning paragraph from numbers the caller already computed.
The LLM never recomputes anything -- it only reasons over totals/positions/
sector_allocation/concentration already in the report dict."""

import asyncio
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from app.agent.tools import portfolio_narrative as narrative_mod
from app.agent.tools.portfolio_narrative import generate_portfolio_narrative

_REPORT = {
    "name": "Jane Doe",
    "risk_profile": "conservative",
    "totals": {"market_value": 100000.0, "cost_basis": 90000.0, "unrealized_pnl": 10000.0, "unrealized_pnl_pct": 11.1},
    "positions": [
        {"ticker": "NVDA", "weight_pct": 65.0, "sector": "Technology", "unrealized_pnl_pct": 40.0},
        {"ticker": "BND", "weight_pct": 35.0, "sector": "ETF", "unrealized_pnl_pct": 2.0},
    ],
    "sector_allocation": {"Technology": 65.0, "ETF": 35.0},
    "concentration": {"threshold_pct": 30.0, "breach_count": 1, "breaches": [{"label": "Jane Doe", "ticker": "NVDA", "weight_pct": 65.0, "market_value": 65000.0}]},
    "unpriced_tickers": [],
}


def test_generate_portfolio_narrative_grounds_the_prompt_in_computed_numbers():
    with patch.object(narrative_mod, "_llm") as mock:
        mock.ainvoke = AsyncMock(return_value=AIMessage(content="Jane Doe's portfolio is concentrated in NVDA..."))
        result = asyncio.run(generate_portfolio_narrative(_REPORT))

    prompt_messages = mock.ainvoke.call_args[0][0]
    prompt_text = " ".join(m.content for m in prompt_messages)
    assert "100000" in prompt_text or "100,000" in prompt_text
    assert "NVDA" in prompt_text
    assert "65.0" in prompt_text or "65%" in prompt_text
    assert "conservative" in prompt_text
    assert result == "Jane Doe's portfolio is concentrated in NVDA..."


def test_generate_portfolio_narrative_skips_the_llm_call_with_no_priced_positions():
    empty_report = {**_REPORT, "totals": None, "positions": [], "sector_allocation": None, "concentration": None}
    with patch.object(narrative_mod, "_llm") as mock:
        result = asyncio.run(generate_portfolio_narrative(empty_report))

    mock.ainvoke.assert_not_called()
    assert "no priced position" in result.lower()
