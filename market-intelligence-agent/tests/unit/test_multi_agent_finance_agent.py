from unittest.mock import patch
from langchain_core.messages import AIMessage
from langgraph.types import Command
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import finance_agent as finance_agent_mod
from app.agent.multi_agent.finance_agent import finance_agent_node, build_finance_agent


def _state():
    return {"question": "AAPL price?", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}


def test_routes_to_approval_when_tool_calls_present():
    ai_msg = AIMessage(content="", tool_calls=[{"id": "1", "name": "yfinance_get_ticker_info", "args": {"symbol": "AAPL"}}])
    with patch.object(finance_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = finance_agent_node(_state())
    assert result.goto == "approval"
    assert result.update["messages"] == [ai_msg]


def test_routes_to_supervisor_parent_when_no_tool_calls():
    ai_msg = AIMessage(content="AAPL is at $200")
    with patch.object(finance_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = finance_agent_node(_state())
    assert result.goto == "supervisor"
    assert result.graph == Command.PARENT
    assert result.update["messages"] == [ai_msg]


def test_build_finance_agent_compiles_with_expected_nodes():
    graph = build_finance_agent()
    assert set(graph.get_graph().nodes) >= {"agent", "approval", "tools"}


def test_finance_specialist_bypasses_interrupt_for_read_only_tool():
    from app.agent.graph import approval_node

    pending = AIMessage(
        content="",
        tool_calls=[{"id": "1", "name": "yfinance_get_ticker_info", "args": {"symbol": "AAPL"}}],
    )
    state = {"messages": [pending], "question": "q", "documents": []}
    with patch("app.agent.graph.interrupt") as mock_interrupt:
        result = approval_node(state)
    mock_interrupt.assert_not_called()
    assert result == {}


def test_finance_agent_system_prompt_includes_todays_date():
    from datetime import date

    with patch.object(finance_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = AIMessage(content="answer")
        finance_agent_node(_state())
    system_prompt = mock.invoke.call_args[0][0][0].content
    assert f"Today's date is {date.today().isoformat()}" in system_prompt
