from unittest.mock import patch
from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.multi_agent import filesystem_agent as filesystem_agent_mod
from app.agent.multi_agent.filesystem_agent import filesystem_agent_node, build_filesystem_agent


def _state():
    return {"question": "list my workspace files", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}


def test_routes_to_approval_when_tool_calls_present():
    ai_msg = AIMessage(content="", tool_calls=[{"id": "1", "name": "write_file", "args": {"path": "x.txt", "content": "y"}}])
    with patch.object(filesystem_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = filesystem_agent_node(_state())
    assert result.goto == "approval"
    assert result.update["messages"] == [ai_msg]


def test_routes_to_supervisor_parent_when_no_tool_calls():
    ai_msg = AIMessage(content="Here are your files.")
    with patch.object(filesystem_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = filesystem_agent_node(_state())
    assert result.goto == "supervisor"
    assert result.graph == Command.PARENT


def test_build_filesystem_agent_compiles_with_expected_nodes():
    graph = build_filesystem_agent()
    assert set(graph.get_graph().nodes) >= {"agent", "approval", "tools"}


def test_write_file_triggers_interrupt_since_it_is_a_side_effect_tool():
    from app.agent.graph import approval_node

    pending = AIMessage(content="", tool_calls=[{"id": "1", "name": "write_file", "args": {"path": "x.txt", "content": "y"}}])
    state = {"messages": [pending], "question": "q", "documents": []}
    with patch("app.agent.graph.interrupt", return_value=["approve"]) as mock_interrupt:
        result = approval_node(state)
    mock_interrupt.assert_called_once()
    assert result == {}


def test_list_and_read_bypass_interrupt_since_read_only():
    from app.agent.graph import approval_node

    for tool_name in ("list_directory", "read_text_file"):
        pending = AIMessage(content="", tool_calls=[{"id": "1", "name": tool_name, "args": {}}])
        state = {"messages": [pending], "question": "q", "documents": []}
        with patch("app.agent.graph.interrupt") as mock_interrupt:
            result = approval_node(state)
        mock_interrupt.assert_not_called()
        assert result == {}
