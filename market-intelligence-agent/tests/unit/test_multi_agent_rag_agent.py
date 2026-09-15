from unittest.mock import patch
from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.multi_agent import rag_agent as rag_agent_mod
from app.agent.multi_agent.rag_agent import decide_next_step, synthesize_node, build_rag_agent


def test_decide_next_step_routes_to_synthesize_when_documents_present():
    assert decide_next_step({"documents": ["some doc"]}) == "synthesize"


def test_decide_next_step_routes_to_web_search_when_no_documents():
    assert decide_next_step({"documents": []}) == "web_search"


def test_synthesize_node_returns_command_to_parent_supervisor():
    ai_msg = AIMessage(content="Here's the answer from internal docs.")
    with patch.object(rag_agent_mod, "_llm") as mock:
        mock.invoke.return_value = ai_msg
        result = synthesize_node({"question": "q", "messages": [], "documents": ["doc1"]})
    assert result.goto == "supervisor"
    assert result.graph == Command.PARENT
    assert result.update["messages"] == [ai_msg]
    mock.bind_tools.assert_not_called()


def test_build_rag_agent_compiles_with_expected_nodes():
    graph = build_rag_agent()
    assert set(graph.get_graph().nodes) >= {"retrieve", "grade", "web_search", "synthesize"}
