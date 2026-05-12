"""Async SQLite checkpointer factory.

`AsyncSqliteSaver` is the only SQLite checkpointer LangGraph supports for async
graph execution (`astream`/`ainvoke`). It must be entered from a running event
loop, so this module exposes an `@asynccontextmanager` rather than a plain
function. Callers (FastAPI lifespan, async helper scripts) open the context to
get back a fully initialized saver and the connection is closed on exit.

Per langgraph docs: https://langchain-ai.github.io/langgraph/reference/checkpoints/
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.core.config import settings


@asynccontextmanager
async def create_checkpointer(
    db_path: str | None = None,
) -> AsyncIterator[AsyncSqliteSaver]:
    """Open an `AsyncSqliteSaver` backed by an aiosqlite connection.

    The parent directory is created if missing. The aiosqlite worker thread is
    started inside `__aenter__` and torn down on `__aexit__` so the caller does
    not need to manage the connection lifecycle.
    """
    path = db_path or settings.CHECKPOINT_DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        yield AsyncSqliteSaver(conn)
