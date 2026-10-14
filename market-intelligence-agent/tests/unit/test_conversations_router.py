from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.agent.memory import conversations as conv
from app.api.server import app

client = TestClient(app)
T0 = datetime(2026, 10, 14, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _state():
    app.state.store = InMemoryStore(index={"dims": 32, "embed": DeterministicFakeEmbedding(size=32), "fields": ["text"]})
    app.state.checkpointer = InMemorySaver()
    yield


def _seed(tid, q):
    import asyncio

    asyncio.run(conv.record_conversation_turn(app.state.store, tid, q, now=T0))


def test_list():
    _seed("desk_a", "Alpha")
    r = client.get("/conversations")
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == ["desk_a"]


def test_rename_and_404_and_validation():
    _seed("desk_a", "Alpha")
    assert client.patch("/conversations/desk_a", json={"title": "Beta"}).json()["title"] == "Beta"
    assert client.patch("/conversations/desk_zzz", json={"title": "X"}).status_code == 404
    assert client.patch("/conversations/desk_a", json={"title": "   "}).status_code == 422
    assert client.patch("/conversations/desk_a", json={"title": "x" * 81}).status_code == 422


def test_delete():
    _seed("desk_a", "Alpha")
    assert client.delete("/conversations/desk_a").status_code == 204
    assert client.get("/conversations").json() == []
    assert client.delete("/conversations/desk_a").status_code == 204  # idempotent


def test_delete_refuses_non_research_thread():
    assert client.delete("/conversations/clients_17").status_code == 400


def test_delete_refused_while_a_turn_owns_the_thread():
    import asyncio
    from app.agent.turn_coordinator import ThreadTurnCoordinator

    app.state.turn_coordinator = ThreadTurnCoordinator()
    _seed("desk_busy", "Busy")
    lease = asyncio.run(app.state.turn_coordinator.try_acquire("desk_busy", "text"))
    assert client.delete("/conversations/desk_busy").status_code == 409
    asyncio.run(app.state.turn_coordinator.release(lease))
    assert client.delete("/conversations/desk_busy").status_code == 204
