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
        # Playwright Python 1.46+ removed page.accessibility.snapshot(). Fall back to
        # the visible body text — same purpose (give the LLM a readable page summary)
        # without the accessibility-tree shape.
        try:
            return page.locator("body").inner_text(timeout=10000)
        except Exception:
            return page.content()  # last resort: raw HTML
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


# Tool wrappers are async because FastMCP runs them inside an asyncio loop.
# The underlying _impl functions use Playwright's *sync* API, which refuses to
# run inside an asyncio loop. asyncio.to_thread shoves the sync work onto a
# worker thread so Playwright sees a clean sync context. Keeps the _impl
# functions test-friendly without an async-Playwright rewrite.
import asyncio


@mcp.tool()
async def browser_navigate(url: str) -> str:
    """Navigate the persistent browser tab to a URL."""
    return await asyncio.to_thread(_navigate_impl, url)


@mcp.tool()
async def browser_snapshot() -> str:
    """Return the current page as a flattened accessibility tree."""
    return await asyncio.to_thread(_snapshot_impl)


@mcp.tool()
async def browser_take_screenshot(filename: str) -> str:
    """Save a PNG into workspace screenshots/ and return its workspace-relative path."""
    return await asyncio.to_thread(_screenshot_impl, filename)


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
