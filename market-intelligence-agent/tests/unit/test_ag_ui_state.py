from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.middleware import ui_context_lines
from app.agent.orchestration.state import AG_UI_KEY, ClientContextState, SupervisorState


def test_graph_state_keeps_the_ag_ui_key():
    seen = {}

    def node(state):
        seen.update(state.get(AG_UI_KEY) or {})
        return {}

    g = StateGraph(SupervisorState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    app = g.compile(checkpointer=InMemorySaver())
    app.invoke({"messages": [], AG_UI_KEY: {"context": [{"description": "Page", "value": "research"}]}},
               {"configurable": {"thread_id": "t"}})
    assert seen == {"context": [{"description": "Page", "value": "research"}]}


def test_specialist_state_declares_the_key():
    from typing import get_type_hints

    assert AG_UI_KEY in get_type_hints(ClientContextState, include_extras=True)


def test_ui_context_lines():
    state = {AG_UI_KEY: {"context": [{"description": "Selected position", "value": '{"ticker": "NVDA"}'},
                                     {"description": "", "value": ""}]}}
    assert ui_context_lines(state) == ['- Selected position: {"ticker": "NVDA"}']
    assert ui_context_lines({}) == []


def test_ui_context_lines_reads_ag_ui_pydantic_context_models():
    # ag-ui-langgraph puts ag_ui Context models (not dicts) in state["ag-ui"]["context"].
    from ag_ui.core import Context

    state = {AG_UI_KEY: {"tools": [], "context": [Context(description="Selected position", value="NVDA")]}}
    assert ui_context_lines(state) == ["- Selected position: NVDA"]


def test_non_ag_ui_run_clears_stale_ag_ui_state():
    # Review Critical 1: ag-ui-langgraph's "ag-ui" value persists in the
    # checkpoint; a later voice / /stream turn on the same thread must not
    # inherit it.
    from app.agent.orchestration.graph import load_client_context

    stale = {AG_UI_KEY: {"context": [{"description": "Selected position", "value": "NVDA"}]}}
    out = load_client_context(stale, {"configurable": {"thread_id": "desk_1"}})
    assert out[AG_UI_KEY] is None


def test_ag_ui_run_keeps_its_ag_ui_state():
    from app.agent.orchestration.graph import load_client_context
    from app.agent.orchestration.state import AG_UI_RUN_METADATA

    state = {AG_UI_KEY: {"context": []}}
    out = load_client_context(state, {"configurable": {"thread_id": "desk_1"}, "metadata": dict(AG_UI_RUN_METADATA)})
    assert AG_UI_KEY not in out


def test_market_desk_agent_marks_its_runs_as_ag_ui():
    from app.api.routers.copilot import build_market_desk_agent
    from app.agent.orchestration.state import AG_UI_RUN_METADATA, is_ag_ui_run

    g = StateGraph(SupervisorState)
    g.add_node("n", lambda state: {})
    g.add_edge(START, "n")
    g.add_edge("n", END)
    agent = build_market_desk_agent(g.compile())
    assert is_ag_ui_run(agent.config)
    assert agent.config["metadata"] == AG_UI_RUN_METADATA
