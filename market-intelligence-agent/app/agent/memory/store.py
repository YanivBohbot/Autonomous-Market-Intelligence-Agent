"""Store factory — produces the BaseStore passed to workflow.compile(store=...).

InMemoryStore is volatile (lost on server restart). Migrating to AsyncSqliteStore
later means changing this single function; nothing in graph.py or server.py needs
to know about the backend.
"""

from __future__ import annotations

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore


def create_store() -> BaseStore:
    """Return the long-term memory store used for cross-thread user facts."""
    return InMemoryStore()
