"""Research conversation index in the LangGraph store.

One item per Research thread (`desk_*`) in ("conversations",): title (first
question, renamable), timestamps, the last questions, and `text` -- the
field the store embeds, so the history can be searched by meaning.
Messages themselves stay in the checkpointer."""

from __future__ import annotations

from datetime import datetime, timezone

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

NAMESPACE = ("conversations",)
RESEARCH_PREFIX = "desk_"
TITLE_MAX = 60
QUESTION_MAX = 300
MAX_QUESTIONS = 10
SEARCH_MIN_SCORE = 0.25
_LIST_SCAN = 1000


def is_research_thread(thread_id: str) -> bool:
    return isinstance(thread_id, str) and thread_id.startswith(RESEARCH_PREFIX)


def _clean(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _text(title: str, questions: list[str]) -> str:
    return "\n".join([title, *questions])


def _row(key: str, value: dict) -> dict:
    return {"id": key, "title": value["title"], "created_at": value["created_at"], "updated_at": value["updated_at"]}


async def record_conversation_turn(
    store: BaseStore, thread_id: str, question: str, now: datetime | None = None
) -> None:
    if not is_research_thread(thread_id):
        return
    q = _clean(question, QUESTION_MAX)
    if not q:
        return
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    existing = await store.aget(NAMESPACE, thread_id)
    if existing is None:
        value = {"title": _clean(question, TITLE_MAX), "created_at": stamp, "questions": []}
    else:
        value = dict(existing.value)
    value["questions"] = [*value.get("questions", []), q][-MAX_QUESTIONS:]
    value["updated_at"] = stamp
    value["text"] = _text(value["title"], value["questions"])
    await store.aput(NAMESPACE, thread_id, value)


async def list_conversations(store: BaseStore, query: str | None = None, limit: int = 50) -> list[dict]:
    if query and query.strip():
        hits = await store.asearch(NAMESPACE, query=query.strip(), limit=limit)
        return [_row(h.key, h.value) for h in hits if (h.score or 0) >= SEARCH_MIN_SCORE]
    items = await store.asearch(NAMESPACE, limit=_LIST_SCAN)
    items.sort(key=lambda i: i.value.get("updated_at", ""), reverse=True)
    return [_row(i.key, i.value) for i in items[:limit]]


async def rename_conversation(store: BaseStore, thread_id: str, title: str) -> dict | None:
    existing = await store.aget(NAMESPACE, thread_id)
    if existing is None:
        return None
    value = dict(existing.value)
    value["title"] = _clean(title, 80)
    value["text"] = _text(value["title"], value.get("questions", []))
    await store.aput(NAMESPACE, thread_id, value)
    return _row(thread_id, value)


async def delete_conversation(store: BaseStore, checkpointer: BaseCheckpointSaver, thread_id: str) -> None:
    await checkpointer.adelete_thread(thread_id)
    await store.adelete(NAMESPACE, thread_id)
