"""Smoke test that the dynamic interrupt() pattern is wired correctly.

Verifies the graph compiles WITHOUT interrupt_before, and the approval node
exists. Full end-to-end resume tests would need real LLM calls, so we just
assert structural correctness here."""
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import approval_node, build_agent_app


def _build():
    return build_agent_app(InMemorySaver())


def test_graph_has_approval_node():
    nodes = _build().get_graph().nodes
    assert "approval" in nodes


def test_graph_does_not_use_static_interrupt_before():
    # The compiled graph should not declare static interrupt_before for tools.
    # If it did, that would be the legacy pattern.
    agent_app = _build()
    interrupts = getattr(agent_app, "interrupt_before_nodes", None) or getattr(agent_app, "_interrupt_before", None) or []
    assert "tools" not in (interrupts or [])


def test_approval_node_returns_cancel_messages_on_reject():
    """When decision is 'reject', node returns ToolMessages cancelling each tool_call."""
    from langchain_core.messages import AIMessage
    from unittest.mock import patch

    pending = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "send_email", "args": {"to": "x@y.com"}}],
    )
    state = {"messages": [pending], "question": "q", "documents": []}

    # Patch interrupt() to return "reject" without actually pausing
    with patch("app.agent.graph.interrupt", return_value=["reject"]):
        result = approval_node(state)

    assert "messages" in result
    cancel = result["messages"][0]
    assert cancel.tool_call_id == "call_1"
    assert "cancelled" in cancel.content.lower()


def test_approval_node_returns_empty_on_approve():
    from langchain_core.messages import AIMessage
    from unittest.mock import patch

    pending = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "send_email", "args": {"to": "x@y.com"}}],
    )
    state = {"messages": [pending], "question": "q", "documents": []}

    with patch("app.agent.graph.interrupt", return_value=["approve"]):
        result = approval_node(state)

    assert result == {}
