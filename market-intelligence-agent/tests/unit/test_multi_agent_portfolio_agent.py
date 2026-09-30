from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent import portfolio_agent as mod
from app.agent.multi_agent.common import base_middleware
from app.agent.multi_agent.display import market_desk_display


def _kwargs():
    with patch.object(mod, "create_agent") as ca:
        mod.build_portfolio_agent()
    return ca.call_args.kwargs


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


def test_builds_a_real_agent():
    assert "model" in mod.build_portfolio_agent().get_graph().nodes


def test_keeps_email_addresses_it_needs_to_work():
    kw = _kwargs()
    assert not any(getattr(m, "pii_type", None) == "email" for m in kw["middleware"])


def test_portfolio_recipe_defers_to_report_recipe_for_save_or_export_requests():
    """Regression: live QA showed "Generate a portfolio report for Margaret
    Collins and save it" made the LLM call client_portfolio (Portfolio
    recipe) instead of generate_portfolio_report + write_file (Report
    recipe), then falsely claim in prose that it had generated the report.
    Both recipes matched on "portfolio"/"client" with nothing telling the
    model which one wins -- the Portfolio recipe bullet must explicitly
    exclude generate/save/export/report requests."""
    from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT

    portfolio_bullet = PORTFOLIO_SYSTEM_PROMPT.split("Portfolio recipe:")[1].split("\n-")[0]
    assert "report recipe" in portfolio_bullet.lower()


def test_report_recipe_has_a_worked_example_for_the_combined_generate_and_save_phrasing():
    """Regression: the Portfolio-recipe exclusion clause alone did not change
    the live LLM's tool choice -- live re-test of "Generate a portfolio
    report for Margaret Collins and save it" still called only
    client_portfolio and falsely claimed a report was generated. A concrete
    worked example is the pattern already proven to change routing behavior
    elsewhere in this file (SUPERVISOR_ROUTING_PROMPT's RAG/Tesla and
    save-report examples); apply the same fix here."""
    from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT

    report_section = PORTFOLIO_SYSTEM_PROMPT.split("Report recipe:")[1]
    example = report_section.split("Example:", 1)[1]
    assert "generate_portfolio_report" in example
    assert "client_portfolio" in example
