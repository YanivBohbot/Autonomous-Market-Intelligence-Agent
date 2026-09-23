from unittest.mock import patch
from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.multi_agent import rag_agent as rag_agent_mod
from app.agent.multi_agent.rag_agent import rag_agent_node, build_rag_agent


def _state():
    return {"question": "Amazon 2024 revenue?", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}


def test_rag_agent_binds_knowledge_base_and_web_search_tools():
    names = {t.name for t in rag_agent_mod._RAG_TOOLS}
    assert names == {"search_knowledge_base", "web_search"}


def test_routes_to_approval_when_tool_calls_present():
    ai_msg = AIMessage(content="", tool_calls=[{"id": "1", "name": "search_knowledge_base", "args": {"query": "Amazon revenue"}}])
    with patch.object(rag_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = rag_agent_node(_state())
    assert result.goto == "approval"
    assert result.update["messages"] == [ai_msg]


def test_routes_to_supervisor_parent_when_no_tool_calls():
    ai_msg = AIMessage(content="Amazon 2024 revenue was $638B [Source: Amazon-2024-Annual-Report.pdf, page 24]")
    with patch.object(rag_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = rag_agent_node(_state())
    assert result.goto == "supervisor"
    assert result.graph == Command.PARENT
    assert result.update["messages"] == [ai_msg]


def test_build_rag_agent_compiles_with_expected_nodes():
    graph = build_rag_agent()
    nodes = set(graph.get_graph().nodes)
    assert nodes >= {"agent", "approval", "tools"}
    assert not nodes & {"retrieve", "grade", "synthesize"}


def test_rag_specialist_bypasses_interrupt_for_knowledge_base_and_web_search():
    from app.agent.graph import approval_node

    pending = AIMessage(
        content="",
        tool_calls=[
            {"id": "1", "name": "search_knowledge_base", "args": {"query": "q"}},
            {"id": "2", "name": "web_search", "args": {"query": "q"}},
        ],
    )
    state = {"messages": [pending], "question": "q", "documents": []}
    with patch("app.agent.graph.interrupt") as mock_interrupt:
        result = approval_node(state)
    mock_interrupt.assert_not_called()
    assert result == {}
