from app.agent import tools as tools_mod
from app.agent.agents_specialist import finance_agent, portfolio_agent
from app.agent.prompts.agents_specialist_prompts import FINANCE_SYSTEM_PROMPT, PORTFOLIO_SYSTEM_PROMPT
from app.agent.prompts.orchestration_prompt import SUPERVISOR_ROUTING_PROMPT


def _names(tools):
    return {t.name for t in tools}


def test_specialists_get_the_new_tools():
    assert "compare_companies" in _names(finance_agent._TOOLS)
    assert {"simulate_portfolio_change", "watchlist_alerts"} <= _names(portfolio_agent._TOOLS)


def test_new_tools_are_registered_read_only():
    for name in ("compare_companies", "simulate_portfolio_change", "watchlist_alerts"):
        assert name in _names(tools_mod.TOOLS)
        assert tools_mod.is_read_only(name)


def test_prompts_name_the_new_tools():
    assert "compare_companies" in FINANCE_SYSTEM_PROMPT
    assert "simulate_portfolio_change" in PORTFOLIO_SYSTEM_PROMPT
    assert "watchlist_alerts" in PORTFOLIO_SYSTEM_PROMPT
    assert "never an executed trade" in PORTFOLIO_SYSTEM_PROMPT


def test_routing_prompt_knows_the_new_intents():
    assert "compare two or more companies" in SUPERVISOR_ROUTING_PROMPT
    assert "what-if" in SUPERVISOR_ROUTING_PROMPT
    assert "watchlist" in SUPERVISOR_ROUTING_PROMPT
