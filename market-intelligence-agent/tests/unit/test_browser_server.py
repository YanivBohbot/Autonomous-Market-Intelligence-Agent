"""Unit tests for the custom browser MCP server tool functions.

We import the underlying tool implementations directly (bypassing FastMCP
transport) and mock the session manager so the tests are pure.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


def test_browser_navigate_calls_page_goto():
    with patch.dict(os.environ, {
        "BROWSER_TOOL_ID": "arn:1", "BROWSER_THREAD_ID": "t1",
        "BROWSER_IDLE_TTL_S": "300",
    }, clear=False):
        with patch("app.mcp.browser.server._manager") as mgr_holder:
            page = MagicMock(name="Page")
            mgr = MagicMock()
            mgr.with_retry.side_effect = lambda op, **kw: op(page)
            mgr_holder.return_value = mgr

            from app.mcp.browser.server import _navigate_impl
            result = _navigate_impl("https://example.com")
            page.goto.assert_called_once_with("https://example.com", timeout=30000)
            assert "Navigated to https://example.com" in result


def test_browser_snapshot_returns_accessibility_tree():
    with patch.dict(os.environ, {
        "BROWSER_TOOL_ID": "arn:1", "BROWSER_THREAD_ID": "t1",
    }, clear=False):
        with patch("app.mcp.browser.server._manager") as mgr_holder:
            page = MagicMock(name="Page")
            page.accessibility.snapshot.return_value = {"role": "WebArea", "name": "Example Domain"}
            mgr = MagicMock()
            mgr.with_retry.side_effect = lambda op, **kw: op(page)
            mgr_holder.return_value = mgr

            from app.mcp.browser.server import _snapshot_impl
            result = _snapshot_impl()
            assert "Example Domain" in result


def test_browser_screenshot_writes_into_workspace(tmp_path):
    with patch.dict(os.environ, {
        "BROWSER_TOOL_ID": "arn:1", "BROWSER_THREAD_ID": "t1",
        "WORKSPACE_ROOT": str(tmp_path),
    }, clear=False):
        with patch("app.mcp.browser.server._manager") as mgr_holder:
            page = MagicMock(name="Page")
            mgr = MagicMock()
            mgr.with_retry.side_effect = lambda op, **kw: op(page)
            mgr_holder.return_value = mgr

            from app.mcp.browser.server import _screenshot_impl
            result = _screenshot_impl("evidence.png")
            page.screenshot.assert_called_once()
            assert "screenshots/evidence.png" in result.replace("\\", "/")
