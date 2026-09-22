from langgraph.checkpoint.memory import InMemorySaver

from app.voice.graph import build_voice_agent_app


def test_voice_graph_compiles():
    build_voice_agent_app(InMemorySaver())


def test_voice_graph_has_no_init_node():
    nodes = set(build_voice_agent_app(InMemorySaver()).get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"generate", "approval", "tools"}
