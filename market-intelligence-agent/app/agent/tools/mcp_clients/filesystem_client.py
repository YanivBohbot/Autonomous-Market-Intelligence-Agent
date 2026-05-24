"""Filesystem MCP client — selects the 3 filesystem tools out of the shared registry.

The official @modelcontextprotocol/server-filesystem server exposes ~14 tools; we
expose only the 3 needed for the read+write workspace use case. Sandboxing is
enforced by the server itself via the allowed-root argument set in registry.py.

Public symbols: fs_read_file_tool (read-only), fs_list_dir_tool (read-only),
fs_write_file_tool (gated by approval_node).

Storage backend
---------------
The MCP server runs against a local directory when `WORKSPACE_BACKEND=local`
(default, used in dev with `MCP_TRANSPORT=stdio`).

In production we set `MCP_TRANSPORT=gateway` and the filesystem tools are served
by a Lambda behind AgentCore Gateway. That Lambda reads `WORKSPACE_BACKEND=s3`
and `WORKSPACE_S3_BUCKET=mia-workspace-<acct>` and reroutes the same three tools
to S3 GetObject/PutObject/ListObjectsV2. The agent-side code in this file does
not need to change — the tool names and argument shapes are identical; only the
implementation behind the wire differs. See `prod/lambdas/filesystem/` for the
Lambda handler.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.registry import select_tool

logger = logging.getLogger(__name__)

READ_FILE_TOOL_NAME = "read_text_file"
LIST_DIR_TOOL_NAME = "list_directory"
WRITE_FILE_TOOL_NAME = "write_file"

fs_read_file_tool: BaseTool = select_tool(READ_FILE_TOOL_NAME, "Filesystem")
fs_list_dir_tool: BaseTool = select_tool(LIST_DIR_TOOL_NAME, "Filesystem")
fs_write_file_tool: BaseTool = select_tool(WRITE_FILE_TOOL_NAME, "Filesystem")
