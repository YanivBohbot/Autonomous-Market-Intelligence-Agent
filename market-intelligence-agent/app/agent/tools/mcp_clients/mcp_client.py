"""CRM MCP client — selects CRM-server tools out of the shared registry.

Public surface preserved: `crm_tool` is the single LangChain BaseTool for SQL reads
against the customer database. Schema and routing are unchanged; only the underlying
transport moved to langchain-mcp-adapters.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.registry import select_tool

logger = logging.getLogger(__name__)

CRM_TOOL_NAME = "read_query"

crm_tool: BaseTool = select_tool(CRM_TOOL_NAME, "CRM")
