import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from app.agent.memory import conversations as conv
from app.agent.orchestration import graph as graph_mod
from app.agent.orchestration.state import SupervisorState


def _app(store):
    g = StateGraph(SupervisorState)
    g.add_node(
        "record_question",
        RunnableLambda(graph_mod.record_multi_agent_question, afunc=graph_mod.arecord_multi_agent_question),
    )
    g.add_edge(START, "record_question")
    g.add_edge("record_question", END)
    return g.compile(checkpointer=InMemorySaver(), store=store)


def _store():
    return InMemoryStore(index={"dims": 32, "embed": DeterministicFakeEmbedding(size=32), "fields": ["text"]})


@pytest.mark.anyio
async def test_research_turn_is_indexed():
    store = _store()
    out = await _app(store).ainvoke({"question": "NVDA news?"}, {"configurable": {"thread_id": "desk_t1"}})
    assert out["messages"][-1].content == "NVDA news?"
    assert (await store.aget(conv.NAMESPACE, "desk_t1")).value["title"] == "NVDA news?"


@pytest.mark.anyio
async def test_client_turn_is_not_indexed():
    store = _store()
    await _app(store).ainvoke({"question": "Hi"}, {"configurable": {"thread_id": "clients_3"}})
    assert await store.asearch(conv.NAMESPACE) == []


@pytest.mark.anyio
async def test_index_failure_never_fails_the_turn(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(graph_mod, "record_conversation_turn", boom)
    out = await _app(_store()).ainvoke({"question": "Q"}, {"configurable": {"thread_id": "desk_t2"}})
    assert out["messages"][-1].content == "Q"


@pytest.mark.anyio
async def test_no_store_is_fine():
    g = StateGraph(SupervisorState)
    g.add_node("record_question", RunnableLambda(graph_mod.record_multi_agent_question, afunc=graph_mod.arecord_multi_agent_question))
    g.add_edge(START, "record_question")
    g.add_edge("record_question", END)
    out = await g.compile(checkpointer=InMemorySaver()).ainvoke({"question": "Q"}, {"configurable": {"thread_id": "desk_t3"}})
    assert out["messages"][-1].content == "Q"


def test_graph_registers_async_record_question():
    node = graph_mod._build_workflow().nodes["record_question"].runnable
    assert getattr(node, "afunc", None) is getattr(graph_mod, "arecord_multi_agent_question", object())


@pytest.mark.anyio
async def test_ag_ui_turn_without_question_key_is_indexed():
    # Market Desk (AG-UI) sends the user turn as a message, not as "question".
    from langchain_core.messages import AIMessage, HumanMessage

    store = _store()
    history = [HumanMessage("Old question"), AIMessage("Old answer"), HumanMessage("Compare NVDA and AMD")]
    out = await _app(store).ainvoke({"messages": history}, {"configurable": {"thread_id": "desk_t4"}})
    assert out["messages"][-1].content == "Compare NVDA and AMD"
    assert (await store.aget(conv.NAMESPACE, "desk_t4")).value["title"] == "Compare NVDA and AMD"


@pytest.mark.anyio
async def test_turn_ending_on_ai_message_is_not_indexed():
    from langchain_core.messages import AIMessage, HumanMessage

    store = _store()
    await _app(store).ainvoke({"messages": [HumanMessage("Q"), AIMessage("A")]}, {"configurable": {"thread_id": "desk_t5"}})
    assert await store.aget(conv.NAMESPACE, "desk_t5") is None


def _finalize_app(store):
    g = StateGraph(SupervisorState)
    g.add_node("finalize_turn", RunnableLambda(graph_mod.finalize_turn, afunc=graph_mod.afinalize_turn))
    g.add_edge(START, "finalize_turn")
    g.add_edge("finalize_turn", END)
    return g.compile(checkpointer=InMemorySaver(), store=store)


@pytest.mark.anyio
async def test_finalize_turn_indexes_the_answer():
    from langchain_core.messages import AIMessage, HumanMessage

    store = _store()
    await conv.record_conversation_turn(store, "desk_t6", "Compare NVDA vs AMD")
    msgs = [HumanMessage("Compare NVDA vs AMD"), AIMessage("Both are semiconductor makers.")]
    await _finalize_app(store).ainvoke({"messages": msgs}, {"configurable": {"thread_id": "desk_t6"}})
    assert "semiconductor makers" in (await store.aget(conv.NAMESPACE, "desk_t6")).value["text"]


@pytest.mark.anyio
async def test_finalize_answer_index_failure_never_fails_the_turn(monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage

    async def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(graph_mod, "record_conversation_answer", boom)
    msgs = [HumanMessage("Q"), AIMessage("A")]
    out = await _finalize_app(_store()).ainvoke({"messages": msgs}, {"configurable": {"thread_id": "desk_t7"}})
    assert out["messages"][-1].content == "A"


def test_graph_registers_async_finalize_turn():
    node = graph_mod._build_workflow().nodes["finalize_turn"].runnable
    assert getattr(node, "afunc", None) is getattr(graph_mod, "afinalize_turn", object())
