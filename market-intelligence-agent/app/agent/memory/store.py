"""Store factory — the LangGraph BaseStore passed to workflow.compile(store=...).

Holds cross-thread data: ("user_facts",) for the memory tools and
("conversations",) for the Research history index (vector-indexed on the
item's "text" field, so the history can be searched by meaning).

Backends, selected via `STORE_BACKEND` env (read here, like MIA_MEMORY_ID in
checkpointer.py):
- `sqlite`: `AsyncSqliteStore` in `STORE_DB_PATH` (default data/store.db) —
  durable across restarts. Default when the checkpointer is sqlite (local dev).
- `memory`: `InMemoryStore` — tests and the AgentCore image (default there,
  since its CHECKPOINTER_BACKEND is agentcore).
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langchain_core.embeddings import Embeddings
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from app.core.config import settings

logger = logging.getLogger(__name__)

CONVERSATION_INDEX_FIELDS = ["text"]
EMBEDDING_DIMS = 1536  # text-embedding-3-small


def _backend() -> str:
    configured = os.environ.get("STORE_BACKEND", "").strip().lower()
    if configured:
        return configured
    return "sqlite" if settings.CHECKPOINTER_BACKEND.lower() == "sqlite" else "memory"


def _index(embeddings: Embeddings | None) -> dict:
    if embeddings is None:
        from app.rag.vectorstore import get_embeddings

        embeddings = get_embeddings()
    return {"dims": EMBEDDING_DIMS, "embed": embeddings, "fields": CONVERSATION_INDEX_FIELDS}


@asynccontextmanager
async def create_store(
    db_path: str | None = None, embeddings: Embeddings | None = None
) -> AsyncIterator[BaseStore]:
    """Yield the long-term store (user facts + Research conversation index)."""
    backend = _backend()
    if backend == "sqlite":
        # Lazy import: aiosqlite / sqlite-vec are not in the AgentCore image.
        from langgraph.store.sqlite.aio import AsyncSqliteStore

        path = db_path or os.environ.get("STORE_DB_PATH", "data/store.db")
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        logger.info("store backend=sqlite path=%s", path)
        async with AsyncSqliteStore.from_conn_string(path, index=_index(embeddings)) as store:
            await store.setup()
            yield store
        return
    if backend == "memory":
        logger.info("store backend=memory (lost on restart)")
        yield InMemoryStore(index=_index(embeddings))
        return
    raise ValueError(f"Unknown STORE_BACKEND={backend!r} (expected sqlite or memory)")
