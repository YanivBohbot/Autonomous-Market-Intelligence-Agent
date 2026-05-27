# AgentCore Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Phase 8 — route the existing `browser_navigate` / `browser_snapshot` / `browser_take_screenshot` tools through Amazon Bedrock AgentCore Browser in production, while keeping the local `@playwright/mcp` path for dev.

**Architecture:** A custom Python stdio MCP server (inside `app/mcp/browser/`) wraps `bedrock_agentcore.tools.browser_client.BrowserClient` + Playwright and exposes three name-identical tools. Registry branches on `BROWSER_BACKEND=local|agentcore`. A new CDK `BrowserStack` provisions a Custom Browser Tool + S3 recording bucket + execution role. RuntimeStack gains 4 IAM actions and 3 new env vars.

**Tech Stack:** Python 3.12, FastMCP, `bedrock-agentcore` Python SDK, Playwright Python, AWS CDK (Python), boto3 / botocore.stub.Stubber, pytest, AWS Bedrock AgentCore Browser.

---

## File structure

Files this plan creates or modifies, with one-sentence purpose:

**Inside `market-intelligence-agent/` (cwd, shipped in the agent Docker image):**

| File | Purpose |
|---|---|
| `app/mcp/__init__.py` | New package marker. |
| `app/mcp/browser/__init__.py` | New package marker. |
| `app/mcp/browser/session_manager.py` | Per-process `BrowserSessionManager` — lazy-start, idle-TTL, auto-reconnect, signal-handler cleanup. Holds at most one AgentCore session keyed on `BROWSER_THREAD_ID` env. |
| `app/mcp/browser/server.py` | FastMCP stdio server. Exposes the 3 tools by name-identical contract, delegates to the session manager. |
| `app/agent/tools/mcp_clients/registry.py` | Add `BROWSER_BACKEND` branch in `_stdio_config()` and merge browser entry on top of gateway config in `_server_config()`. |
| `app/core/config.py` | Add `BROWSER_BACKEND`, `BROWSER_TOOL_ID`, `BROWSER_IDLE_TTL_S` settings. |
| `Dockerfile.agentcore` | Install `bedrock-agentcore` and `playwright` Python packages. No Chromium binary needed. |
| `tests/unit/test_browser_session_manager.py` | Unit tests for the session manager with boto3 stubbed and Playwright mocked. |
| `docs/TOOLS.md` | Note prod backend on the 3 browser entries. |
| `CLAUDE.md` | Document new env vars. |

**One level up at `../prod/` (CDK + CI):**

| File | Purpose |
|---|---|
| `prod/iac/stacks/browser_stack.py` | New stack — Custom Browser Tool (CfnCustomResource), S3 recording bucket, browser execution role. |
| `prod/iac/app.py` | Register `BrowserStack`; pass its outputs to `RuntimeStack`. |
| `prod/iac/stacks/runtime_stack.py` | IAM additions + 3 new env vars. |
| `prod/ci/probe_browser.py` | New live integration probe — navigate, snapshot, screenshot, recording-object check. |
| `prod/ci/qa_playground.py` | Add cases 19 (navigate→snapshot) and 20 (navigate→screenshot→write_file HITL). |
| `prod/STATE.md` | After cutover, add Browser ARN + recording bucket to the live-system snapshot. |

---

## Open verification points

Two interfaces in the spec are unverified — the implementer must confirm them during the relevant task and adapt the code if the API differs:

1. **`bedrock_agentcore.tools.browser_client.BrowserClient`** — exact import path and API surface (whether `start()` returns `(ws_url, headers)` or a Playwright connection object). Verify with `python -c "from bedrock_agentcore.tools.browser_client import BrowserClient; help(BrowserClient)"` in Task 1. Adjust Task 2 / Task 3 code accordingly.
2. **`AWS::BedrockAgentCore::Browser` CloudFormation resource** — whether a native L1 exists (`aws_cdk.aws_bedrockagentcore.CfnBrowser`). If yes, use it. If not, fall back to `cdk.CustomResource` calling `bedrock-agentcore-control:CreateBrowser`. Verify with `python -c "from aws_cdk import aws_bedrockagentcore as a; print([x for x in dir(a) if 'Browser' in x])"` in Task 6.

---

## Task 1: Add settings + verify SDK shape

**Files:**
- Modify: `market-intelligence-agent/app/core/config.py`
- Verify (no edit): SDK shape via REPL

- [ ] **Step 1: Install the AgentCore Python SDK in the dev venv**

```bash
uv add bedrock-agentcore playwright
uv run playwright install chromium  # dev only — prod uses managed Chromium
```

- [ ] **Step 2: Verify `BrowserClient` import path and surface**

```bash
uv run python -c "from bedrock_agentcore.tools.browser_client import BrowserClient; import inspect; print(inspect.signature(BrowserClient.__init__)); print([m for m in dir(BrowserClient) if not m.startswith('_')])"
```

Expected: prints `__init__` signature and at least one of `start`, `start_session`, `generate_ws_headers`. **Record the actual method names in a comment at the top of `app/mcp/browser/session_manager.py` when you create it in Task 2.** If the import fails, search PyPI for the current package name and update.

- [ ] **Step 3: Add three settings to `app/core/config.py`**

Find the `Settings` class in `app/core/config.py`. Add three fields next to the existing `WORKSPACE_ROOT` field, preserving the file's pydantic-settings style:

```python
    BROWSER_BACKEND: str = "local"  # "local" | "agentcore"
    BROWSER_TOOL_ID: str | None = None  # AgentCore Browser ARN, required when BROWSER_BACKEND=agentcore
    BROWSER_IDLE_TTL_S: int = 300
```

- [ ] **Step 4: Run config tests to confirm no regression**

```bash
uv run pytest tests/ -k config -v
```

Expected: PASS (or no matching tests; either is fine).

- [ ] **Step 5: Commit**

```bash
git add market-intelligence-agent/app/core/config.py market-intelligence-agent/pyproject.toml market-intelligence-agent/uv.lock
git commit -m "feat(browser): add BROWSER_BACKEND/BROWSER_TOOL_ID/BROWSER_IDLE_TTL_S settings + SDK deps"
```

---

## Task 2: Session manager — failing test for lazy start

**Files:**
- Create: `market-intelligence-agent/app/mcp/__init__.py` (empty)
- Create: `market-intelligence-agent/app/mcp/browser/__init__.py` (empty)
- Create: `market-intelligence-agent/app/mcp/browser/session_manager.py`
- Create: `market-intelligence-agent/tests/unit/test_browser_session_manager.py`

- [ ] **Step 1: Create the empty package markers**

```bash
mkdir -p market-intelligence-agent/app/mcp/browser
type nul > market-intelligence-agent/app/mcp/__init__.py
type nul > market-intelligence-agent/app/mcp/browser/__init__.py
```

(On a bash shell substitute `touch` for `type nul >`.)

- [ ] **Step 2: Write the failing test for lazy start**

Create `market-intelligence-agent/tests/unit/test_browser_session_manager.py`:

```python
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
    return MagicMock(name="BrowserClient")


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
        assert fake_browser_client.start_session.call_count == 1
        assert fake_connect.call_count == 1
```

- [ ] **Step 3: Run test, confirm it fails with ModuleNotFoundError**

```bash
cd market-intelligence-agent
uv run pytest tests/unit/test_browser_session_manager.py::test_lazy_start_calls_start_session_on_first_get_page -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.mcp.browser.session_manager'`.

- [ ] **Step 4: Write minimal `session_manager.py` to make the test pass**

Create `market-intelligence-agent/app/mcp/browser/session_manager.py`:

```python
"""Per-process AgentCore Browser session manager.

Holds at most one live AgentCore Browser session, lazily started on the first
get_page() call. Reuses the cached Playwright Page for the lifetime of the
session. Idle-TTL eviction and auto-reconnect are added in later tasks.

Verified SDK surface (Task 1):
  - BrowserClient(region_name=...).start_session(browser_identifier=..., session_timeout_seconds=...)
    -> dict with at least "sessionId" and a way to obtain the signed WS URL+headers
  - Adapt _connect_playwright if the SDK shape differs.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from bedrock_agentcore.tools.browser_client import BrowserClient  # type: ignore

logger = logging.getLogger(__name__)


def _connect_playwright(ws_url: str, headers: dict):
    """Connect Playwright over CDP and return (browser, context, page).

    Split into a module-level function so tests can monkeypatch it without
    touching the real playwright import (which would require a Chromium binary).
    """
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(ws_url, headers=headers)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.pages[0] if context.pages else context.new_page()
    return browser, context, page


@dataclass
class _Session:
    session_id: str
    browser: object
    context: object
    page: object
    last_activity_s: float


class BrowserSessionManager:
    def __init__(
        self, *, browser_arn: str, thread_id: str, idle_ttl_s: int = 300
    ) -> None:
        self.browser_arn = browser_arn
        self.thread_id = thread_id
        self.idle_ttl_s = idle_ttl_s
        self._client = BrowserClient(region_name=None)
        self._session: _Session | None = None
        self._lock = threading.Lock()

    def get_page(self):
        with self._lock:
            if self._session is None:
                self._start()
            self._session.last_activity_s = time.monotonic()  # type: ignore[union-attr]
            return self._session.page  # type: ignore[union-attr]

    def _start(self) -> None:
        resp = self._client.start_session(
            browser_identifier=self.browser_arn,
            session_timeout_seconds=1800,
        )
        ws_url = resp["wsUrl"]  # adjust if SDK uses different key (verify Task 1)
        headers = resp.get("headers", {})
        browser, context, page = _connect_playwright(ws_url, headers)
        self._session = _Session(
            session_id=resp["sessionId"],
            browser=browser,
            context=context,
            page=page,
            last_activity_s=time.monotonic(),
        )
        logger.info(
            "BrowserSessionManager started session=%s thread=%s",
            self._session.session_id,
            self.thread_id,
        )
```

- [ ] **Step 5: Run test, confirm PASS**

```bash
uv run pytest tests/unit/test_browser_session_manager.py::test_lazy_start_calls_start_session_on_first_get_page -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add market-intelligence-agent/app/mcp market-intelligence-agent/tests/unit/test_browser_session_manager.py
git commit -m "feat(browser): BrowserSessionManager lazy-start + first unit test"
```

---

## Task 3: Session manager — idle TTL eviction

**Files:**
- Modify: `market-intelligence-agent/app/mcp/browser/session_manager.py`
- Modify: `market-intelligence-agent/tests/unit/test_browser_session_manager.py`

- [ ] **Step 1: Add a failing test for idle eviction**

Append to `tests/unit/test_browser_session_manager.py`:

```python
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
            assert fake_browser_client.stop_session.call_count == 0

            clock["t"] = 1500.0  # 500s later — past TTL
            mgr.evict_if_idle()
            assert fake_browser_client.stop_session.call_count == 1

            mgr.get_page()  # forces session #2
            assert fake_browser_client.start_session.call_count == 2
```

- [ ] **Step 2: Run, confirm FAIL**

```bash
uv run pytest tests/unit/test_browser_session_manager.py::test_evict_if_idle_stops_session_past_ttl -v
```

Expected: FAIL with `AttributeError: 'BrowserSessionManager' object has no attribute 'evict_if_idle'`.

- [ ] **Step 3: Add `evict_if_idle` and `stop` methods**

Append inside the `BrowserSessionManager` class in `session_manager.py`:

```python
    def evict_if_idle(self) -> None:
        with self._lock:
            if self._session is None:
                return
            idle_for = time.monotonic() - self._session.last_activity_s
            if idle_for >= self.idle_ttl_s:
                self._stop_locked()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._session is None:
            return
        try:
            self._client.stop_session(
                browser_identifier=self.browser_arn,
                session_id=self._session.session_id,
            )
        except Exception as exc:  # best-effort; server-side TTL is the safety net
            logger.warning("stop_session failed (continuing): %r", exc)
        self._session = None
```

- [ ] **Step 4: Run, confirm PASS**

```bash
uv run pytest tests/unit/test_browser_session_manager.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add market-intelligence-agent/app/mcp/browser/session_manager.py market-intelligence-agent/tests/unit/test_browser_session_manager.py
git commit -m "feat(browser): idle-TTL eviction + stop() in BrowserSessionManager"
```

---

## Task 4: Session manager — auto-reconnect on mid-call disconnect

**Files:**
- Modify: `market-intelligence-agent/app/mcp/browser/session_manager.py`
- Modify: `market-intelligence-agent/tests/unit/test_browser_session_manager.py`

- [ ] **Step 1: Failing test for auto-reconnect**

Append to test file:

```python
def test_auto_reconnect_on_disconnect(fake_browser_client):
    """If the cached page raises ConnectionError on use, the manager must drop
    the session and restart on the next get_page() call. Up to 3 retries before
    surfacing the error."""
    from app.mcp.browser import session_manager as sm

    bad_page = MagicMock(name="DeadPage")
    bad_page.evaluate.side_effect = ConnectionError("ws closed")
    good_page = MagicMock(name="LivePage")

    with patch(
        "app.mcp.browser.session_manager.BrowserClient",
        return_value=fake_browser_client,
    ), patch(
        "app.mcp.browser.session_manager._connect_playwright",
        side_effect=[
            (MagicMock(), MagicMock(), bad_page),
            (MagicMock(), MagicMock(), good_page),
        ],
    ):
        mgr = sm.BrowserSessionManager(
            browser_arn="arn:1", thread_id="t1", idle_ttl_s=300,
        )

        def health_check(p):
            p.evaluate("1")  # raises on dead, returns on good

        result = mgr.with_retry(health_check, max_attempts=3)
        assert fake_browser_client.start_session.call_count == 2
        assert result is None  # health_check returned None on the live page
```

- [ ] **Step 2: Run, confirm FAIL**

```bash
uv run pytest tests/unit/test_browser_session_manager.py::test_auto_reconnect_on_disconnect -v
```

Expected: FAIL with `AttributeError: ... no attribute 'with_retry'`.

- [ ] **Step 3: Add `with_retry` to the manager**

Append inside `BrowserSessionManager`:

```python
    _RECONNECT_EXCEPTIONS = (ConnectionError, OSError)

    def with_retry(self, op, *, max_attempts: int = 3):
        """Run op(page); on ConnectionError/OSError, drop the session and retry.
        Raises the last exception if all attempts fail."""
        last: BaseException | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return op(self.get_page())
            except self._RECONNECT_EXCEPTIONS as exc:
                last = exc
                logger.warning(
                    "browser op failed (attempt %d/%d): %r", attempt, max_attempts, exc
                )
                with self._lock:
                    self._stop_locked()
        assert last is not None
        raise last
```

- [ ] **Step 4: Run, confirm PASS**

```bash
uv run pytest tests/unit/test_browser_session_manager.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add market-intelligence-agent/app/mcp/browser/session_manager.py market-intelligence-agent/tests/unit/test_browser_session_manager.py
git commit -m "feat(browser): with_retry auto-reconnect on disconnects"
```

---

## Task 5: FastMCP server exposing the 3 tools

**Files:**
- Create: `market-intelligence-agent/app/mcp/browser/server.py`
- Create: `market-intelligence-agent/tests/unit/test_browser_server.py`

- [ ] **Step 1: Failing tests for the 3 tool functions**

Create `market-intelligence-agent/tests/unit/test_browser_server.py`:

```python
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
```

- [ ] **Step 2: Run, confirm FAIL with ModuleNotFoundError**

```bash
uv run pytest tests/unit/test_browser_server.py -v
```

Expected: FAIL — server module not found.

- [ ] **Step 3: Implement `server.py`**

Create `market-intelligence-agent/app/mcp/browser/server.py`:

```python
"""Custom stdio MCP server: browser_navigate / browser_snapshot / browser_take_screenshot.

Same tool names, argument shapes, and return shapes as @playwright/mcp so the
LLM behaves identically in dev and prod. In prod the BrowserSessionManager
talks to Amazon Bedrock AgentCore Browser via the bedrock-agentcore Python SDK.

Spawn:
    BROWSER_TOOL_ID=<arn> BROWSER_THREAD_ID=<thread> \
        python -m app.mcp.browser.server
"""
from __future__ import annotations

import logging
import os
import signal
import sys
from functools import lru_cache
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.mcp.browser.session_manager import BrowserSessionManager

logger = logging.getLogger("app.mcp.browser.server")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

mcp = FastMCP("browser")


def _workspace_root() -> Path:
    return Path(os.environ.get("WORKSPACE_ROOT", "data/workspace")).resolve()


@lru_cache(maxsize=1)
def _manager() -> BrowserSessionManager:
    arn = os.environ["BROWSER_TOOL_ID"]
    thread_id = os.environ.get("BROWSER_THREAD_ID", "default")
    ttl = int(os.environ.get("BROWSER_IDLE_TTL_S", "300"))
    return BrowserSessionManager(browser_arn=arn, thread_id=thread_id, idle_ttl_s=ttl)


def _navigate_impl(url: str) -> str:
    def op(page):
        page.goto(url, timeout=30000)
        return f"Navigated to {url}"
    return _manager().with_retry(op)


def _snapshot_impl() -> str:
    def op(page):
        tree = page.accessibility.snapshot() or {}
        return _flatten(tree)
    return _manager().with_retry(op)


def _screenshot_impl(filename: str) -> str:
    rel = Path("screenshots") / Path(filename).name
    abs_path = _workspace_root() / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    def op(page):
        page.screenshot(path=str(abs_path), full_page=True)
        return str(rel).replace("\\", "/")
    return _manager().with_retry(op)


def _flatten(node: dict, depth: int = 0) -> str:
    role = node.get("role", "")
    name = node.get("name", "")
    line = f"{'  ' * depth}{role}: {name}".rstrip(": ")
    out = [line]
    for child in node.get("children", []) or []:
        out.append(_flatten(child, depth + 1))
    return "\n".join(out)


@mcp.tool()
def browser_navigate(url: str) -> str:
    """Navigate the persistent browser tab to a URL."""
    return _navigate_impl(url)


@mcp.tool()
def browser_snapshot() -> str:
    """Return the current page as a flattened accessibility tree."""
    return _snapshot_impl()


@mcp.tool()
def browser_take_screenshot(filename: str) -> str:
    """Save a PNG into workspace screenshots/ and return its workspace-relative path."""
    return _screenshot_impl(filename)


def _on_signal(signum, _frame):
    logger.info("signal %s received — stopping browser session", signum)
    try:
        _manager().stop()
    except Exception as exc:
        logger.warning("stop on signal failed: %r", exc)
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run server tests, confirm PASS**

```bash
uv run pytest tests/unit/test_browser_server.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Sanity-run the server module so a syntax/import error fails fast**

```bash
uv run python -c "from app.mcp.browser import server; print('ok')"
```

Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add market-intelligence-agent/app/mcp/browser/server.py market-intelligence-agent/tests/unit/test_browser_server.py
git commit -m "feat(browser): FastMCP stdio server exposing 3 tools"
```

---

## Task 6: Registry switch — wire BROWSER_BACKEND=agentcore

**Files:**
- Modify: `market-intelligence-agent/app/agent/tools/mcp_clients/registry.py`
- Modify: `market-intelligence-agent/tests/unit/test_browser_session_manager.py` (add an integration-shape test for the registry config)

- [ ] **Step 1: Write a failing test for the registry config branch**

Create `market-intelligence-agent/tests/unit/test_browser_registry.py`:

```python
"""Verify the registry adds a 'browser' stdio entry pointing at our custom
server when BROWSER_BACKEND=agentcore, regardless of MCP_TRANSPORT."""
from __future__ import annotations

from unittest.mock import patch


def test_browser_backend_agentcore_uses_custom_server(monkeypatch):
    monkeypatch.setenv("BROWSER_BACKEND", "agentcore")
    monkeypatch.setenv("BROWSER_TOOL_ID", "arn:aws:bedrock-agentcore:us-east-1:1:browser/foo")
    monkeypatch.setenv("MCP_TRANSPORT", "gateway")
    monkeypatch.setenv("AGENTCORE_GATEWAY_URL", "https://example.com/mcp")

    # Force re-read of settings cache
    from app.core import config as cfg
    cfg.settings = cfg.Settings()

    from app.agent.tools.mcp_clients import registry
    with patch.object(registry, "_fetch_gateway_oauth_token", return_value=None):
        cfg_dict = registry._server_config()

    assert "browser" in cfg_dict
    browser = cfg_dict["browser"]
    assert browser["transport"] == "stdio"
    assert browser["command"] in {"python", "uv"}
    args = " ".join(browser["args"])
    assert "app.mcp.browser.server" in args
    assert browser["env"]["BROWSER_TOOL_ID"].startswith("arn:aws:bedrock-agentcore")


def test_browser_backend_local_uses_playwright_mcp(monkeypatch):
    monkeypatch.setenv("BROWSER_BACKEND", "local")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    from app.core import config as cfg
    cfg.settings = cfg.Settings()
    from app.agent.tools.mcp_clients import registry

    cfg_dict = registry._server_config()
    assert cfg_dict["browser"]["command"] == "npx"
    assert "@playwright/mcp@latest" in " ".join(cfg_dict["browser"]["args"])
```

- [ ] **Step 2: Run, confirm FAIL**

```bash
uv run pytest tests/unit/test_browser_registry.py -v
```

Expected: both FAIL (first because `browser` key is missing under gateway transport; second because BROWSER_BACKEND logic does not exist yet).

- [ ] **Step 3: Add the BROWSER_BACKEND branch in `registry.py`**

In `app/agent/tools/mcp_clients/registry.py`:

(a) Extract the existing local browser dict-literal in `_stdio_config()` (lines 121-134) into a module-level helper. Replace those lines with a call:

```python
        "browser": _browser_entry(workspace_root),
```

(b) Define the helper just above `_stdio_config`:

```python
def _browser_entry(workspace_root) -> dict:
    """Return the 'browser' MCP server entry — local @playwright/mcp by default,
    custom AgentCore Browser MCP server when BROWSER_BACKEND=agentcore."""
    backend = (settings.BROWSER_BACKEND or "local").lower()
    if backend == "agentcore":
        if not settings.BROWSER_TOOL_ID:
            raise RuntimeError(
                "BROWSER_BACKEND=agentcore requires BROWSER_TOOL_ID to be set."
            )
        env = dict(os.environ)
        env["BROWSER_TOOL_ID"] = settings.BROWSER_TOOL_ID
        env["BROWSER_IDLE_TTL_S"] = str(settings.BROWSER_IDLE_TTL_S)
        # BROWSER_THREAD_ID is injected per-spawn by the runtime if multi-thread
        # isolation is wired; default "default" is fine for the single-thread path.
        env.setdefault("BROWSER_THREAD_ID", "default")
        return {
            "command": "python",
            "args": ["-m", "app.mcp.browser.server"],
            "transport": "stdio",
            "env": env,
            "cwd": str(workspace_root),
        }
    return {
        "command": "npx",
        "args": [
            "-y", "@playwright/mcp@latest",
            "--browser", "chromium",
            "--headless",
            "--output-dir", str(workspace_root / "screenshots"),
        ],
        "transport": "stdio",
        "env": dict(os.environ),
        "cwd": str(workspace_root),
    }
```

(c) In `_server_config()`, when transport == "gateway", **merge** the browser entry on top of the gateway config (browser is not a Gateway target; it always stays a stdio MCP server inside the container):

```python
    if transport == "gateway":
        workspace_root = settings.WORKSPACE_ROOT.resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "screenshots").mkdir(parents=True, exist_ok=True)
        cfg = _gateway_config()
        cfg["browser"] = _browser_entry(workspace_root)
        return cfg
```

- [ ] **Step 4: Run, confirm PASS**

```bash
uv run pytest tests/unit/test_browser_registry.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Make sure nothing else broke**

```bash
uv run pytest tests/ -v
```

Expected: all green (including pre-existing tests).

- [ ] **Step 6: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/mcp_clients/registry.py market-intelligence-agent/tests/unit/test_browser_registry.py
git commit -m "feat(browser): registry BROWSER_BACKEND switch, browser entry merged into gateway config"
```

---

## Task 7: Dockerfile.agentcore — install bedrock-agentcore + playwright

**Files:**
- Modify: `market-intelligence-agent/Dockerfile.agentcore`
- Modify: `market-intelligence-agent/requirements.agentcore.txt`

- [ ] **Step 1: Add packages to `requirements.agentcore.txt`**

Append:

```
bedrock-agentcore>=0.1.0
playwright>=1.46.0
```

- [ ] **Step 2: Confirm Dockerfile.agentcore picks up new deps**

Read `Dockerfile.agentcore`. If it does `pip install -r requirements.agentcore.txt`, no change needed. If it bakes a Chromium binary via `playwright install`, **remove that step** — managed Chromium runs in AgentCore Browser, not in the agent container.

- [ ] **Step 3: Local image-build smoke (optional but recommended)**

```bash
docker build -f market-intelligence-agent/Dockerfile.agentcore -t mia-agent-local market-intelligence-agent/
```

Expected: build succeeds. If it fails on the playwright install due to native deps, drop `playwright` from the prod requirements and instead pip-install a minimal subset (`playwright` pure-python — no system deps needed for `connect_over_cdp`-only usage). Verify with:

```bash
docker run --rm mia-agent-local python -c "from playwright.sync_api import sync_playwright; print('ok')"
```

- [ ] **Step 4: Commit**

```bash
git add market-intelligence-agent/Dockerfile.agentcore market-intelligence-agent/requirements.agentcore.txt
git commit -m "build(browser): include bedrock-agentcore + playwright in prod image"
```

---

## Task 8: CDK — BrowserStack (Custom Browser + S3 + execution role)

**Files:**
- Create: `prod/iac/stacks/browser_stack.py`
- Modify: `prod/iac/app.py`

- [ ] **Step 1: Verify CDK construct shape for AgentCore Browser**

```bash
uv run python -c "from aws_cdk import aws_bedrockagentcore as a; print([x for x in dir(a) if 'Browser' in x])"
```

If the list contains a `CfnBrowser` or `Browser` construct, use it. **If not**, fall back to `aws_cdk.CustomResource` calling `bedrock-agentcore-control:CreateBrowser` (the API is documented at the URL in spec §IAM detail). Record which path you took in a top-of-file comment in `browser_stack.py`.

- [ ] **Step 2: Write `browser_stack.py`**

Create `prod/iac/stacks/browser_stack.py`:

```python
"""BrowserStack — Amazon Bedrock AgentCore Custom Browser + recording bucket.

The system ARN `aws.browser.v1` does not support session recording, so we
provision a Custom Browser Tool with recording=ON pointed at a dedicated
S3 bucket (KMS-encrypted, 30-day lifecycle).

The browser execution role trusts bedrock-agentcore.amazonaws.com with
confused-deputy guards (SourceAccount + SourceArn).
"""
from __future__ import annotations

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from constructs import Construct

# If the L1/L2 construct exists, switch this import.
try:
    from aws_cdk import aws_bedrockagentcore as agentcore
    _HAS_NATIVE_CONSTRUCT = hasattr(agentcore, "CfnBrowser")
except ImportError:
    _HAS_NATIVE_CONSTRUCT = False


class MiaBrowserStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, project: str, env_name: str, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- KMS key for recording bucket ---
        key = kms.Key(
            self, "BrowserKey",
            description=f"{project}-{env_name} browser recordings",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- Recording bucket ---
        bucket = s3.Bucket(
            self, "BrowserRecordings",
            bucket_name=f"{project}-browser-recordings-{self.account}-{self.region}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=key,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-30d",
                    expiration=Duration.days(30),
                    abort_incomplete_multipart_upload_after=Duration.days(1),
                )
            ],
        )
        self.recording_bucket = bucket

        # --- Browser execution role ---
        exec_role = iam.Role(
            self, "BrowserExecRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:*"
                    },
                },
            ),
        )
        bucket.grant_write(exec_role)
        key.grant_encrypt(exec_role)
        self.exec_role = exec_role

        # --- Custom Browser ---
        if _HAS_NATIVE_CONSTRUCT:
            # NOTE: confirm exact property names against the construct in Task 8 step 1.
            browser = agentcore.CfnBrowser(  # type: ignore[attr-defined]
                self, "MiaBrowser",
                name=f"{project}_browser_{env_name}",
                network_configuration={"networkMode": "PUBLIC"},
                recording={
                    "enabled": True,
                    "s3Location": {"bucket": bucket.bucket_name, "prefix": "sessions/"},
                },
                execution_role_arn=exec_role.role_arn,
            )
            self.browser_arn = browser.attr_browser_arn
        else:
            # Fallback: CustomResource via AwsCustomResource calling
            # bedrock-agentcore-control:CreateBrowser. Build this in a follow-up
            # if the native construct is unavailable — keep the stack importable.
            from aws_cdk import custom_resources as cr
            cr_lambda = cr.AwsCustomResource(
                self, "CreateBrowser",
                on_create=cr.AwsSdkCall(
                    service="bedrock-agentcore-control",
                    action="createBrowser",
                    parameters={
                        "name": f"{project}_browser_{env_name}",
                        "networkConfiguration": {"networkMode": "PUBLIC"},
                        "recording": {
                            "enabled": True,
                            "s3Location": {
                                "bucket": bucket.bucket_name,
                                "prefix": "sessions/",
                            },
                        },
                        "executionRoleArn": exec_role.role_arn,
                    },
                    physical_resource_id=cr.PhysicalResourceId.from_response("browserId"),
                ),
                on_delete=cr.AwsSdkCall(
                    service="bedrock-agentcore-control",
                    action="deleteBrowser",
                    parameters={"browserIdentifier": cr.PhysicalResourceIdReference()},
                ),
                policy=cr.AwsCustomResourcePolicy.from_statements([
                    iam.PolicyStatement(
                        actions=[
                            "bedrock-agentcore:CreateBrowser",
                            "bedrock-agentcore:DeleteBrowser",
                            "iam:PassRole",
                        ],
                        resources=["*"],
                    )
                ]),
            )
            self.browser_arn = cr_lambda.get_response_field("browserArn")

        CfnOutput(
            self, "BrowserArn", value=self.browser_arn,
            export_name=f"{project}-{env_name}-browser-arn",
        )
        CfnOutput(
            self, "RecordingBucket", value=bucket.bucket_name,
            export_name=f"{project}-{env_name}-browser-bucket",
        )
```

- [ ] **Step 3: Register BrowserStack in `prod/iac/app.py`**

After the `secrets = MiaSecretsStack(...)` block, add:

```python
from stacks.browser_stack import MiaBrowserStack

browser = MiaBrowserStack(
    app, f"{PROJECT}-browser-{ENV_NAME}",
    project=PROJECT, env_name=ENV_NAME, env=env,
)
```

Then pass `browser=browser.browser_arn` to `MiaRuntimeStack(...)` (Task 9 wires it on the receiving side).

- [ ] **Step 4: Synth — must produce a valid template**

```bash
cd ../prod/iac
uv pip install -r requirements.txt   # if not already
cdk synth mia-browser-demo 2>&1 | tail -40
```

Expected: synth succeeds; output ends with `Successfully synthesized to ...`.

- [ ] **Step 5: Commit**

```bash
git add prod/iac/stacks/browser_stack.py prod/iac/app.py
git commit -m "iac(browser): MiaBrowserStack — Custom Browser + S3 recordings + exec role"
```

---

## Task 9: CDK — RuntimeStack IAM + env vars

**Files:**
- Modify: `prod/iac/stacks/runtime_stack.py`
- Modify: `prod/iac/app.py`

- [ ] **Step 1: Accept `browser_arn` in `MiaRuntimeStack`**

In `runtime_stack.py`, add to `__init__` signature after `gateway`:

```python
        browser_arn: str,
```

- [ ] **Step 2: Add IAM statement for AgentCore Browser**

After the existing `gateway.grant_invoke(role)` line, add:

```python
        # AgentCore Browser data-plane: start/stop/get sessions, plus the
        # ConnectBrowserAutomationStream WebSocket data-plane call.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:StartBrowserSession",
                    "bedrock-agentcore:StopBrowserSession",
                    "bedrock-agentcore:GetBrowserSession",
                    "bedrock-agentcore:ConnectBrowserAutomationStream",
                ],
                resources=[browser_arn],
            )
        )
```

- [ ] **Step 3: Add env vars on the Runtime**

Inside the `environment_variables={...}` dict, add:

```python
                "BROWSER_BACKEND": "agentcore",
                "BROWSER_TOOL_ID": browser_arn,
                "BROWSER_IDLE_TTL_S": "300",
```

- [ ] **Step 4: Wire it up in `prod/iac/app.py`**

Change the `MiaRuntimeStack(...)` call to pass `browser_arn=browser.browser_arn` and add `runtime.add_dependency(browser)`.

- [ ] **Step 5: Synth**

```bash
cd ../prod/iac
cdk synth mia-runtime-demo 2>&1 | tail -40
```

Expected: synth succeeds. Diff against the previous synth to confirm only the 3 env vars + 1 IAM statement changed.

- [ ] **Step 6: Commit**

```bash
git add prod/iac/stacks/runtime_stack.py prod/iac/app.py
git commit -m "iac(browser): wire BrowserStack outputs into RuntimeStack (IAM + env)"
```

---

## Task 10: Live integration probe

**Files:**
- Create: `prod/ci/probe_browser.py`

- [ ] **Step 1: Write the probe**

Create `prod/ci/probe_browser.py`:

```python
"""Live integration probe for AgentCore Browser.

Costs money. Run manually from a developer laptop with credentials for the
deployed environment. Not wired into push CI.

    uv run python prod/ci/probe_browser.py

Asserts:
    1. browser_navigate("https://example.com") succeeds.
    2. browser_snapshot() contains "Example Domain".
    3. browser_take_screenshot("evidence.png") writes the file.
    4. Within 60s of stop, the recording bucket has >=1 object under sessions/.
"""
from __future__ import annotations

import os
import sys
import time

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
RUNTIME_ARN = os.environ["MIA_RUNTIME_ARN"]
RECORDING_BUCKET = os.environ["MIA_BROWSER_BUCKET"]
SESSION_ID = f"probe-{int(time.time())}"


def invoke(prompt: str) -> dict:
    """Single-turn invoke of the runtime; same protocol as probe_playground.py."""
    client = boto3.client("bedrock-agentcore", region_name=REGION)
    body = {"query": prompt, "session_id": SESSION_ID}
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=f"probe-{int(time.time()*1000)}",
        payload=str(body).encode(),  # JSON shape matches probe_playground; adapt to that file's helper if different
    )
    raw = resp["response"].read().decode()
    print(raw[:400], "..." if len(raw) > 400 else "")
    return {"raw": raw}


def main() -> int:
    print("Step 1: navigate")
    invoke("Open https://example.com in the browser and confirm.")

    print("Step 2: snapshot — expect 'Example Domain' in answer")
    out = invoke("Take a browser_snapshot and tell me the page title.")
    assert "Example Domain" in out["raw"], "snapshot did not contain Example Domain"

    print("Step 3: screenshot")
    invoke("Take a browser_take_screenshot with filename 'probe-evidence.png' and confirm.")

    print("Step 4: recording — poll bucket up to 60s")
    s3 = boto3.client("s3", region_name=REGION)
    deadline = time.time() + 60
    found = 0
    while time.time() < deadline:
        resp = s3.list_objects_v2(Bucket=RECORDING_BUCKET, Prefix="sessions/")
        found = resp.get("KeyCount", 0)
        if found > 0:
            break
        time.sleep(5)
    assert found > 0, "no recording object appeared in the bucket within 60s"
    print(f"OK — {found} recording object(s) under sessions/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Commit (do not run live yet — deploy first)**

```bash
git add prod/ci/probe_browser.py
git commit -m "test(browser): live integration probe (run after deploy)"
```

---

## Task 11: QA cases 19 + 20

**Files:**
- Modify: `prod/ci/qa_playground.py`

- [ ] **Step 1: Read existing cases to match style**

```bash
head -80 ../prod/ci/qa_playground.py
```

- [ ] **Step 2: Add cases 19 and 20**

Locate the cases list/table in `qa_playground.py`. Append entries matching the existing style:

```python
# Case 19 — browser_navigate + browser_snapshot, read-only, no HITL
{
    "id": 19,
    "name": "browser_navigate_then_snapshot",
    "turns": [
        ("Open https://example.com and tell me the H1 text.", "completed"),
    ],
    "assert_contains": ["Example Domain"],
},

# Case 20 — browser_navigate -> screenshot -> write_file (HITL approve)
{
    "id": 20,
    "name": "browser_research_to_brief",
    "turns": [
        (
            "Open https://example.com, take a screenshot as 'evidence.png', "
            "then write a brief 'example_brief.md' that references the screenshot.",
            "interrupted",
        ),
        ("approve", "completed"),
    ],
    "assert_contains": ["evidence.png", "example_brief.md"],
},
```

(Adjust shape to match the actual list-of-dicts / list-of-tuples shape in the file.)

- [ ] **Step 3: Commit (live run happens at cutover)**

```bash
git add prod/ci/qa_playground.py
git commit -m "test(browser): QA cases 19 (snapshot) and 20 (HITL screenshot->brief)"
```

---

## Task 12: Cutover

This task is operational, not a code edit. Do not commit on this task — it produces the live deployment.

- [ ] **Step 1: Push master**

```bash
git push origin master
```

GitHub Actions OIDC pipeline deploys `mia-browser-demo` (first), then `mia-runtime-demo` (in dependency order). Wait for the workflow to be green.

- [ ] **Step 2: Capture outputs**

```bash
aws cloudformation describe-stacks --stack-name mia-browser-demo \
  --query "Stacks[0].Outputs" --output table
```

Note the `BrowserArn` and `RecordingBucket` values.

- [ ] **Step 3: Run the live probe**

```bash
export MIA_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-east-1:584246028688:runtime/mia_runtime_demo-tio2ELGaQB
export MIA_BROWSER_BUCKET=<from step 2>
uv run python prod/ci/probe_browser.py
```

Expected: 4 steps print OK; exits 0.

- [ ] **Step 4: Run grounded QA**

```bash
uv run python prod/ci/qa_playground.py
```

Expected: **20/20 passed.**

- [ ] **Step 5: If anything fails — rollback**

In `prod/iac/stacks/runtime_stack.py`, flip `"BROWSER_BACKEND": "agentcore"` to `"BROWSER_BACKEND": "local"`, push to master. The runtime container restarts using the dev backend (which will then fail at startup because there's no Chromium in the prod image — so this is really "roll back to the previous container tag via `cdk deploy` of the prior commit"). `BrowserStack` itself stays in place; idle cost ≈ $0/mo.

- [ ] **Step 6: Update `prod/STATE.md` (post-success)**

Add a row to the live-system snapshot:

```
| Custom Browser ARN | <from step 2> |
| Browser recording bucket | <from step 2> |
```

Commit:

```bash
git add prod/STATE.md
git commit -m "docs(state): record Custom Browser ARN + recording bucket after cutover"
git push origin master
```

---

## Task 13: Docs sync

**Files:**
- Modify: `market-intelligence-agent/docs/TOOLS.md`
- Modify: `market-intelligence-agent/CLAUDE.md`

- [ ] **Step 1: TOOLS.md — note prod backend on the 3 browser entries**

For each of `browser_navigate`, `browser_snapshot`, `browser_take_screenshot` in `docs/TOOLS.md`, append to the existing entry:

> **Production backend:** Amazon Bedrock AgentCore Browser via a custom stdio MCP server in `app/mcp/browser/`. Selected via `BROWSER_BACKEND=agentcore`. Dev uses `@playwright/mcp`. See `docs/superpowers/specs/2026-05-27-agentcore-browser-design.md`.

- [ ] **Step 2: CLAUDE.md — document env vars**

In the `## Required \`.env\` keys` section, add an "Optional with defaults" line for the 3 new vars:

```
BROWSER_BACKEND (local), BROWSER_TOOL_ID (none — required when BROWSER_BACKEND=agentcore), BROWSER_IDLE_TTL_S (300)
```

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/docs/TOOLS.md market-intelligence-agent/CLAUDE.md
git commit -m "docs(browser): note AgentCore Browser prod backend + env vars"
git push origin master
```

---

## Self-review notes

- **Spec coverage:** All 7 decisions in the spec map to tasks (1: T9 env; 2: T2–T6; 3: T5; 4: T1, T6; 5: T3, T4; 6: T8; 7: unchanged).
- **Placeholder scan:** None — every step has runnable commands and complete code.
- **Type consistency:** `BrowserSessionManager(browser_arn, thread_id, idle_ttl_s)` constant across T2/T3/T4/T6. Tool function names match the spec contract.
- **Known soft spots** flagged inline as "Open verification points": (a) exact `BrowserClient` method names/return-shape (T1, T2); (b) availability of native `CfnBrowser` construct (T8 step 1). The implementer must verify and adapt — do not invent shapes that aren't documented.
