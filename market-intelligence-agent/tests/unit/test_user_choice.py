import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from app.agent.middleware import OnlyOnAgUi
from app.agent.orchestration.state import AG_UI_RUN_METADATA
from app.agent.tools import is_read_only
from app.agent.tools.user_choice import ask_user_choice_tool, build_choice_payload


def test_payload_shape_and_ids():
    p = build_choice_payload("Which client?", ["Ann Lee", "Ann Moss"], multi=False, allow_other=False)
    assert p == {"type": "user_choice", "question": "Which client?", "multi": False, "allow_other": False,
                 "options": [{"id": "0", "label": "Ann Lee"}, {"id": "1", "label": "Ann Moss"}]}


def test_payload_needs_two_options():
    with pytest.raises(ValueError):
        build_choice_payload("Q", ["only"], multi=False, allow_other=False)


def test_tool_interrupts_then_returns_resume_value():
    g = StateGraph(MessagesState)
    g.add_node("tools", ToolNode([ask_user_choice_tool]))
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    app = g.compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "c1"}, "metadata": dict(AG_UI_RUN_METADATA)}
    call = AIMessage(content="", tool_calls=[{"id": "t1", "name": "ask_user_choice",
                                              "args": {"question": "Which?", "options": ["A", "B"]}}])
    first = app.invoke({"messages": [call]}, cfg)
    assert first["__interrupt__"][0].value["type"] == "user_choice"
    done = app.invoke(Command(resume={"selected": ["1"], "other": None}), cfg)
    assert json.loads(done["messages"][-1].content) == {"selected": ["B"], "other": None}


def test_not_read_only_so_tool_retry_never_wraps_the_interrupt():
    assert not is_read_only("ask_user_choice")


def _request(state, names):
    tools = [SimpleNamespace(name=n) for n in names]
    return SimpleNamespace(state=state, tools=tools, override=lambda **kw: SimpleNamespace(state=state, **kw))


def test_gate_removes_choice_tool_without_ag_ui():
    mw = OnlyOnAgUi({"ask_user_choice"})
    seen = mw.wrap_model_call(_request({}, ["read_query", "ask_user_choice"]), lambda r: r)
    assert [t.name for t in seen.tools] == ["read_query"]


def test_gate_keeps_choice_tool_on_ag_ui():
    mw = OnlyOnAgUi({"ask_user_choice"})
    seen = mw.wrap_model_call(_request({"ag-ui": {"context": []}}, ["read_query", "ask_user_choice"]), lambda r: r)
    assert [t.name for t in seen.tools] == ["read_query", "ask_user_choice"]


def _tool_graph():
    g = StateGraph(MessagesState)
    g.add_node("tools", ToolNode([ask_user_choice_tool]))
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    return g.compile(checkpointer=InMemorySaver())


def _call():
    return AIMessage(content="", tool_calls=[{"id": "t1", "name": "ask_user_choice",
                                              "args": {"question": "Which?", "options": ["A", "B"]}}])


def test_tool_refuses_to_interrupt_outside_ag_ui_runs():
    # Review Critical 1: a stale tool call must never pause voice / /stream.
    out = _tool_graph().invoke({"messages": [_call()]}, {"configurable": {"thread_id": "c2"}})
    assert "__interrupt__" not in out
    assert "not available" in out["messages"][-1].content


def test_declined_choice_is_reported_as_cancelled():
    app = _tool_graph()
    cfg = {"configurable": {"thread_id": "c3"}, "metadata": dict(AG_UI_RUN_METADATA)}
    app.invoke({"messages": [_call()]}, cfg)
    done = app.invoke(Command(resume={"selected": [], "other": None, "cancelled": True}), cfg)
    assert json.loads(done["messages"][-1].content) == {"selected": [], "other": None, "cancelled": True}


def test_prompts_explain_a_declined_choice():
    from app.agent.prompts.agents_specialist_prompts import EMAIL_SYSTEM_PROMPT, FINANCE_SYSTEM_PROMPT, PORTFOLIO_SYSTEM_PROMPT
    for prompt in (EMAIL_SYSTEM_PROMPT, FINANCE_SYSTEM_PROMPT, PORTFOLIO_SYSTEM_PROMPT):
        assert '"cancelled": true' in prompt
