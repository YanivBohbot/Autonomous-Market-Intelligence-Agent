"""Regression test for the thread-poisoning bug: a raising tool must produce
an error ToolMessage, never let the exception propagate out of ToolNode.

Root cause: LangGraph's ToolNode default `handle_tool_errors` handler
(`_default_handle_tool_errors`) only converts LangGraph's own internal
`ToolInvocationError` into a ToolMessage — any other exception (e.g. an MCP
server's ToolException, a connectivity failure) is re-raised. When that
happens mid-turn, the AIMessage with tool_calls is already checkpointed by
the preceding `generate` node, but the matching ToolMessage never gets
written. Every later turn on that thread_id then fails OpenAI's 400
"assistant message with tool_calls must be followed by tool messages" check
forever, because the graph always resumes from the poisoned checkpoint.
"""
from typing import Annotated, TypedDict

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode


@tool
def failing_tool(x: str) -> str:
    """A tool that always raises, simulating an MCP server error."""
    raise RuntimeError("simulated MCP tool failure")


def _pending_ai_message():
    return AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "failing_tool", "args": {"x": "y"}}],
    )


class _ToolsOnlyState(TypedDict):
    messages: Annotated[list, add_messages]


def _tools_only_graph(**tool_node_kwargs):
    """A minimal single-node graph so ToolNode runs inside a real Pregel
    runtime (it needs injected config the bare RunnableCallable doesn't
    provide when invoked standalone)."""
    g = StateGraph(_ToolsOnlyState)
    g.add_node("tools", ToolNode([failing_tool], **tool_node_kwargs))
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    return g.compile()


def test_default_handle_tool_errors_reraises_non_toolinvocation_exceptions():
    """Documents the LangGraph default: a genuine tool failure is NOT caught."""
    app = _tools_only_graph()
    with pytest.raises(RuntimeError, match="simulated MCP tool failure"):
        app.invoke({"messages": [_pending_ai_message()]})


def test_handle_tool_errors_true_converts_failure_to_tool_message():
    """The fix: handle_tool_errors=True always yields an error ToolMessage,
    so the checkpoint never has an AIMessage tool_call without a response."""
    app = _tools_only_graph(handle_tool_errors=True)
    result = app.invoke({"messages": [_pending_ai_message()]})

    messages = result["messages"]
    tool_msg = messages[-1]
    assert tool_msg.tool_call_id == "call_1"
    assert tool_msg.status == "error"
    assert "simulated MCP tool failure" in tool_msg.content


def test_graph_tools_node_configured_to_never_reraise():
    """Production wiring check: app/agent/graph.py's underlying ToolNode must
    not use the default error handler, or any real tool failure will poison
    the thread's checkpoint the same way. The graph's "tools" node is a thin
    async wrapper (`run_tools`) around this ToolNode — it also strips image
    content off tool results before they re-enter checkpointed state — so
    inspect the wrapped node directly rather than `workflow.nodes["tools"]`."""
    from app.agent.graph import _tool_node

    # ToolNode's own default (the callable `_default_handle_tool_errors`) is
    # truthy but still re-raises real tool exceptions — only its internal
    # ToolInvocationError is caught. Must be explicitly overridden to True
    # (or an equivalent catch-all) so every tool failure becomes a
    # ToolMessage instead of poisoning the checkpoint.
    assert _tool_node._handle_tool_errors is True
