from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import build_multi_agent_app


def _build():
    return build_multi_agent_app(InMemorySaver())


def test_graph_compiles():
    _build()


def test_graph_has_supervisor_and_specialist_nodes():
    nodes = _build().get_graph().nodes
    for name in (
        "record_question",
        "supervisor",
        "rag_agent",
        "finance_agent",
        "portfolio_agent",
        "memory_agent",
        "filesystem_agent",
        "browser_agent",
        "email_agent",
    ):
        assert name in nodes


def test_graph_does_not_use_static_interrupt_before():
    agent_app = _build()
    interrupts = getattr(agent_app, "interrupt_before_nodes", None) or getattr(agent_app, "_interrupt_before", None) or []
    assert "tools" not in (interrupts or [])


def test_create_agent_specialists_return_to_supervisor():
    from app.agent.multi_agent.graph import SPECIALISTS
    edges = {(e.source, e.target) for e in _build().get_graph().edges}
    for name in SPECIALISTS:
        assert (name, "supervisor") in edges
