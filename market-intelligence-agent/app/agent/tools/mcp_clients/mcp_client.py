"""CRM MCP client — selects client-database tools out of the shared registry.

Public surface: `crm_tool` (read_query), `crm_list_tables_tool` and
`crm_describe_table_tool` — all read-only SQL access to customers.db.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.registry import select_tool

logger = logging.getLogger(__name__)

CRM_TOOL_NAME = "read_query"

crm_tool: BaseTool = select_tool(CRM_TOOL_NAME, "CRM")
# Read-only schema discovery. mcp-server-sqlite also offers write_query,
# create_table and append_insight — deliberately NOT selected (read-only DB).
crm_list_tables_tool: BaseTool = select_tool("list_tables", "CRM")
crm_describe_table_tool: BaseTool = select_tool("describe_table", "CRM")
