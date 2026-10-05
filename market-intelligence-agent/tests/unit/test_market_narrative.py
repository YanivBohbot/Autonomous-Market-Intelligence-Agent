"""generate_market_narrative -- same lightweight, direct-ChatOpenAI pattern
as portfolio_narrative.py (no tool-calling loop, no agent graph), grounded
only in index/sector quotes the Briefing endpoint already computed."""

import asyncio
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from app.agent.tools import market_narrative as narrative_mod
from app.agent.tools.market_narrative import generate_market_narrative

_MARKET = {
    "indices": [
        {"name": "S&P 500", "price": 5800.0, "change_pct": 0.73},
        {"name": "VIX", "price": 14.2, "change_pct": -3.1},
    ],
    "sectors": [
        {"name": "Technology", "change_pct": 1.2},
        {"name": "Energy", "change_pct": -0.8},
    ],
}


def test_generate_market_narrative_grounds_the_prompt_in_computed_numbers():
    with patch.object(narrative_mod, "_llm") as mock:
        mock.ainvoke = AsyncMock(return_value=AIMessage(content="Markets edged higher today..."))
        result = asyncio.run(generate_market_narrative(_MARKET))

    prompt_messages = mock.ainvoke.call_args[0][0]
    prompt_text = " ".join(m.content for m in prompt_messages)
    assert "S&P 500" in prompt_text
    assert "5800" in prompt_text
    assert "0.73" in prompt_text
    assert "Technology" in prompt_text
    assert "1.2" in prompt_text
    assert result == "Markets edged higher today..."


def test_generate_market_narrative_skips_the_llm_call_with_no_data():
    empty_market = {"indices": [], "sectors": []}
    with patch.object(narrative_mod, "_llm") as mock:
        result = asyncio.run(generate_market_narrative(empty_market))

    mock.ainvoke.assert_not_called()
    assert result == "Market data unavailable right now."
