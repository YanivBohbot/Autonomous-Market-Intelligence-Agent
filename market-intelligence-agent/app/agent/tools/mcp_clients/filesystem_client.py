"""Filesystem MCP client — selects the 3 filesystem tools out of the shared registry.

The official @modelcontextprotocol/server-filesystem server exposes ~14 tools; we
expose only the 3 needed for the read+write workspace use case. Sandboxing is
enforced by the server itself via the allowed-root argument set in registry.py.

Public symbols: fs_read_file_tool (read-only), fs_list_dir_tool (read-only),
fs_write_file_tool (gated by approval_node).
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.registry import get_mcp_tools

logger = logging.getLogger(__name__)

READ_FILE_TOOL_NAME = "read_text_file"
LIST_DIR_TOOL_NAME = "list_directory"
WRITE_FILE_TOOL_NAME = "write_file"


def _select(name: str) -> BaseTool:
    for tool in get_mcp_tools():
        if tool.name == name:
            return tool
    raise RuntimeError(
        f"Filesystem MCP tool {name!r} not found in registry; check server config."
    )


fs_read_file_tool: BaseTool = _select(READ_FILE_TOOL_NAME)
fs_list_dir_tool: BaseTool = _select(LIST_DIR_TOOL_NAME)
fs_write_file_tool: BaseTool = _select(WRITE_FILE_TOOL_NAME)
