import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langgraph.store.memory import InMemoryStore

from app.agent.memory import store as store_mod
from app.agent.memory.store import create_store

FAKE = DeterministicFakeEmbedding(size=1536)


@pytest.mark.anyio
async def test_sqlite_store_persists_across_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "sqlite")
    path = str(tmp_path / "store.db")
    async with create_store(path, embeddings=FAKE) as s:
        await s.aput(("user_facts",), "email", {"value": "a@b.c"}, index=False)
    async with create_store(path, embeddings=FAKE) as s:
        item = await s.aget(("user_facts",), "email")
    assert item.value == {"value": "a@b.c"}


@pytest.mark.anyio
async def test_sqlite_store_semantic_search(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "sqlite")
    async with create_store(str(tmp_path / "s.db"), embeddings=FAKE) as s:
        await s.aput(("conversations",), "desk_a", {"text": "NVDA vs AMD"})
        await s.aput(("conversations",), "desk_b", {"text": "Cohen portfolio"})
        hits = await s.asearch(("conversations",), query="NVDA vs AMD", limit=1)
    assert hits[0].key == "desk_a"


@pytest.mark.anyio
async def test_memory_backend(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    async with create_store(embeddings=FAKE) as s:
        assert isinstance(s, InMemoryStore)


@pytest.mark.anyio
async def test_default_backend_follows_checkpointer(monkeypatch):
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setattr(store_mod.settings, "CHECKPOINTER_BACKEND", "agentcore")
    async with create_store(embeddings=FAKE) as s:
        assert isinstance(s, InMemoryStore)


@pytest.mark.anyio
async def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "nope")
    with pytest.raises(ValueError):
        async with create_store(embeddings=FAKE):
            pass
