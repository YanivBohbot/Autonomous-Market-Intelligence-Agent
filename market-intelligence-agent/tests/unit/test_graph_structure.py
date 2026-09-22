from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import build_agent_app


def _build():
    return build_agent_app(InMemorySaver())


def test_graph_compiles():
    _build()


def test_graph_has_exactly_the_expected_nodes():
    nodes = set(_build().get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"record_question", "generate", "approval", "tools"}


def test_graph_no_longer_has_rag_pipeline_nodes():
    nodes = _build().get_graph().nodes
    for removed in ("rag", "grader", "web_search"):
        assert removed not in nodes
