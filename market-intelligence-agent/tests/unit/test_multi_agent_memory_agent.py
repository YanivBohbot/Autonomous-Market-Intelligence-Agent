from unittest.mock import patch
from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.multi_agent import memory_agent as memory_agent_mod
from app.agent.multi_agent.memory_agent import memory_agent_node, build_memory_agent


def _state():
    return {"question": "remember my color is blue", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}


def test_routes_to_approval_when_tool_calls_present():
    ai_msg = AIMessage(content="", tool_calls=[{"id": "1", "name": "save_memory", "args": {"key": "color", "value": "blue"}}])
    with patch.object(memory_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = memory_agent_node(_state())
    assert result.goto == "approval"
    assert result.update["messages"] == [ai_msg]


def test_routes_to_supervisor_parent_when_no_tool_calls():
    ai_msg = AIMessage(content="I remember your color is blue.")
    with patch.object(memory_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = memory_agent_node(_state())
    assert result.goto == "supervisor"
    assert result.graph == Command.PARENT


def test_build_memory_agent_compiles_with_expected_nodes():
    graph = build_memory_agent()
    assert set(graph.get_graph().nodes) >= {"agent", "approval", "tools"}


def test_save_memory_triggers_interrupt_since_it_is_a_side_effect_tool():
    """Unlike finance/CRM (all read-only), save_memory IS gated — this is the
    first specialist in the multi-agent system with an actual side-effect
    tool, so approval_node must actually call interrupt() for it."""
    from app.agent.graph import approval_node

    pending = AIMessage(
        content="",
        tool_calls=[{"id": "1", "name": "save_memory", "args": {"key": "color", "value": "blue"}}],
    )
    state = {"messages": [pending], "question": "q", "documents": []}
    with patch("app.agent.graph.interrupt", return_value=["approve"]) as mock_interrupt:
        result = approval_node(state)
    mock_interrupt.assert_called_once()
    assert result == {}


def test_recall_and_list_memory_bypass_interrupt_since_read_only():
    from app.agent.graph import approval_node

    for tool_name in ("recall_memory", "list_memories"):
        pending = AIMessage(content="", tool_calls=[{"id": "1", "name": tool_name, "args": {}}])
        state = {"messages": [pending], "question": "q", "documents": []}
        with patch("app.agent.graph.interrupt") as mock_interrupt:
            result = approval_node(state)
        mock_interrupt.assert_not_called()
        assert result == {}
