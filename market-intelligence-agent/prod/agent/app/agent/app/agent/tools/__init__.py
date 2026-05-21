"""Tool registry — Phase 4a (Gateway-backed yfinance + CRM tools).

MCP-backed tools (yfinance, CRM) are now exposed via AgentCore Gateway as
Lambda targets and consumed in the container over `streamable_http`. The
registry (`mcp_clients/registry.py`) handles the local-dev fallback: when
`GATEWAY_URL` is unset, it returns an empty tool list and `select_tool`
returns no-op placeholders. We wrap the imports in a try/except as belt-and-
braces so any unexpected registry failure still lets the container boot with
the native tools (email + memory).

Filesystem and browser tools intentionally stay disabled — Phase 4b covers
AgentCore Browser; filesystem is dropped pending real user demand.
"""
import logging

from app.agent.tools.emails import send_email_tool
from app.agent.tools.memory import (
    save_memory_tool,
    recall_memory_tool,
    list_memories_tool,
)

logger = logging.getLogger(__name__)

# Base set: native LangChain tools that don't depend on MCP / Gateway.
TOOLS = [
    send_email_tool,
    save_memory_tool,
    recall_memory_tool,
    list_memories_tool,
]

# READ_ONLY_TOOLS is consulted by approval_node by *name*, not by tool object.
# Names stay valid here whether or not the tool object is actually loaded into
# TOOLS — the allowlist is the union the approval logic understands. If a tool
# isn't in TOOLS, the LLM won't have it bound and won't try to call it; the
# name simply never appears in pending_tool_calls.
READ_ONLY_TOOLS: set[str] = {
    "recall_memory",
    "list_memories",
    "read_query",
    "yfinance_get_ticker_info",
    "yfinance_get_price_history",
    "yfinance_get_ticker_news",
}

# Attempt to load Gateway-backed tools. In local dev (no GATEWAY_URL) the
# registry returns an empty tuple and select_tool() yields no-op placeholders
# whose .name still matches but whose .func raises if ever invoked. We detect
# that case by checking whether the registry actually produced tools.
try:
    from app.agent.tools.mcp_clients.registry import get_mcp_tools
    from app.agent.tools.mcp_clients.mcp_client import crm_tool
    from app.agent.tools.mcp_clients.yfinance_client import (
        yf_quote_tool,
        yf_history_tool,
        yf_news_tool,
    )

    _gateway_tools = get_mcp_tools()
    if _gateway_tools:
        TOOLS.extend([crm_tool, yf_quote_tool, yf_history_tool, yf_news_tool])
        logger.info(
            "[tools] Gateway-backed tools enabled: %s",
            [t.name for t in (crm_tool, yf_quote_tool, yf_history_tool, yf_news_tool)],
        )
    else:
        logger.info(
            "[tools] MCP-backed tools unavailable, falling back to in-container set"
        )
except Exception as exc:  # noqa: BLE001
    logger.warning(
        "[tools] Failed to import Gateway-backed tools (%r) — falling back to in-container set",
        exc,
    )

# Note: We deliberately do NOT validate that every READ_ONLY_TOOLS entry is in
# TOOLS. The allowlist is name-based and tracks the union of tools the agent
# *could* have when fully wired (in production). Tools missing from TOOLS in
# local dev just never get called.

__all__ = [
    "TOOLS",
    "READ_ONLY_TOOLS",
    "send_email_tool",
    "save_memory_tool",
    "recall_memory_tool",
    "list_memories_tool",
]
