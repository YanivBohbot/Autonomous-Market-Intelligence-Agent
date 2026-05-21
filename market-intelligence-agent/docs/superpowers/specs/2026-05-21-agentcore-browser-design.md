# AgentCore Browser — Design Spec (Phase 4b)

**Date:** 2026-05-21
**Status:** Approved (pending implementation)
**Branch:** `feat/agentcore-prod`
**Depends on:** Phase 4a complete (commit `d5156ef`).

## Goal

Re-enable the 3 browser tools (`browser_navigate`, `browser_snapshot`, `browser_take_screenshot`) in the production agent by driving Amazon Bedrock AgentCore Browser (managed Chromium on AWS) from a thin Playwright CDP client inside the runtime container. The old `@playwright/mcp` stdio server is dropped — no `npx`, no Chromium binary in the container.

## Architecture

```
LangGraph agent (container)
    │
    │ tool_call("browser_navigate", url=...)
    ▼
tools/browser.py          (native LangChain tools)
    │
    │ boto3 StartBrowserSession → ws_url, headers
    ▼
AgentCore Browser  (managed Chromium, AWS-hosted)
    │
    │ Playwright CDP over WebSocket
    ▼
Target website
    │
    │ screenshot bytes
    ▼
S3 (prod-agent-screenshots-…) → pre-signed URL → LLM
```

**Per-call sessions.** Each tool invocation opens a fresh `browser_session`, navigates/snapshots/screenshots, closes. Simpler than per-thread caching and isolates failures. Overhead is ~1-2s per call for `StartBrowserSession`; acceptable given browser tools are not in the hot path.

**Native LangChain tools, not MCP.** AgentCore Browser is not an MCP server — it's a managed CDP endpoint. Wrapping it in MCP would mean writing yet another Lambda stub. We expose it directly via three `StructuredTool` instances in `tools/browser.py`, mirroring the dev tool names so the system prompt + `READ_ONLY_TOOLS` allowlist are unchanged.

## Tools

| Name | Signature | Behavior |
|---|---|---|
| `browser_navigate` | `(url: str) -> dict` | Opens page, returns `{title, url, status}`. No content body — that's `browser_snapshot`'s job. |
| `browser_snapshot` | `(url: str) -> dict` | Opens page, returns `{title, url, content}` where content is the rendered text (Playwright `page.inner_text("body")`) — close to the dev tool's a11y tree shape, more useful for the LLM than raw HTML. |
| `browser_take_screenshot` | `(url: str) -> dict` | Opens page, screenshots viewport, uploads PNG to S3 under `screenshots/<thread_id>/<uuid>.png`, returns `{title, url, screenshot_url}` (pre-signed URL, 1h TTL). |

All three are read-only — they go into `READ_ONLY_TOOLS` (no HITL).

## New files

- **`prod/agent/app/agent/app/agent/tools/browser.py`** — 3 `StructuredTool` instances. Each opens a session via `bedrock_agentcore.tools.browser_client.browser_session(region)`, navigates with Playwright async, returns the dict. Imports are guarded so import-time failures (missing AWS creds locally) don't crash module load — they log and produce no-op placeholders.

## Modified files

- **`prod/agent/app/agent/app/agent/tools/__init__.py`** — add a second try/except block (parallel to Phase 4a's Gateway block) that imports browser tools and appends to `TOOLS` only if AWS_REGION + BROWSER_ENABLED env var are set. `READ_ONLY_TOOLS` gains all three browser names.

- **`prod/agent/app/agent/pyproject.toml`** — add `bedrock-agentcore` and `playwright` (Python client only; no `playwright install` step in the Dockerfile — we don't need a local Chromium binary).

- **`prod/agent/agentcore/cdk/lib/cdk-stack.ts`**:
  - Provision an S3 bucket for screenshots (versioning off, RETAIN, lifecycle rule deleting objects after 30 days, blockPublicAccess BLOCK_ALL).
  - Inject `SCREENSHOT_BUCKET` env var into the runtime.
  - Grant the runtime role:
    - `bedrock-agentcore:StartBrowserSession`, `StopBrowserSession`, `GetBrowserSession`, `ConnectBrowserAutomationStream` (scoped to `browser/*`).
    - `s3:PutObject`, `s3:GetObject` on the screenshot bucket only.
  - Inject `BROWSER_ENABLED=true` to flip the import gate in tools/__init__.py.

- **`prod/agent/README.md`** — add a "Browser tool" subsection.

## Decisions

| Question | Answer | Why |
|---|---|---|
| Session lifetime | Per-call | Simple, isolated, no GC of stale sessions; 1-2s overhead acceptable |
| Screenshot storage | S3 + pre-signed URL | Scales, doesn't blow up tokens; bucket lifecycle handles cleanup |
| Local-dev fallback | No-op gated by `BROWSER_ENABLED` env | Same pattern as Phase 4a Gateway tools; coherent |
| Implementation | Native LangChain tools, not MCP | AgentCore Browser is not an MCP server; wrapping in MCP would add a useless Lambda hop |
| `browser_snapshot` content | `inner_text("body")` | Closest to dev's a11y tree shape; more LLM-friendly than HTML |

## Non-goals

- Stateful browsing across tool calls (login → navigate → form submit). Per-call sessions can't do this. If the use case shows up, revisit with per-thread session cache (Phase 4b.2).
- Custom browser provisioning (`CreateBrowser`). We use the default browser tool, no need for a custom one with VPC config yet.
- Live view in production. The dev console's live view is for debugging; not exposed to end users.

## Acceptance criteria

1. `npx tsc --noEmit` from `prod/agent/agentcore/cdk/` passes.
2. `agentcore validate` passes.
3. Local dev (`agentcore dev -p 8090`): browser tools not in `TOOLS` (BROWSER_ENABLED unset). Log line confirms skip. Phase 2 HITL email smoke test still passes.
4. New commits land on `feat/agentcore-prod`. Pushed.
