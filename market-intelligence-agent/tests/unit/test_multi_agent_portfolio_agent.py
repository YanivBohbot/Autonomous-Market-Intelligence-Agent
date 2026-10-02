from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent import portfolio_agent as mod
from app.agent.common import base_middleware
from app.agent.multi_agent.display import market_desk_display
from app.agent.pii import SensitiveDataGuard


def _kwargs():
    with patch.object(mod, "create_agent") as ca:
        mod.build_portfolio_agent()
    return ca.call_args.kwargs


def test_tools():
    names = {t.name.rsplit("___", 1)[-1] for t in mod._TOOLS}
    assert names == {"read_query", "list_tables", "describe_table", "yfinance_get_ticker_info",
                     "portfolio_metrics", "pct_change", "concentration_screen", "client_portfolio",
                     "save_portfolio_report"}


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


def test_hitl_gate_has_no_content_argument_to_preview():
    # The user explicitly chose a plain action-confirmation card (no data
    # summary) over previewing content, since HITL fires before the tool
    # runs and there is no result yet to show. save_portfolio_report's
    # only argument is client_name -- there is nothing content-shaped in
    # the approval card by construction.
    save_tool = next(t for t in mod._TOOLS if t.name == "save_portfolio_report")
    assert set(save_tool.args) == {"client_name"}


def test_builds_a_real_agent():
    assert "model" in mod.build_portfolio_agent().get_graph().nodes


def test_keeps_email_addresses_it_needs_to_work():
    kw = _kwargs()
    assert not any(getattr(m, "pii_type", None) == "email" for m in kw["middleware"])
    guard = next(m for m in kw["middleware"] if isinstance(m, SensitiveDataGuard))
    assert guard.check_email is False


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
