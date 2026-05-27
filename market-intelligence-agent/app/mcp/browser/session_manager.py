"""Per-process AgentCore Browser session manager.

Holds at most one live AgentCore Browser session, lazily started on the first
get_page() call. Reuses the cached Playwright Page for the lifetime of the
session. Idle-TTL eviction and auto-reconnect are added in later tasks (T3/T4).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from bedrock_agentcore.tools.browser_client import BrowserClient  # type: ignore

logger = logging.getLogger(__name__)


def _connect_playwright(ws_url: str, headers: dict):
    """Connect Playwright over CDP and return (browser, context, page).

    Split into a module-level function so tests can monkeypatch it without
    touching the real playwright import.
    """
    from playwright.sync_api import sync_playwright  # type: ignore

    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(ws_url, headers=headers)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.pages[0] if context.pages else context.new_page()
    return browser, context, page


@dataclass
class _Session:
    session_id: str
    browser: Any
    context: Any
    page: Any
    last_activity_s: float


class BrowserSessionManager:
    """Manages a single lazy-started AgentCore Browser session per thread_id.

    Usage::

        mgr = BrowserSessionManager(
            browser_arn="arn:aws:bedrock-agentcore:us-east-1:123:browser/foo",
            thread_id="t1",
        )
        page = mgr.get_page()   # starts session on first call; reuses thereafter
    """

    def __init__(
        self,
        *,
        browser_arn: str,
        thread_id: str,
        idle_ttl_s: int = 300,
    ) -> None:
        self.browser_arn = browser_arn
        self.thread_id = thread_id
        self.idle_ttl_s = idle_ttl_s

        _aws_region = os.environ.get("AWS_REGION") or os.environ.get(
            "AWS_DEFAULT_REGION"
        )
        if not _aws_region:
            logger.warning(
                "AWS_REGION/AWS_DEFAULT_REGION unset, defaulting to us-east-1"
            )
            _aws_region = "us-east-1"
        self._client = BrowserClient(_aws_region)
        self._session: _Session | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_page(self):
        """Return the active Playwright page, starting a session if needed."""
        with self._lock:
            if self._session is None:
                self._start()
            self._session.last_activity_s = time.monotonic()  # type: ignore[union-attr]
            return self._session.page  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _start(self) -> None:
        """Start an AgentCore Browser session and connect Playwright over CDP."""
        logger.info(
            "Starting AgentCore Browser session thread=%s arn=%s",
            self.thread_id,
            self.browser_arn,
        )
        # start() sets self._client.identifier and self._client.session_id,
        # and returns the session_id string.
        self._client.start(
            identifier=self.browser_arn,
            session_timeout_seconds=1800,
        )

        # generate_ws_headers() uses the stored identifier + session_id to
        # build a SigV4-signed WSS URL.
        ws_url, headers = self._client.generate_ws_headers()

        try:
            browser, context, page = _connect_playwright(ws_url, headers)
        except Exception:
            # Server-side session is live but Playwright failed to connect.
            # Best-effort cleanup to avoid an orphaned session on re-entry.
            try:
                self._client.stop()
            except Exception:
                logger.warning(
                    "Failed to stop AgentCore Browser session after Playwright "
                    "connect error (thread=%s); session may remain active server-side",
                    self.thread_id,
                )
            raise

        self._session = _Session(
            session_id=self._client.session_id,
            browser=browser,
            context=context,
            page=page,
            last_activity_s=time.monotonic(),
        )
        logger.info(
            "Browser session started session_id=%s thread=%s",
            self._session.session_id,
            self.thread_id,
        )

    def evict_if_idle(self) -> None:
        """Stop the session if it has been idle longer than idle_ttl_s."""
        with self._lock:
            if self._session is None:
                return
            idle_for = time.monotonic() - self._session.last_activity_s
            if idle_for >= self.idle_ttl_s:
                self._stop_locked()

    def stop(self) -> None:
        """Unconditionally stop the current session."""
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        """Stop the session; caller must hold self._lock."""
        if self._session is None:
            return
        try:
            self._client.stop()  # real SDK: stop() takes no args, uses instance state
        except Exception as exc:
            logger.warning("client.stop failed (continuing): %r", exc)
        self._session = None
