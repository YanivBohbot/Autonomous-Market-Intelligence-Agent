"""Long-term user-facts memory — three native LangChain tools backed by the
LangGraph `BaseStore` injected at graph compile time.

`save_memory` is a side-effect (gated by approval_node). `recall_memory` and
`list_memories` are read-only and slot into READ_ONLY_TOOLS. All three are
async and operate on the single namespace `("user_facts",)`. The single-bucket
choice fits the single-user portfolio agent; multi-tenant namespacing is a
future-subsystem concern.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedStore

logger = logging.getLogger(__name__)

USER_FACTS_NS = ("user_facts",)


@tool
async def save_memory(
    key: str,
    value: str,
    store: Annotated[Any, InjectedStore()],
) -> str:
    """Persist a durable user fact across sessions. Use short snake_case keys
    (e.g. 'email', 'investment_horizon'). Call only when the user has stated a
    fact about themselves they would want remembered next time."""
    await store.aput(USER_FACTS_NS, key, {"value": value})
    logger.info("save_memory: %s=%s", key, value)
    return f"Saved {key}={value}"


@tool
async def recall_memory(
    key: str,
    store: Annotated[Any, InjectedStore()],
) -> str:
    """Look up a previously-saved user fact by key."""
    item = await store.aget(USER_FACTS_NS, key)
    if item is None:
        return f"No memory for key {key!r}"
    return str(item.value.get("value", ""))


@tool
async def list_memories(store: Annotated[Any, InjectedStore()]) -> list[str]:
    """List every user fact in memory as 'key = value' strings."""
    items = await store.asearch(USER_FACTS_NS)
    return [f"{i.key} = {i.value.get('value', '')}" for i in items]


save_memory_tool = save_memory
recall_memory_tool = recall_memory
list_memories_tool = list_memories
