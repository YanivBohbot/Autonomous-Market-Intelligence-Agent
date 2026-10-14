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
