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


def test_evict_if_idle_stops_session_past_ttl(fake_browser_client, fake_playwright_page):
    """If now() - last_activity > idle_ttl_s, evict_if_idle stops the session.
    Next get_page() must lazy-start a fresh one."""
    with patch(
        "app.mcp.browser.session_manager.BrowserClient",
        return_value=fake_browser_client,
    ), patch(
        "app.mcp.browser.session_manager._connect_playwright",
        return_value=(MagicMock(), MagicMock(), fake_playwright_page),
    ):
        from app.mcp.browser import session_manager as sm
        clock = {"t": 1000.0}
        with patch.object(sm.time, "monotonic", side_effect=lambda: clock["t"]):
            mgr = sm.BrowserSessionManager(
                browser_arn="arn:1", thread_id="t1", idle_ttl_s=300,
            )
            mgr.get_page()  # session #1 starts at t=1000

            clock["t"] = 1100.0  # 100s later — under TTL
            mgr.evict_if_idle()
            assert fake_browser_client.stop.call_count == 0  # adapt: client method is `stop`, not `stop_session`

            clock["t"] = 1500.0  # 500s later — past TTL
            mgr.evict_if_idle()
            assert fake_browser_client.stop.call_count == 1

            mgr.get_page()  # forces session #2
            assert fake_browser_client.start.call_count == 2
