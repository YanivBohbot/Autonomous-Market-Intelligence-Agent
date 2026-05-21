"""AgentCore Browser tools — managed Chromium via CDP (Phase 4b).

Three native LangChain tools that drive Amazon Bedrock AgentCore Browser
(managed headless Chromium on AWS) over the Chrome DevTools Protocol via
Playwright. The container ships only the lightweight Playwright Python
client; the actual browser runs in AWS, not in the runtime container.

Tools (names match the dev project verbatim so the system prompt and the
READ_ONLY_TOOLS allowlist are unchanged):

- browser_navigate(url)         → {title, url, status}
- browser_snapshot(url)         → {title, url, content} (body inner_text)
- browser_take_screenshot(url)  → {title, url, screenshot_url} (S3 presigned, 1h TTL)

Session model: one BrowserSession per tool invocation (per-call). Opening a
session costs ~1-2s, which is acceptable for the low-frequency browser path
and avoids the GC/staleness problems of caching sessions across calls.

Local-dev fallback: this module is only imported when `BROWSER_ENABLED=1` is
set on the runtime by the CDK stack. In local `agentcore dev`, that env var
is unset, so `tools/__init__.py` never imports us and the tools never make
it into `TOOLS`. The LLM doesn't see them, no AWS calls happen.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import uuid
from typing import Any

import boto3
from bedrock_agentcore.tools.browser_client import browser_session
from langchain_core.tools import StructuredTool
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Bound page navigation. AgentCore's StartBrowserSession is the expensive
# part (~1-2s); we don't want a slow target page to compound that.
_PAGE_TIMEOUT_MS = 20_000


def _region() -> str:
    return os.environ.get("AWS_REGION", "us-east-1")


def _run_async(coro):
    """Same sync-bridge pattern as mcp_clients/registry.py.

    Tool invocation happens inside uvicorn's running loop, so `asyncio.run()`
    raises. We fall back to running the coroutine in a worker thread with a
    fresh loop. Not pretty, but the alternative is making every LangGraph
    tool async-aware, which is invasive.
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()


# --- Per-tool implementations -------------------------------------------------

class _UrlArgs(BaseModel):
    url: str = Field(..., description="Absolute URL to load (must start with http:// or https://).")


async def _navigate_impl(url: str) -> dict[str, Any]:
    return await _do(url, mode="navigate")


async def _snapshot_impl(url: str) -> dict[str, Any]:
    return await _do(url, mode="snapshot")


async def _screenshot_impl(url: str) -> dict[str, Any]:
    return await _do(url, mode="screenshot")


async def _do(url: str, mode: str) -> dict[str, Any]:
    """Single code path for all three tools — mode flag picks the capture step."""
    region = _region()
    try:
        with browser_session(region) as client:
            ws_url, headers = client.generate_ws_headers()
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp(ws_url, headers=headers)
                try:
                    page = browser.contexts[0].pages[0]
                    await page.goto(url, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT_MS)
                    title = await page.title()
                    final_url = page.url

                    if mode == "navigate":
                        return {"title": title, "url": final_url, "status": "ok"}

                    if mode == "snapshot":
                        # inner_text("body") is the closest match to the dev
                        # tool's accessibility tree shape — rendered visible
                        # text, no HTML noise.
                        content = await page.inner_text("body")
                        return {"title": title, "url": final_url, "content": content}

                    if mode == "screenshot":
                        png = await page.screenshot(full_page=False)
                        bucket = os.environ.get("SCREENSHOT_BUCKET")
                        if not bucket:
                            return {
                                "title": title,
                                "url": final_url,
                                "error": "SCREENSHOT_BUCKET unset — cannot upload screenshot",
                            }
                        key = f"screenshots/{uuid.uuid4().hex}.png"
                        s3 = boto3.client("s3", region_name=region)
                        s3.put_object(Bucket=bucket, Key=key, Body=png, ContentType="image/png")
                        presigned = s3.generate_presigned_url(
                            "get_object",
                            Params={"Bucket": bucket, "Key": key},
                            ExpiresIn=3600,
                        )
                        return {"title": title, "url": final_url, "screenshot_url": presigned}

                    return {"error": f"unknown mode {mode!r}"}
                finally:
                    await browser.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[browser] %s(%r) failed: %r", mode, url, exc)
        return {"error": f"browser_{mode} failed: {exc}"}


# --- Sync wrappers exposed as LangChain tools --------------------------------

def _navigate(url: str) -> dict[str, Any]:
    return _run_async(_navigate_impl(url))


def _snapshot(url: str) -> dict[str, Any]:
    return _run_async(_snapshot_impl(url))


def _screenshot(url: str) -> dict[str, Any]:
    return _run_async(_screenshot_impl(url))


browser_navigate_tool: StructuredTool = StructuredTool.from_function(
    func=_navigate,
    name="browser_navigate",
    description=(
        "Open a URL in a managed headless browser and return the page title + final URL. "
        "Use this when you just need to confirm a page loads or follow a redirect."
    ),
    args_schema=_UrlArgs,
)

browser_snapshot_tool: StructuredTool = StructuredTool.from_function(
    func=_snapshot,
    name="browser_snapshot",
    description=(
        "Open a URL in a managed headless browser and return the rendered text content of the page body. "
        "Use this to read live web content that isn't covered by the RAG index or web_search."
    ),
    args_schema=_UrlArgs,
)

browser_screenshot_tool: StructuredTool = StructuredTool.from_function(
    func=_screenshot,
    name="browser_take_screenshot",
    description=(
        "Open a URL in a managed headless browser, take a viewport screenshot, "
        "upload to S3, and return a 1-hour pre-signed URL. Use sparingly — only when the user explicitly asks for a screenshot."
    ),
    args_schema=_UrlArgs,
)
