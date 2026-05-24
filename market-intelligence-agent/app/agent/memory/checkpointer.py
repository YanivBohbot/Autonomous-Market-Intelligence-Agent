"""Checkpointer factory with a pluggable backend.

The default `sqlite` backend uses `AsyncSqliteSaver` against a local SQLite file —
the right choice for local dev where state must survive process restarts.

The `memory` backend uses LangGraph's in-process `InMemorySaver`. State is lost
when the container stops. This is the v1 production choice for AgentCore Runtime:
each AgentCore session lives inside a single container instance, so we don't need
cross-process persistence — session continuity is handled by AgentCore itself
keying the same `thread_id` to the same warm container. A future revision will
add an `agentcore` backend that persists facts to the AgentCore Memory service
via boto3, when an official LangGraph adapter ships.

Selected via `CHECKPOINTER_BACKEND` env: `sqlite` (default) | `memory`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def create_checkpointer(
    db_path: str | None = None,
) -> AsyncIterator[BaseCheckpointSaver]:
    backend = settings.CHECKPOINTER_BACKEND.lower()

    if backend == "sqlite":
        # Lazy import: langgraph-checkpoint-sqlite is not in the slim
        # AgentCore Runtime image (memory backend only). Local dev / tests
        # that select the sqlite backend keep working because uv.lock has it.
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        path = db_path or settings.CHECKPOINT_DB_PATH
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        logger.info("checkpointer backend=sqlite path=%s", path)
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            yield saver
        return

    if backend == "memory":
        logger.info("checkpointer backend=memory (state lost on restart)")
        yield InMemorySaver()
        return

    raise ValueError(
        f"Unknown CHECKPOINTER_BACKEND={settings.CHECKPOINTER_BACKEND!r}. "
        "Valid values: 'sqlite', 'memory'."
    )
