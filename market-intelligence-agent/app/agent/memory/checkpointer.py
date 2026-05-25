"""Checkpointer factory with a pluggable backend.

Backends, selected via `CHECKPOINTER_BACKEND` env:

- `sqlite` (default): `AsyncSqliteSaver` against a local SQLite file —
  right choice for local dev where state must survive process restarts.
- `memory`: LangGraph's in-process `InMemorySaver`. State is lost when
  the container stops AND when AgentCore routes a follow-up call to a
  different container. Use only for tests / very-short single-turn
  flows.
- `agentcore`: `AgentCoreMemorySaver` (from `langgraph-checkpoint-aws`),
  backed by an AgentCore Memory resource. Durable across containers —
  the right choice for any AgentCore Runtime deployment that does
  multi-turn or HITL. Requires `MIA_MEMORY_ID` and AWS creds with
  `bedrock-agentcore:CreateEvent`, `ListEvents`, `RetrieveMemories`
  on the memory ARN.
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

    if backend == "agentcore":
        # Durable, multi-container checkpointer backed by AgentCore Memory.
        # Required when running on AgentCore Runtime so that HITL resume and
        # cross-turn recall work regardless of which container handles which
        # turn. See docs/superpowers/specs/2026-05-25-durable-checkpointer-design.md.
        from langgraph_checkpoint_aws import AgentCoreMemorySaver

        memory_id = os.environ.get("MIA_MEMORY_ID")
        if not memory_id:
            raise RuntimeError(
                "CHECKPOINTER_BACKEND=agentcore requires MIA_MEMORY_ID env var "
                "(set automatically by the runtime CDK stack)."
            )
        region = os.environ.get("AWS_REGION", "us-east-1")
        logger.info(
            "checkpointer backend=agentcore memory_id=%s region=%s",
            memory_id, region,
        )
        yield AgentCoreMemorySaver(memory_id, region_name=region)
        return

    raise ValueError(
        f"Unknown CHECKPOINTER_BACKEND={settings.CHECKPOINTER_BACKEND!r}. "
        "Valid values: 'sqlite', 'memory', 'agentcore'."
    )
