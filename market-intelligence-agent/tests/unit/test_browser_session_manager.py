"""Unit tests for BrowserSessionManager.

The manager wraps bedrock_agentcore.tools.browser_client.BrowserClient +
Playwright. We mock both at the import boundary so tests run offline.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_browser_client():
    """A MagicMock standing in for BrowserClient instances."""
    mock = MagicMock(name="BrowserClient")
    # generate_ws_headers() returns (ws_url, headers); configure so tuple
    # unpacking in session_manager._start() works offline.
    mock.generate_ws_headers.return_value = (
        "wss://fake.example.com/browser-streams/foo/sessions/s1/automation",
        {"Authorization": "AWS4-HMAC-SHA256 ..."},
    )
    mock.session_id = "fake-session-id"
    return mock


@pytest.fixture
def fake_playwright_page():
    """A MagicMock standing in for the connected Playwright page."""
    return MagicMock(name="PlaywrightPage")


def test_lazy_start_calls_start_session_on_first_get_page(
    fake_browser_client, fake_playwright_page
):
    """First .get_page() call must start an AgentCore session and a Playwright
    connection. Subsequent calls must reuse them (no second start)."""
    with patch(
        "app.mcp.browser.session_manager.BrowserClient",
        return_value=fake_browser_client,
    ), patch(
        "app.mcp.browser.session_manager._connect_playwright",
        return_value=(MagicMock(), MagicMock(), fake_playwright_page),
    ) as fake_connect:
        from app.mcp.browser.session_manager import BrowserSessionManager

        mgr = BrowserSessionManager(
            browser_arn="arn:aws:bedrock-agentcore:us-east-1:1:browser/foo",
            thread_id="t1",
            idle_ttl_s=300,
        )
        page_a = mgr.get_page()
        page_b = mgr.get_page()

        assert page_a is fake_playwright_page
        assert page_b is fake_playwright_page
        # start() is the real SDK method name used by session_manager._start()
        assert fake_browser_client.start.call_count == 1
        assert fake_connect.call_count == 1


def test_connect_playwright_failure_cleans_up_server_session(fake_browser_client):
    """If _connect_playwright raises, _start() must call client.stop() (best-effort)
    and leave self._session as None so a subsequent get_page() doesn't try to
    call start() on a half-open server session."""
    pw_error = RuntimeError("CDP connect failed")

    # Import the module first so patch targets are resolvable.
    from app.mcp.browser.session_manager import BrowserSessionManager

    with patch(
        "app.mcp.browser.session_manager.BrowserClient",
        return_value=fake_browser_client,
    ), patch(
        "app.mcp.browser.session_manager._connect_playwright",
        side_effect=pw_error,
    ):
        mgr = BrowserSessionManager(
            browser_arn="arn:aws:bedrock-agentcore:us-east-1:1:browser/foo",
            thread_id="t2",
            idle_ttl_s=300,
        )

        with pytest.raises(RuntimeError, match="CDP connect failed"):
            mgr.get_page()

        # Server-side cleanup must have been attempted.
        fake_browser_client.stop.assert_called_once()
        # Session must remain None — no partial state left behind.
        assert mgr._session is None
