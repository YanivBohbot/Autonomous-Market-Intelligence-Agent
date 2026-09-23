from unittest.mock import patch
from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.multi_agent import browser_agent as browser_agent_mod
from app.agent.multi_agent.browser_agent import browser_agent_node, build_browser_agent


def _state():
    return {"question": "check example.com", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}


def test_routes_to_approval_when_tool_calls_present():
    ai_msg = AIMessage(content="", tool_calls=[{"id": "1", "name": "browser_navigate", "args": {"url": "https://example.com"}}])
    with patch.object(browser_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = browser_agent_node(_state())
    assert result.goto == "approval"
    assert result.update["messages"] == [ai_msg]


def test_routes_to_supervisor_parent_when_no_tool_calls():
    ai_msg = AIMessage(content="The page says hello.")
    with patch.object(browser_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = browser_agent_node(_state())
    assert result.goto == "supervisor"
    assert result.graph == Command.PARENT


def test_build_browser_agent_compiles_with_expected_nodes():
    graph = build_browser_agent()
    assert set(graph.get_graph().nodes) >= {"agent", "approval", "tools"}


def test_all_browser_tools_bypass_interrupt_since_read_only():
    from app.agent.graph import approval_node

    for tool_name in ("browser_navigate", "browser_snapshot", "browser_take_screenshot"):
        pending = AIMessage(content="", tool_calls=[{"id": "1", "name": tool_name, "args": {}}])
        state = {"messages": [pending], "question": "q", "documents": []}
        with patch("app.agent.graph.interrupt") as mock_interrupt:
            result = approval_node(state)
        mock_interrupt.assert_not_called()
        assert result == {}


def test_browser_agent_system_prompt_includes_todays_date():
    from datetime import date

    with patch.object(browser_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = AIMessage(content="answer")
        browser_agent_node(_state())
    system_prompt = mock.invoke.call_args[0][0][0].content
    assert f"Today's date is {date.today().isoformat()}" in system_prompt
