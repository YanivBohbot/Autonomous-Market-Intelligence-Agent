from datetime import datetime, timedelta, timezone

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.store.memory import InMemoryStore

from app.agent.memory import conversations as conv

T0 = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)


def _store():
    return InMemoryStore(index={"dims": 64, "embed": DeterministicFakeEmbedding(size=64), "fields": ["text"]})


@pytest.mark.anyio
async def test_first_turn_creates_item_with_truncated_title():
    s = _store()
    q = "Compare   NVDA and AMD over the last six months, including valuation and momentum please"
    await conv.record_conversation_turn(s, "desk_a", q, now=T0)
    item = (await s.aget(conv.NAMESPACE, "desk_a")).value
    assert item["title"] == "Compare NVDA and AMD over the last six months, including val…"
    assert len(item["title"]) == 61
    assert item["created_at"] == item["updated_at"] == T0.isoformat()
    assert item["questions"] == [" ".join(q.split())]
    assert item["title"] in item["text"]


@pytest.mark.anyio
async def test_later_turn_keeps_title_and_updates():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "First", now=T0)
    await conv.record_conversation_turn(s, "desk_a", "Second", now=T0 + timedelta(hours=1))
    item = (await s.aget(conv.NAMESPACE, "desk_a")).value
    assert item["title"] == "First"
    assert item["created_at"] == T0.isoformat()
    assert item["updated_at"] == (T0 + timedelta(hours=1)).isoformat()
    assert item["questions"] == ["First", "Second"]


@pytest.mark.anyio
async def test_keeps_last_ten_questions():
    s = _store()
    for i in range(12):
        await conv.record_conversation_turn(s, "desk_a", f"q{i}", now=T0)
    assert (await s.aget(conv.NAMESPACE, "desk_a")).value["questions"] == [f"q{i}" for i in range(2, 12)]


@pytest.mark.anyio
async def test_rename_survives_later_turn():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "First", now=T0)
    assert (await conv.rename_conversation(s, "desk_a", "  Chip stocks  "))["title"] == "Chip stocks"
    await conv.record_conversation_turn(s, "desk_a", "Second", now=T0)
    assert (await s.aget(conv.NAMESPACE, "desk_a")).value["title"] == "Chip stocks"


@pytest.mark.anyio
async def test_rename_unknown_returns_none():
    assert await conv.rename_conversation(_store(), "desk_x", "T") is None


@pytest.mark.anyio
async def test_non_research_threads_are_ignored():
    s = _store()
    for tid in ("clients_17", "qa_desk_1", "default_thread", "web_session_x"):
        await conv.record_conversation_turn(s, tid, "Q", now=T0)
    assert await s.asearch(conv.NAMESPACE) == []


@pytest.mark.anyio
async def test_empty_question_ignored():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "   ", now=T0)
    assert await s.aget(conv.NAMESPACE, "desk_a") is None


@pytest.mark.anyio
async def test_list_sorted_by_updated_desc():
    s = _store()
    await conv.record_conversation_turn(s, "desk_old", "Old", now=T0)
    await conv.record_conversation_turn(s, "desk_new", "New", now=T0 + timedelta(days=1))
    rows = await conv.list_conversations(s)
    assert [r["id"] for r in rows] == ["desk_new", "desk_old"]
    assert set(rows[0]) == {"id", "title", "created_at", "updated_at"}


@pytest.mark.anyio
async def test_search_returns_semantic_match_first():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "NVDA vs AMD", now=T0)
    await conv.record_conversation_turn(s, "desk_b", "Cohen portfolio", now=T0)
    item = (await s.aget(conv.NAMESPACE, "desk_a")).value
    rows = await conv.list_conversations(s, query=item["text"])
    assert rows[0]["id"] == "desk_a"


@pytest.mark.anyio
async def test_search_drops_low_scores(monkeypatch):
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "NVDA vs AMD", now=T0)
    monkeypatch.setattr(conv, "SEARCH_MIN_SCORE", 1.01)
    assert await conv.list_conversations(s, query="anything") == []


@pytest.mark.anyio
async def test_blank_query_is_plain_list():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "A", now=T0)
    assert [r["id"] for r in await conv.list_conversations(s, query="  ")] == ["desk_a"]


@pytest.mark.anyio
async def test_delete_removes_checkpoints_and_item():
    s = _store()
    saver = InMemorySaver()
    g = StateGraph(MessagesState)
    g.add_node("n", lambda st: {})
    g.add_edge(START, "n")
    app = g.compile(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "desk_a"}}
    await app.ainvoke({"messages": [HumanMessage("hi")]}, cfg)
    await conv.record_conversation_turn(s, "desk_a", "hi", now=T0)
    await conv.delete_conversation(s, saver, "desk_a")
    assert await saver.aget_tuple(cfg) is None
    assert await s.aget(conv.NAMESPACE, "desk_a") is None


def test_filter_hits_floor_and_relative_cut():
    from types import SimpleNamespace as H

    hits = [H(key="a", score=0.40), H(key="b", score=0.33), H(key="c", score=0.30), H(key="d", score=0.15)]
    assert [h.key for h in conv._filter_hits(hits)] == ["a", "b"]  # 0.30 < 0.8 * 0.40
    assert conv._filter_hits([H(key="x", score=0.19)]) == []  # below the floor
    assert conv._filter_hits([]) == []


@pytest.mark.anyio
async def test_answer_excerpts_join_the_searchable_text():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "Compare NVDA vs AMD", now=T0)
    for i in range(4):
        await conv.record_conversation_answer(s, "desk_a", f"Answer {i}: both are semiconductor makers. " + "x" * 600)
    item = (await s.aget(conv.NAMESPACE, "desk_a")).value
    assert [a[:8] for a in item["answers"]] == ["Answer 1", "Answer 2", "Answer 3"]
    assert all(len(a) <= conv.ANSWER_MAX + 1 for a in item["answers"])
    assert "semiconductor makers" in item["text"]
    assert item["title"] == "Compare NVDA vs AMD"


@pytest.mark.anyio
async def test_answer_without_indexed_conversation_is_ignored():
    s = _store()
    await conv.record_conversation_answer(s, "desk_none", "An answer")
    await conv.record_conversation_answer(s, "clients_3", "An answer")
    assert await s.asearch(conv.NAMESPACE) == []


@pytest.mark.anyio
async def test_rename_keeps_answers_in_text():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "Q", now=T0)
    await conv.record_conversation_answer(s, "desk_a", "semiconductor answer")
    await conv.rename_conversation(s, "desk_a", "Chips")
    assert "semiconductor answer" in (await s.aget(conv.NAMESPACE, "desk_a")).value["text"]


@pytest.mark.anyio
async def test_card_numbers_never_reach_the_index():
    s = _store()
    await conv.record_conversation_turn(s, "desk_a", "Pay with 4111 1111 1111 1111 please", now=T0)
    await conv.record_conversation_turn(s, "desk_a", "card 4111111111111111 again", now=T0)
    await conv.record_conversation_answer(s, "desk_a", "I saw 4111111111111111 in your message")
    value = (await s.aget(conv.NAMESPACE, "desk_a")).value
    blob = repr(value)
    assert "4111111111111111" not in blob and "4111 1111 1111 1111" not in blob
    assert "1111" in value["title"]  # masked to the last 4 digits, like PIIMiddleware
