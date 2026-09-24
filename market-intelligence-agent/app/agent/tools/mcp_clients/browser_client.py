"""Playwright Browser MCP client — selects browser-server tools out of the shared registry.

Public symbols: `browser_navigate_tool`, `browser_snapshot_tool`,
`browser_screenshot_tool`. All three are read-only from the agent's perspective and
slot into READ_ONLY_TOOLS — they perform network reads and (for screenshots) write
into the dedicated `data/workspace/screenshots/` subfolder, away from user-facing
briefs in the workspace root.

Sandboxing is enforced by the @playwright/mcp server itself (headless Chromium,
no host filesystem access outside --output-dir).
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.browser_session import (
    PersistentToolSession,
    open_local_browser_tools,
    persistent_tool,
)
from app.agent.tools.mcp_clients.registry import select_tool
from app.core.config import settings

logger = logging.getLogger(__name__)

NAVIGATE_TOOL_NAME = "browser_navigate"
SNAPSHOT_TOOL_NAME = "browser_snapshot"
SCREENSHOT_TOOL_NAME = "browser_take_screenshot"

# Local @playwright/mcp: all three tools run on ONE long-lived session so
# navigate -> snapshot -> screenshot act on the same page (a per-call session
# meant a fresh, blank Chromium each time). The agentcore backend is left as
# is: its server keeps the page in the remote AgentCore Browser session.
_local_session = PersistentToolSession(open_local_browser_tools)


def _browser_tool(name: str) -> BaseTool:
    tool = select_tool(name, "Playwright Browser")
    if (settings.BROWSER_BACKEND or "local").lower() == "local":
        return persistent_tool(tool, _local_session)
    return tool


browser_navigate_tool: BaseTool = _browser_tool(NAVIGATE_TOOL_NAME)
browser_snapshot_tool: BaseTool = _browser_tool(SNAPSHOT_TOOL_NAME)
browser_screenshot_tool: BaseTool = _browser_tool(SCREENSHOT_TOOL_NAME)
