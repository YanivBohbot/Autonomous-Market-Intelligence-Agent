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

from app.agent.tools.mcp_clients.registry import select_tool

logger = logging.getLogger(__name__)

NAVIGATE_TOOL_NAME = "browser_navigate"
SNAPSHOT_TOOL_NAME = "browser_snapshot"
SCREENSHOT_TOOL_NAME = "browser_take_screenshot"

browser_navigate_tool: BaseTool = select_tool(NAVIGATE_TOOL_NAME, "Playwright Browser")
browser_snapshot_tool: BaseTool = select_tool(SNAPSHOT_TOOL_NAME, "Playwright Browser")
browser_screenshot_tool: BaseTool = select_tool(SCREENSHOT_TOOL_NAME, "Playwright Browser")
