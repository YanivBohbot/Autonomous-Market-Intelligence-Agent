from datetime import date
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.multi_agent import portfolio_agent as portfolio_agent_mod
from app.agent.multi_agent.portfolio_agent import build_portfolio_agent, portfolio_agent_node


def _state():
    return {"question": "Which clients hold NVDA?", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}


def test_portfolio_agent_has_every_tool_a_portfolio_computation_needs():
    names = {t.name.rsplit("___", 1)[-1] for t in portfolio_agent_mod._PORTFOLIO_TOOLS}
    assert names == {"read_query", "list_tables", "describe_table", "yfinance_get_ticker_info", "portfolio_metrics", "pct_change"}


def test_routes_to_approval_when_tool_calls_present():
    ai_msg = AIMessage(content="", tool_calls=[{"id": "1", "name": "read_query", "args": {"query": "SELECT 1"}}])
    with patch.object(portfolio_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = portfolio_agent_node(_state())
    assert result.goto == "approval"
    assert result.update["messages"] == [ai_msg]


def test_routes_to_supervisor_parent_when_no_tool_calls():
    ai_msg = AIMessage(content="Nine clients hold NVDA.")
    with patch.object(portfolio_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = portfolio_agent_node(_state())
    assert result.goto == "supervisor"
    assert result.graph == Command.PARENT


def test_system_prompt_includes_todays_date():
    with patch.object(portfolio_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = AIMessage(content="answer")
        portfolio_agent_node(_state())
    system_prompt = mock.invoke.call_args[0][0][0].content
    assert f"Today's date is {date.today().isoformat()}" in system_prompt
    assert "portfolio_metrics" in system_prompt


def test_build_portfolio_agent_compiles_with_expected_nodes():
    assert set(build_portfolio_agent().get_graph().nodes) >= {"agent", "approval", "tools"}


def test_all_portfolio_tools_bypass_interrupt():
    from app.agent.graph import approval_node

    pending = AIMessage(content="", tool_calls=[
        {"id": str(i), "name": n, "args": {}}
        for i, n in enumerate(["read_query", "list_tables", "describe_table", "yfinance_get_ticker_info", "portfolio_metrics", "pct_change"])
    ])
    with patch("app.agent.graph.interrupt") as mock_interrupt:
        result = approval_node({"messages": [pending], "question": "q", "documents": []})
    mock_interrupt.assert_not_called()
    assert result == {}
