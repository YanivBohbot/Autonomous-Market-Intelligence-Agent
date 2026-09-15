from unittest.mock import patch
from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.multi_agent import crm_agent as crm_agent_mod
from app.agent.multi_agent.crm_agent import crm_agent_node, build_crm_agent


def _state():
    return {"question": "how many customers?", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}


def test_routes_to_approval_when_tool_calls_present():
    ai_msg = AIMessage(content="", tool_calls=[{"id": "1", "name": "read_query", "args": {"query": "SELECT COUNT(*) FROM customers"}}])
    with patch.object(crm_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = crm_agent_node(_state())
    assert result.goto == "approval"
    assert result.update["messages"] == [ai_msg]


def test_routes_to_supervisor_parent_when_no_tool_calls():
    ai_msg = AIMessage(content="There are 42 customers.")
    with patch.object(crm_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = crm_agent_node(_state())
    assert result.goto == "supervisor"
    assert result.graph == Command.PARENT


def test_build_crm_agent_compiles_with_expected_nodes():
    graph = build_crm_agent()
    assert set(graph.get_graph().nodes) >= {"agent", "approval", "tools"}


def test_crm_specialist_bypasses_interrupt_for_read_only_tool():
    from app.agent.graph import approval_node

    pending = AIMessage(
        content="",
        tool_calls=[{"id": "1", "name": "read_query", "args": {"query": "SELECT 1"}}],
    )
    state = {"messages": [pending], "question": "q", "documents": []}
    with patch("app.agent.graph.interrupt") as mock_interrupt:
        result = approval_node(state)
    mock_interrupt.assert_not_called()
    assert result == {}
