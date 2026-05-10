"""CRM MCP client — selects CRM-server tools out of the shared registry.

Public surface preserved: `crm_tool` is the single LangChain BaseTool for SQL reads
against the customer database. Schema and routing are unchanged; only the underlying
transport moved to langchain-mcp-adapters.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.registry import get_mcp_tools

logger = logging.getLogger(__name__)

CRM_TOOL_NAME = "crm_read_query"


def _select_crm_tool() -> BaseTool:
    for tool in get_mcp_tools():
        if tool.name == CRM_TOOL_NAME:
            return tool
    raise RuntimeError(
        f"CRM MCP tool {CRM_TOOL_NAME!r} not found in registry; check server config."
    )


crm_tool: BaseTool = _select_crm_tool()
