# Browser Long-Lived MCP Transport — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make multi-step browser flows (e.g. `navigate(yahoo) → snapshot → navigate(news tab) → snapshot`) actually share tab/URL/cookie state across LangGraph tool calls.

**Architecture:** Switch the custom AgentCore Browser MCP server from **stdio (one subprocess per tool call)** to **streamable-HTTP (one long-lived process)**. The MCP server is launched by `entrypoint.py` as a sidecar subprocess on `127.0.0.1:8765` before uvicorn starts. The LangChain MCP client connects via `streamable_http` URL. The `@lru_cache _manager()` in `server.py` now actually persists across calls → the `BrowserSessionManager` keeps one AgentCore Browser session + one Playwright Page alive for the lifetime of the container (subject to idle TTL). Local dev with `BROWSER_BACKEND=local` (npx @playwright/mcp) stays on stdio — only the AgentCore branch switches.

**Tech Stack:** Python 3.12, FastMCP (`mcp.server.fastmcp`), `langchain-mcp-adapters` 0.1.0, `bedrock-agentcore` SDK, Playwright sync API, AWS AgentCore Runtime + AgentCore Browser (Custom).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `app/mcp/browser/server.py` | FastMCP entrypoint with the 3 browser tools. Add a `--transport http` mode that calls `mcp.run(transport="streamable-http", host, port)`. | Modify |
| `app/mcp/browser/lifecycle.py` | **NEW.** `start_browser_mcp_subprocess()` + `wait_until_ready()` + `stop()`. Spawns `python -m app.mcp.browser.server --transport http`, waits for the `/mcp` endpoint to respond, returns a handle the parent can `terminate()` on shutdown. | Create |
| `entrypoint.py` | Container entrypoint. Calls `lifecycle.start_browser_mcp_subprocess()` after secrets are resolved, waits for readiness, then execs uvicorn. SIGTERM handler stops the sidecar cleanly. | Modify |
| `app/agent/tools/mcp_clients/registry.py` | `_browser_entry()` returns `{"transport": "streamable_http", "url": "http://127.0.0.1:8765/mcp"}` when `BROWSER_BACKEND=agentcore` AND `BROWSER_MCP_TRANSPORT=http`. Defaults preserve local stdio behavior. | Modify |
| `app/core/config.py` | Add `BROWSER_MCP_TRANSPORT: str = "stdio"` + `BROWSER_MCP_HOST: str = "127.0.0.1"` + `BROWSER_MCP_PORT: int = 8765` settings. | Modify |
| `tests/mcp/browser/test_server_http.py` | **NEW.** Unit test: starting the server in HTTP mode binds the port and serves `/mcp`. | Create |
| `tests/mcp/browser/test_lifecycle.py` | **NEW.** Unit test: `start_browser_mcp_subprocess()` returns a handle, `wait_until_ready()` succeeds, `stop()` reaps the child. | Create |
| `tests/mcp/browser/test_registry_http_entry.py` | **NEW.** Unit test: `_browser_entry()` returns the HTTP config when env vars are set; stdio otherwise. | Create |
| `prod/iac/stacks/runtime_stack.py` | Add `BROWSER_MCP_TRANSPORT=http`, `BROWSER_MCP_HOST=127.0.0.1`, `BROWSER_MCP_PORT=8765` to the Runtime container env block (AgentCore Browser branch only). | Modify |
| `prod/ci/probe_browser_multistep.py` | **NEW.** Live integration test against the deployed runtime: navigate to a real market site, snapshot, navigate to a second URL in the same flow, snapshot again, assert the second snapshot reflects the second URL (state was preserved). | Create |
| `prod/STATE.md` | Remove the "Known v1 limitation — cross-call tab state" block. Note new env vars. | Modify |
| `market-intelligence-agent/CLAUDE.md` | Update browser tool section to mention the HTTP sidecar in prod. | Modify |

---

## Task 1: Add HTTP transport mode to the browser MCP server

**Files:**
- Modify: `app/mcp/browser/server.py:117-124` (the `main()` function)
- Test: `tests/mcp/browser/test_server_http.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/browser/test_server_http.py
"""HTTP-transport mode for the browser MCP server.

We don't drive a full FastMCP run loop in unit tests (it would need a live
AgentCore Browser session); we only assert main() routes --transport http to
the right FastMCP method. The real exercise lives in probe_browser_multistep.py.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def test_main_stdio_calls_run():
    from app.mcp.browser import server
    with patch.object(server, "mcp") as mock_mcp, \
         patch.object(server.signal, "signal"):
        server.main(argv=["server"])
        mock_mcp.run.assert_called_once_with()
        mock_mcp.run_streamable_http_async.assert_not_called()


def test_main_http_passes_host_and_port(monkeypatch):
    from app.mcp.browser import server
    monkeypatch.setenv("BROWSER_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("BROWSER_MCP_PORT", "8765")
    with patch.object(server, "mcp") as mock_mcp, \
         patch.object(server.signal, "signal"):
        server.main(argv=["server", "--transport", "http"])
        mock_mcp.run.assert_called_once_with(
            transport="streamable-http",
            host="127.0.0.1",
            port=8765,
        )


def test_main_http_unknown_arg_raises():
    from app.mcp.browser import server
    with pytest.raises(SystemExit):
        server.main(argv=["server", "--transport", "bogus"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd market-intelligence-agent && uv run pytest tests/mcp/browser/test_server_http.py -v`
Expected: FAIL — `main()` currently takes no `argv` parameter and doesn't accept `--transport`.

- [ ] **Step 3: Modify `server.py` to support `--transport http`**

Replace the existing `def main() -> None:` at the bottom of `app/mcp/browser/server.py` with:

```python
import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.mcp.browser.server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="MCP transport. 'stdio' (default) = one subprocess per tool call. "
             "'http' = long-lived streamable-HTTP server bound to "
             "BROWSER_MCP_HOST:BROWSER_MCP_PORT (default 127.0.0.1:8765).",
    )
    args = parser.parse_args(argv[1:] if argv else None)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    if args.transport == "http":
        host = os.environ.get("BROWSER_MCP_HOST", "127.0.0.1")
        port = int(os.environ.get("BROWSER_MCP_PORT", "8765"))
        logger.info("starting browser MCP server transport=http host=%s port=%d", host, port)
        mcp.run(transport="streamable-http", host=host, port=port)
        return

    logger.info("starting browser MCP server transport=stdio")
    mcp.run()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd market-intelligence-agent && uv run pytest tests/mcp/browser/test_server_http.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add market-intelligence-agent/app/mcp/browser/server.py market-intelligence-agent/tests/mcp/browser/test_server_http.py
git commit -m "feat(browser): --transport http mode for long-lived MCP server"
```

---

## Task 2: Add config settings for the HTTP transport

**Files:**
- Modify: `app/core/config.py` (add 3 fields)
- Test: `tests/core/test_config_browser_mcp.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_config_browser_mcp.py
from app.core.config import Settings


def test_browser_mcp_defaults():
    s = Settings()
    assert s.BROWSER_MCP_TRANSPORT == "stdio"
    assert s.BROWSER_MCP_HOST == "127.0.0.1"
    assert s.BROWSER_MCP_PORT == 8765


def test_browser_mcp_env_override(monkeypatch):
    monkeypatch.setenv("BROWSER_MCP_TRANSPORT", "http")
    monkeypatch.setenv("BROWSER_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("BROWSER_MCP_PORT", "9000")
    s = Settings()
    assert s.BROWSER_MCP_TRANSPORT == "http"
    assert s.BROWSER_MCP_HOST == "0.0.0.0"
    assert s.BROWSER_MCP_PORT == 9000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd market-intelligence-agent && uv run pytest tests/core/test_config_browser_mcp.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'BROWSER_MCP_TRANSPORT'`.

- [ ] **Step 3: Add the fields to `Settings`**

Find the existing `BROWSER_BACKEND`/`BROWSER_TOOL_ID`/`BROWSER_IDLE_TTL_S` block in `app/core/config.py` and append immediately after:

```python
    # Browser MCP transport (only meaningful when BROWSER_BACKEND=agentcore):
    # 'stdio' (default, dev) spawns one process per tool call.
    # 'http' runs a single long-lived FastMCP server bound to HOST:PORT
    # so the BrowserSessionManager (and thus the AgentCore Browser session)
    # is reused across tool calls — required for multi-step browser flows.
    BROWSER_MCP_TRANSPORT: str = "stdio"
    BROWSER_MCP_HOST: str = "127.0.0.1"
    BROWSER_MCP_PORT: int = 8765
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd market-intelligence-agent && uv run pytest tests/core/test_config_browser_mcp.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add market-intelligence-agent/app/core/config.py market-intelligence-agent/tests/core/test_config_browser_mcp.py
git commit -m "feat(config): BROWSER_MCP_TRANSPORT/HOST/PORT settings"
```

---

## Task 3: Sidecar lifecycle helper

**Files:**
- Create: `app/mcp/browser/lifecycle.py`
- Test: `tests/mcp/browser/test_lifecycle.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/browser/test_lifecycle.py
"""Lifecycle of the browser MCP HTTP sidecar.

We don't actually start Playwright here — we patch subprocess.Popen and
httpx so the test runs in <1s and doesn't need AWS creds.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import httpx
import pytest

from app.mcp.browser import lifecycle


def test_start_sets_command_and_env(monkeypatch):
    monkeypatch.setenv("BROWSER_TOOL_ID", "browser-arn-id")
    fake_proc = MagicMock(pid=42)
    with patch.object(lifecycle.subprocess, "Popen", return_value=fake_proc) as p_open:
        handle = lifecycle.start_browser_mcp_subprocess(
            host="127.0.0.1", port=8765,
        )
    call = p_open.call_args
    assert call.args[0][:4] == ["python", "-m", "app.mcp.browser.server", "--transport"]
    assert call.args[0][-1] == "http"
    env = call.kwargs["env"]
    assert env["BROWSER_MCP_HOST"] == "127.0.0.1"
    assert env["BROWSER_MCP_PORT"] == "8765"
    assert env["BROWSER_TOOL_ID"] == "browser-arn-id"
    assert handle.process is fake_proc


def test_wait_until_ready_polls_then_succeeds():
    handle = lifecycle.SidecarHandle(process=MagicMock(poll=lambda: None), host="127.0.0.1", port=8765)
    responses = [httpx.ConnectError("not yet"), MagicMock(status_code=200)]
    def fake_get(*a, **kw):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    with patch.object(httpx, "get", side_effect=fake_get):
        lifecycle.wait_until_ready(handle, timeout_s=2.0, interval_s=0.01)


def test_wait_until_ready_raises_if_process_died():
    dead = MagicMock(poll=lambda: 1)  # non-None = exited
    handle = lifecycle.SidecarHandle(process=dead, host="127.0.0.1", port=8765)
    with pytest.raises(RuntimeError, match="browser MCP sidecar exited"):
        lifecycle.wait_until_ready(handle, timeout_s=0.1, interval_s=0.01)


def test_wait_until_ready_times_out():
    alive = MagicMock(poll=lambda: None)
    handle = lifecycle.SidecarHandle(process=alive, host="127.0.0.1", port=8765)
    with patch.object(httpx, "get", side_effect=httpx.ConnectError("nope")):
        with pytest.raises(TimeoutError):
            lifecycle.wait_until_ready(handle, timeout_s=0.05, interval_s=0.01)


def test_stop_terminates_then_kills():
    proc = MagicMock()
    proc.wait.side_effect = [None]  # graceful exit
    handle = lifecycle.SidecarHandle(process=proc, host="127.0.0.1", port=8765)
    lifecycle.stop(handle, grace_s=0.01)
    proc.terminate.assert_called_once()
    proc.kill.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd market-intelligence-agent && uv run pytest tests/mcp/browser/test_lifecycle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.mcp.browser.lifecycle'`.

- [ ] **Step 3: Create `app/mcp/browser/lifecycle.py`**

```python
"""Launch and supervise the browser MCP HTTP sidecar from inside the container.

The sidecar is `python -m app.mcp.browser.server --transport http` bound to
127.0.0.1:8765 by default. The parent process (entrypoint.py) calls
start_browser_mcp_subprocess() before uvicorn starts, then wait_until_ready()
blocks until /mcp answers a GET (or until the child dies / a timeout hits).
On SIGTERM the parent calls stop() to drain the child cleanly so any open
AgentCore Browser session is stopped instead of leaking.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class SidecarHandle:
    process: subprocess.Popen
    host: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/mcp"


def start_browser_mcp_subprocess(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    python_executable: Optional[str] = None,
) -> SidecarHandle:
    """Spawn the browser MCP server as a child process.

    Inherits the parent's env (so BROWSER_TOOL_ID, AWS_REGION, etc. propagate),
    overlays BROWSER_MCP_HOST/PORT, and pipes stdout/stderr to the parent's
    streams so CloudWatch captures sidecar logs alongside FastAPI logs.
    """
    env = dict(os.environ)
    env["BROWSER_MCP_HOST"] = host
    env["BROWSER_MCP_PORT"] = str(port)
    cmd = [
        python_executable or sys.executable,
        "-m",
        "app.mcp.browser.server",
        "--transport",
        "http",
    ]
    logger.info("starting browser MCP sidecar: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    return SidecarHandle(process=proc, host=host, port=port)


def wait_until_ready(
    handle: SidecarHandle,
    *,
    timeout_s: float = 30.0,
    interval_s: float = 0.5,
) -> None:
    """Poll the sidecar's /mcp endpoint until it answers OR raise.

    Raises RuntimeError if the child process exits before becoming ready.
    Raises TimeoutError if neither happens within timeout_s.
    """
    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        rc = handle.process.poll()
        if rc is not None:
            raise RuntimeError(
                f"browser MCP sidecar exited before ready (rc={rc}); "
                "check container logs for the child's traceback."
            )
        try:
            # streamable-http exposes /mcp; any response (even 4xx) proves
            # the server is listening. We don't assert status — FastMCP may
            # return 4xx for an empty GET, that's fine.
            httpx.get(handle.url, timeout=1.0)
            logger.info("browser MCP sidecar ready at %s", handle.url)
            return
        except httpx.HTTPError as exc:
            last_exc = exc
            time.sleep(interval_s)
    raise TimeoutError(
        f"browser MCP sidecar not ready after {timeout_s}s "
        f"(last error: {last_exc!r})"
    )


def stop(handle: SidecarHandle, *, grace_s: float = 5.0) -> None:
    """Send SIGTERM, wait grace_s, escalate to SIGKILL if still alive."""
    if handle.process.poll() is not None:
        return
    logger.info("stopping browser MCP sidecar pid=%d", handle.process.pid)
    handle.process.terminate()
    try:
        handle.process.wait(timeout=grace_s)
        return
    except subprocess.TimeoutExpired:
        logger.warning(
            "sidecar pid=%d did not exit after %ss SIGTERM; sending SIGKILL",
            handle.process.pid, grace_s,
        )
        handle.process.kill()
        handle.process.wait(timeout=2.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd market-intelligence-agent && uv run pytest tests/mcp/browser/test_lifecycle.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add market-intelligence-agent/app/mcp/browser/lifecycle.py market-intelligence-agent/tests/mcp/browser/test_lifecycle.py
git commit -m "feat(browser): sidecar lifecycle (start, wait_until_ready, stop)"
```

---

## Task 4: Boot the sidecar from `entrypoint.py`

**Files:**
- Modify: `entrypoint.py`
- Test: `tests/test_entrypoint_browser_sidecar.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_entrypoint_browser_sidecar.py
"""entrypoint.py should boot the browser MCP sidecar before uvicorn
ONLY when BROWSER_BACKEND=agentcore AND BROWSER_MCP_TRANSPORT=http."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import entrypoint


def test_no_sidecar_when_backend_local(monkeypatch):
    monkeypatch.setenv("BROWSER_BACKEND", "local")
    monkeypatch.setenv("BROWSER_MCP_TRANSPORT", "http")
    with patch.object(entrypoint, "_resolve_secrets"), \
         patch("app.mcp.browser.lifecycle.start_browser_mcp_subprocess") as start, \
         patch("uvicorn.run"):
        entrypoint.main()
    start.assert_not_called()


def test_no_sidecar_when_transport_stdio(monkeypatch):
    monkeypatch.setenv("BROWSER_BACKEND", "agentcore")
    monkeypatch.setenv("BROWSER_MCP_TRANSPORT", "stdio")
    with patch.object(entrypoint, "_resolve_secrets"), \
         patch("app.mcp.browser.lifecycle.start_browser_mcp_subprocess") as start, \
         patch("uvicorn.run"):
        entrypoint.main()
    start.assert_not_called()


def test_sidecar_starts_when_agentcore_http(monkeypatch):
    monkeypatch.setenv("BROWSER_BACKEND", "agentcore")
    monkeypatch.setenv("BROWSER_MCP_TRANSPORT", "http")
    monkeypatch.setenv("BROWSER_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("BROWSER_MCP_PORT", "8765")
    fake_handle = MagicMock()
    with patch.object(entrypoint, "_resolve_secrets"), \
         patch("app.mcp.browser.lifecycle.start_browser_mcp_subprocess",
               return_value=fake_handle) as start, \
         patch("app.mcp.browser.lifecycle.wait_until_ready") as ready, \
         patch("uvicorn.run") as uv:
        entrypoint.main()
    start.assert_called_once_with(host="127.0.0.1", port=8765)
    ready.assert_called_once_with(fake_handle, timeout_s=30.0)
    uv.assert_called_once()


def test_sidecar_failure_aborts_uvicorn(monkeypatch):
    monkeypatch.setenv("BROWSER_BACKEND", "agentcore")
    monkeypatch.setenv("BROWSER_MCP_TRANSPORT", "http")
    with patch.object(entrypoint, "_resolve_secrets"), \
         patch("app.mcp.browser.lifecycle.start_browser_mcp_subprocess"), \
         patch("app.mcp.browser.lifecycle.wait_until_ready",
               side_effect=RuntimeError("boom")), \
         patch("uvicorn.run") as uv:
        import pytest
        with pytest.raises(RuntimeError, match="boom"):
            entrypoint.main()
    uv.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd market-intelligence-agent && uv run pytest tests/test_entrypoint_browser_sidecar.py -v`
Expected: FAIL — entrypoint doesn't import lifecycle yet.

- [ ] **Step 3: Modify `entrypoint.py`**

Replace `def main()` with:

```python
import atexit
import signal


def _should_start_browser_sidecar() -> bool:
    return (
        os.environ.get("BROWSER_BACKEND", "").lower() == "agentcore"
        and os.environ.get("BROWSER_MCP_TRANSPORT", "stdio").lower() == "http"
    )


def main() -> None:
    _resolve_secrets()

    sidecar_handle = None
    if _should_start_browser_sidecar():
        from app.mcp.browser import lifecycle
        host = os.environ.get("BROWSER_MCP_HOST", "127.0.0.1")
        port = int(os.environ.get("BROWSER_MCP_PORT", "8765"))
        sidecar_handle = lifecycle.start_browser_mcp_subprocess(host=host, port=port)
        lifecycle.wait_until_ready(sidecar_handle, timeout_s=30.0)

        # Make sure SIGTERM from AgentCore propagates to the sidecar so the
        # AgentCore Browser session is stopped server-side instead of leaking.
        def _shutdown(signum, _frame):
            logger.info("entrypoint received signal %s — stopping sidecar", signum)
            lifecycle.stop(sidecar_handle)
            sys.exit(0)

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)
        atexit.register(lifecycle.stop, sidecar_handle)

    import uvicorn  # late import — Settings instantiation depends on env being set
    uvicorn.run(
        "app.api.server:app",
        host="0.0.0.0",
        port=8080,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd market-intelligence-agent && uv run pytest tests/test_entrypoint_browser_sidecar.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add market-intelligence-agent/entrypoint.py market-intelligence-agent/tests/test_entrypoint_browser_sidecar.py
git commit -m "feat(runtime): boot browser MCP HTTP sidecar before uvicorn"
```

---

## Task 5: Switch the registry to HTTP when configured

**Files:**
- Modify: `app/agent/tools/mcp_clients/registry.py:92-131` (the `_browser_entry` function)
- Test: `tests/mcp_clients/test_registry_http_entry.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp_clients/test_registry_http_entry.py
"""_browser_entry should return an HTTP client config when
BROWSER_BACKEND=agentcore AND BROWSER_MCP_TRANSPORT=http."""
from __future__ import annotations

from pathlib import Path

from app.agent.tools.mcp_clients import registry


def test_browser_entry_stdio_local(monkeypatch, tmp_path):
    monkeypatch.setattr(registry.settings, "BROWSER_BACKEND", "local")
    entry = registry._browser_entry(tmp_path)
    assert entry["transport"] == "stdio"
    assert entry["command"] == "npx"


def test_browser_entry_stdio_agentcore_default(monkeypatch, tmp_path):
    monkeypatch.setattr(registry.settings, "BROWSER_BACKEND", "agentcore")
    monkeypatch.setattr(registry.settings, "BROWSER_TOOL_ID", "arn:x")
    monkeypatch.setattr(registry.settings, "BROWSER_MCP_TRANSPORT", "stdio")
    entry = registry._browser_entry(tmp_path)
    assert entry["transport"] == "stdio"
    assert entry["args"] == ["-m", "app.mcp.browser.server"]


def test_browser_entry_http_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(registry.settings, "BROWSER_BACKEND", "agentcore")
    monkeypatch.setattr(registry.settings, "BROWSER_TOOL_ID", "arn:x")
    monkeypatch.setattr(registry.settings, "BROWSER_MCP_TRANSPORT", "http")
    monkeypatch.setattr(registry.settings, "BROWSER_MCP_HOST", "127.0.0.1")
    monkeypatch.setattr(registry.settings, "BROWSER_MCP_PORT", 8765)
    entry = registry._browser_entry(tmp_path)
    assert entry == {
        "transport": "streamable_http",
        "url": "http://127.0.0.1:8765/mcp",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd market-intelligence-agent && uv run pytest tests/mcp_clients/test_registry_http_entry.py -v`
Expected: FAIL — third test fails because `_browser_entry` ignores `BROWSER_MCP_TRANSPORT`.

- [ ] **Step 3: Modify `_browser_entry()` in `app/agent/tools/mcp_clients/registry.py`**

Replace the existing function body. The first `if backend == "agentcore":` block needs an inner branch on transport:

```python
def _browser_entry(workspace_root) -> dict:
    """Return the 'browser' MCP server entry.

    Three modes:
      - BROWSER_BACKEND=local (default): npx @playwright/mcp via stdio.
      - BROWSER_BACKEND=agentcore + BROWSER_MCP_TRANSPORT=stdio: our custom
        FastMCP server via stdio — one subprocess per tool call, no shared
        state across calls.
      - BROWSER_BACKEND=agentcore + BROWSER_MCP_TRANSPORT=http: our custom
        FastMCP server reached over streamable-HTTP at
        BROWSER_MCP_HOST:BROWSER_MCP_PORT. The sidecar process is started by
        entrypoint.py before this client is constructed; it keeps a single
        AgentCore Browser session alive so multi-step browser flows share
        tab/URL/cookie state. THIS is the prod path.
    """
    backend = (settings.BROWSER_BACKEND or "local").lower()
    if backend == "agentcore":
        if not settings.BROWSER_TOOL_ID:
            raise RuntimeError(
                "BROWSER_BACKEND=agentcore requires BROWSER_TOOL_ID to be set."
            )
        transport = (settings.BROWSER_MCP_TRANSPORT or "stdio").lower()
        if transport == "http":
            url = f"http://{settings.BROWSER_MCP_HOST}:{settings.BROWSER_MCP_PORT}/mcp"
            return {"transport": "streamable_http", "url": url}
        # stdio fallback (legacy / unit-test convenience)
        env = dict(os.environ)
        env["BROWSER_TOOL_ID"] = settings.BROWSER_TOOL_ID
        env["BROWSER_IDLE_TTL_S"] = str(settings.BROWSER_IDLE_TTL_S)
        env.setdefault("BROWSER_THREAD_ID", "default")
        return {
            "command": "python",
            "args": ["-m", "app.mcp.browser.server"],
            "transport": "stdio",
            "env": env,
            "cwd": str(workspace_root),
        }
    # local (default): Playwright MCP via npx
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd market-intelligence-agent && uv run pytest tests/mcp_clients/test_registry_http_entry.py -v`
Expected: 3 passed.

- [ ] **Step 5: Make sure existing registry tests still pass**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v -k "registry or mcp_client" --timeout 30`
Expected: All pre-existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/mcp_clients/registry.py market-intelligence-agent/tests/mcp_clients/test_registry_http_entry.py
git commit -m "feat(browser): wire streamable_http transport in MCP client registry"
```

---

## Task 6: Push the new env vars from CDK to the Runtime container

**Files:**
- Modify: `prod/iac/stacks/runtime_stack.py` (env block)

- [ ] **Step 1: Read current env block**

Run: `grep -n "BROWSER" prod/iac/stacks/runtime_stack.py`
Note the line numbers where the existing `BROWSER_BACKEND` / `BROWSER_TOOL_ID` env vars are injected.

- [ ] **Step 2: Add the 3 new env vars**

Add to the same env dict the runtime stack assembles for the container:

```python
"BROWSER_MCP_TRANSPORT": "http",
"BROWSER_MCP_HOST": "127.0.0.1",
"BROWSER_MCP_PORT": "8765",
```

(Adjacent to the existing `BROWSER_BACKEND`, `BROWSER_TOOL_ID`, `BROWSER_IDLE_TTL_S` entries. Keep them grouped.)

- [ ] **Step 3: cdk synth to confirm the template builds**

Run: `cd prod/iac && uv run cdk synth mia-runtime-demo > /tmp/synth.yaml 2>&1 && grep -A2 BROWSER_MCP /tmp/synth.yaml | head -15`
Expected: the three new env vars appear in the CloudFormation template.

- [ ] **Step 4: Commit**

```bash
git add prod/iac/stacks/runtime_stack.py
git commit -m "iac(runtime): propagate BROWSER_MCP_TRANSPORT/HOST/PORT to container"
```

---

## Task 7: Live integration test — multi-step browser flow on a real site

**Files:**
- Create: `prod/ci/probe_browser_multistep.py`

- [ ] **Step 1: Write the probe script**

```python
# prod/ci/probe_browser_multistep.py
"""Live test: prove the AgentCore Browser session persists across tool calls.

Invokes the deployed AgentCore Runtime with a sticky body.session_id so the
durable checkpointer keeps state, then drives:
  turn 1: navigate to Yahoo Finance NVDA quote page
  turn 2: snapshot — must mention "NVIDIA" (proves page state survived)
  turn 3: navigate to the same site's News tab
  turn 4: snapshot — must contain news-y wording, not the quote page wording

Exits 0 on success, non-zero on failure. Designed to be cheap (4 turns) so it
can run on every deploy.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import boto3

RUNTIME_ARN = os.environ.get(
    "MIA_RUNTIME_ARN",
    "arn:aws:bedrock-agentcore:us-east-1:584246028688:runtime/mia_runtime_demo-tio2ELGaQB",
)
REGION = os.environ.get("AWS_REGION", "us-east-1")
SESSION_ID = f"probe-browser-multistep-{uuid.uuid4().hex[:8]}"

CLIENT = boto3.client("bedrock-agentcore", region_name=REGION)


def invoke(prompt: str) -> dict:
    """Single turn against the runtime. Fresh runtimeSessionId, sticky body.session_id."""
    resp = CLIENT.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=uuid.uuid4().hex,  # console-UI-like: fresh per call
        payload=json.dumps({"prompt": prompt, "session_id": SESSION_ID}).encode(),
    )
    body = b"".join(chunk for chunk in resp["response"].iter_chunks())
    return json.loads(body)


def assert_contains(haystack: str, needle: str, case_label: str) -> None:
    if needle.lower() not in haystack.lower():
        print(f"FAIL [{case_label}]: response did not contain {needle!r}")
        print(f"  response was: {haystack[:400]!r}")
        sys.exit(1)
    print(f"PASS [{case_label}]: response contained {needle!r}")


def main() -> None:
    print(f"session_id={SESSION_ID}")

    # Turn 1: navigate to Yahoo Finance NVDA. The agent will call browser_navigate.
    r = invoke("Navigate the browser to https://finance.yahoo.com/quote/NVDA — just navigate, don't summarize yet.")
    assert r.get("status") == "completed", f"turn 1 not completed: {r}"
    print("turn 1 OK (navigate to NVDA quote)")

    # Turn 2: snapshot the SAME tab. If session was lost, snapshot will return
    # blank/about:blank text. If it persisted, we expect 'NVIDIA' somewhere.
    r = invoke("Take a snapshot of the current page and tell me what stock is shown.")
    assert r.get("status") == "completed", f"turn 2 not completed: {r}"
    assert_contains(r.get("response", ""), "NVIDIA", "turn 2 / state preserved across calls")

    # Turn 3: navigate to a different URL (News tab on same site) in the SAME session.
    r = invoke("Now navigate the browser to https://finance.yahoo.com/quote/NVDA/news")
    assert r.get("status") == "completed", f"turn 3 not completed: {r}"
    print("turn 3 OK (navigate to news)")

    # Turn 4: snapshot — must look like a news page, not the quote page.
    r = invoke("Snapshot the current page and list 2 news headlines you see.")
    assert r.get("status") == "completed", f"turn 4 not completed: {r}"
    text = r.get("response", "").lower()
    if "news" not in text and "headline" not in text and "article" not in text:
        print(f"FAIL [turn 4 / news page]: response had no news-y wording")
        print(f"  response was: {text[:400]!r}")
        sys.exit(1)
    print("PASS [turn 4]: response references news/headline/article")

    print("\nALL PASS — browser session persists across multi-step tool calls.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit (probe runs only after deploy)**

```bash
git add prod/ci/probe_browser_multistep.py
git commit -m "test(browser): live multi-step probe against deployed runtime"
```

---

## Task 8: Deploy and verify live

- [ ] **Step 1: Push to master to trigger the GH Actions OIDC pipeline**

```bash
git push origin master
```

- [ ] **Step 2: Watch the deploy**

Run: `gh run watch` (or check the Actions tab in the GitHub UI)
Expected: deploy succeeds; `mia-runtime-demo` stack updates with the 3 new env vars.

- [ ] **Step 3: Run the multi-step probe**

Run: `python prod/ci/probe_browser_multistep.py`
Expected output:
```
session_id=probe-browser-multistep-xxxxxxxx
turn 1 OK (navigate to NVDA quote)
PASS [turn 2 / state preserved across calls]: response contained 'NVIDIA'
turn 3 OK (navigate to news)
PASS [turn 4]: response references news/headline/article

ALL PASS — browser session persists across multi-step tool calls.
```

- [ ] **Step 4: Run the existing playground QA suite — must not regress**

Run: `python prod/ci/qa_playground.py`
Expected: 18/18 pass (no regression on single-call tools).

- [ ] **Step 5: Optional — confirm session reuse in CloudWatch**

Run: `aws logs tail /aws/bedrock-agentcore/runtimes/mia_runtime_demo-tio2ELGaQB-DEFAULT --since 5m --filter-pattern "Browser session started"`
Expected: **one** "Browser session started" line for the 4-turn probe, not four. (Confirms one AgentCore Browser session served all 4 tool calls.)

---

## Task 9: Update docs and mark the limitation closed

**Files:**
- Modify: `prod/STATE.md:53` (remove the v1 limitation block)
- Modify: `prod/STATE.md` (browser env vars section)
- Modify: `market-intelligence-agent/CLAUDE.md` (browser tool notes)

- [ ] **Step 1: Update `prod/STATE.md`**

Delete the entire paragraph at line 53 starting with "**Known v1 limitation — cross-call tab state.**" through the end of that paragraph.

Add to the container env vars section:
```
BROWSER_MCP_TRANSPORT  = http
BROWSER_MCP_HOST       = 127.0.0.1
BROWSER_MCP_PORT       = 8765
```

Add a "How browser session sharing works" sub-section:
```
## How browser session sharing works (Phase 8.1, shipped 2026-05-31)

The runtime container boots a sidecar process `python -m app.mcp.browser.server
--transport http` on 127.0.0.1:8765 BEFORE uvicorn starts. The LangGraph MCP
client connects to that HTTP endpoint instead of spawning a new subprocess per
call, so the in-process `BrowserSessionManager` (and its single AgentCore
Browser session) is reused across all `browser_*` tool calls in a conversation.

Idle eviction: after BROWSER_IDLE_TTL_S of inactivity, the session is stopped
and the next tool call lazily starts a new one.
```

- [ ] **Step 2: Update `market-intelligence-agent/CLAUDE.md`**

Find the browser tools section. After the existing tool table, add:

```
In prod (`BROWSER_BACKEND=agentcore`, `BROWSER_MCP_TRANSPORT=http`) the
custom FastMCP server runs as a long-lived sidecar started by
`entrypoint.py`. This is what lets multi-step browser flows
(navigate → snapshot → navigate → snapshot) share tab/URL/cookie state.
```

- [ ] **Step 3: Commit**

```bash
git add prod/STATE.md market-intelligence-agent/CLAUDE.md
git commit -m "docs: close Phase 8.1 — browser session sharing live"
git push origin master
```

- [ ] **Step 4: Save memory entry**

Save a new memory entry `project_phase8_1_done.md` indexed in `MEMORY.md`:
```
- [Phase 8.1 DONE](project_phase8_1_done.md) — browser cross-call state fixed via long-lived HTTP MCP sidecar; multi-step Yahoo Finance flows work
```

---

## Self-review notes

- **Spec coverage** ✅ All 5 file-touches from the discussion are tasks (server.py, lifecycle.py, entrypoint.py, registry.py, runtime_stack.py) plus the new probe script.
- **Placeholders** ✅ Every code step has complete code; no "TBD" / "handle errors appropriately".
- **Type consistency** ✅ `SidecarHandle` defined in Task 3 is consumed by Task 4 (`entrypoint.py`); URL path `/mcp` is consistent in lifecycle.py:wait_until_ready (Task 3) and registry.py:_browser_entry (Task 5); env var names (`BROWSER_MCP_TRANSPORT`, `BROWSER_MCP_HOST`, `BROWSER_MCP_PORT`) match across config (Task 2), entrypoint (Task 4), registry (Task 5), and IaC (Task 6).
- **Rollback** is one-liner: set `BROWSER_MCP_TRANSPORT=stdio` in `runtime_stack.py`, push. Old stdio path is preserved verbatim in `_browser_entry()`.
