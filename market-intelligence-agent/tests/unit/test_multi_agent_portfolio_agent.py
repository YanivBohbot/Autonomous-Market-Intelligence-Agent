from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent import portfolio_agent as mod
from app.agent.multi_agent.common import base_middleware


def _kwargs():
    with patch.object(mod, "create_agent") as ca:
        mod.build_portfolio_agent()
    return ca.call_args.kwargs


def test_tools():
    names = {t.name.rsplit("___", 1)[-1] for t in mod._TOOLS}
    assert names == {"read_query", "list_tables", "describe_table", "yfinance_get_ticker_info",
                     "portfolio_metrics", "pct_change", "concentration_screen"}


def test_create_agent_call():
    kw = _kwargs()
    from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT
    assert kw["system_prompt"] == PORTFOLIO_SYSTEM_PROMPT
    assert kw["tools"] == mod._TOOLS
    assert kw["name"] == "portfolio_agent"
    assert [type(m) for m in kw["middleware"]] == [type(m) for m in base_middleware()]
    assert not any(isinstance(m, HumanInTheLoopMiddleware) for m in kw["middleware"])


def test_builds_a_real_agent():
    assert "model" in mod.build_portfolio_agent().get_graph().nodes
