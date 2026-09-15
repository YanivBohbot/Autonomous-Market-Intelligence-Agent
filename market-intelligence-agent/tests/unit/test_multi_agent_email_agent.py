from unittest.mock import patch
from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.multi_agent import email_agent as email_agent_mod
from app.agent.multi_agent.email_agent import email_agent_node, build_email_agent


def _state():
    return {"question": "email a summary to x@y.com", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}


def test_routes_to_approval_when_tool_calls_present():
    ai_msg = AIMessage(content="", tool_calls=[{"id": "1", "name": "send_email", "args": {"recipient": "x@y.com", "subject": "s", "body": "b"}}])
    with patch.object(email_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = email_agent_node(_state())
    assert result.goto == "approval"
    assert result.update["messages"] == [ai_msg]


def test_routes_to_supervisor_parent_when_no_tool_calls():
    ai_msg = AIMessage(content="I need the recipient's email address first.")
    with patch.object(email_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = email_agent_node(_state())
    assert result.goto == "supervisor"
    assert result.graph == Command.PARENT


def test_build_email_agent_compiles_with_expected_nodes():
    graph = build_email_agent()
    assert set(graph.get_graph().nodes) >= {"agent", "approval", "tools"}


def test_send_email_triggers_interrupt_since_it_is_a_side_effect_tool():
    from app.agent.graph import approval_node

    pending = AIMessage(content="", tool_calls=[{"id": "1", "name": "send_email", "args": {"recipient": "x@y.com", "subject": "s", "body": "b"}}])
    state = {"messages": [pending], "question": "q", "documents": []}
    with patch("app.agent.graph.interrupt", return_value=["approve"]) as mock_interrupt:
        result = approval_node(state)
    mock_interrupt.assert_called_once()
    assert result == {}
