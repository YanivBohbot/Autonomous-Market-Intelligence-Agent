# AgentCore Browser — Design Spec

**Phase 8 of the agentic-expansion roadmap.** Deploys the three browser tools (`browser_navigate`, `browser_snapshot`, `browser_take_screenshot`) to production by routing them through Amazon Bedrock AgentCore Browser instead of a local Chromium. Dev path is unchanged.

Companion to the May-12 local Playwright MCP spec (`2026-05-12-playwright-mcp-design.md`), which remains the source of truth for the dev path and the tool-name contract.

## Decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Browser backend in prod | Amazon Bedrock AgentCore Browser (managed Chromium, WebSocket CDP via SigV4) |
| 2 | Integration shape | **Custom MCP server** wrapping `bedrock_agentcore.tools.browser_client.BrowserClient` + Playwright Python. Stdio transport. |
| 3 | Tool contract | Identical to `@playwright/mcp` — same 3 names, same argument shapes, same return shapes. LLM behaves identically dev vs prod. |
| 4 | Dev/prod parity | Env switch `BROWSER_BACKEND=local\|agentcore`. Mirrors `CHECKPOINTER_BACKEND` / `MCP_TRANSPORT` / `WORKSPACE_BACKEND`. |
| 5 | Session lifecycle | Per LangGraph `thread_id`, lazy-start on first browser call, idle-TTL eviction (default 300s), hard server timeout 1800s, auto-reconnect on disconnect. |
| 6 | Session recording | ON. Custom Browser Tool (system `aws.browser.v1` doesn't record). Dedicated S3 bucket with 30-day lifecycle. |
| 7 | HITL gate | All 3 tools remain in `READ_ONLY_TOOLS`. Unchanged from May-12 spec. |

## Architecture

```
LangGraph agent
  └── browser_navigate_tool / _snapshot / _screenshot         (existing selector — unchanged)
        └── MultiServerMCPClient → "browser" stdio process
              ├── (dev,  BROWSER_BACKEND=local)     npx @playwright/mcp + local Chromium
              └── (prod, BROWSER_BACKEND=agentcore) python -m prod.mcp.browser.server
                          └── BrowserSessionManager
                              └── boto3 bedrock-agentcore.StartBrowserSession
                                    └── Playwright connect_over_cdp(signed WS)
                                          └── AgentCore Browser (managed Chromium)
                                                └── S3 recording bucket (KMS, 30-day)
```

One MCP server process is spawned **per LangGraph thread** so that the session manager can key on `thread_id` via env var without parsing MCP request context. Process exit signal-handlers tear down the AgentCore session best-effort.

### Why a custom MCP server instead of `@playwright/mcp --cdp-endpoint`

AgentCore Browser does not expose a plain `ws://…` CDP URL. The data-plane is a SigV4-signed WebSocket via `bedrock-agentcore:ConnectBrowserAutomationStream`. `@playwright/mcp` cannot sign requests. AWS publishes `bedrock_agentcore.tools.browser_client.BrowserClient`, a Python helper that handles SigV4 + WebSocket tunneling and exposes the connection to Playwright via `playwright.chromium.connect_over_cdp(url, headers=…)`. Wrapping this helper in a stdio MCP server is the minimum-surface way to keep the existing tool-name contract.

## Components

| File | Change |
|---|---|
| `prod/mcp/browser/server.py` | **NEW.** FastMCP stdio server exposing the 3 tools by name-identical contract. |
| `prod/mcp/browser/session_manager.py` | **NEW.** Per-process `BrowserSessionManager` — lazy-start, idle-TTL, auto-reconnect, signal-handler cleanup. |
| `prod/mcp/browser/__init__.py` | **NEW.** Package marker. |
| `prod/iac/stacks/browser_stack.py` | **NEW.** Custom Browser Tool resource + S3 recording bucket + browser execution role. |
| `prod/iac/stacks/runtime_stack.py` | IAM additions on the Runtime role; new env vars on the container. |
| `prod/iac/app.py` | Register `BrowserStack`; pass its outputs to `RuntimeStack`. |
| `app/agent/tools/mcp_clients/registry.py` | Branch the `"browser"` entry on `BROWSER_BACKEND` env var. Default `local`. |
| `app/agent/tools/mcp_clients/browser_client.py` | **No change.** Selector and tool names stay identical. |
| `Dockerfile` | Ensure `bedrock-agentcore` and `playwright` Python packages are installed in the prod image. Chromium binary not needed (managed remotely). |
| `prod/ci/probe_browser.py` | **NEW.** Live integration probe — navigate, snapshot, screenshot, assert S3 recording object lands. |
| `prod/ci/qa_playground.py` | Add cases 19 (`navigate → snapshot`) and 20 (`navigate → screenshot → write_file` with HITL approve). |
| `tests/mcp/test_browser_server.py` | **NEW.** Unit-test session manager lifecycle with stubbed boto3 client. |
| `docs/TOOLS.md` | No new rows (tool names unchanged) — add a "Production backend" note to the 3 browser entries pointing at this spec. |
| `CLAUDE.md` | Add `BROWSER_BACKEND`, `BROWSER_TOOL_ID`, `BROWSER_IDLE_TTL_S` to the env vars section. Note the dev/prod backend switch in the tools table. |
| `prod/STATE.md` | After cutover, add Browser ARN + recording bucket to the live-system snapshot. |

## Session lifecycle

`BrowserSessionManager` is instantiated once per MCP server process. It holds at most one live AgentCore session, keyed on the `BROWSER_THREAD_ID` env var passed in at spawn time.

| Event | Behavior |
|---|---|
| First `browser_*` call | `StartBrowserSession(browserIdentifier=<custom-arn>, sessionTimeoutSeconds=1800)`. Open Playwright `connect_over_cdp(signed_ws_url, headers=signed_headers)`. Cache `(browser, context, page)`. |
| Subsequent calls in same thread | Reuse the cached page. Navigate → snapshot → screenshot is one tab. |
| Idle | Background asyncio task sleeps `BROWSER_IDLE_TTL_S` (default 300s) on the last-activity timestamp. On expiry, call `StopBrowserSession`, drop cache. |
| Hard timeout (1800s server-side) | WebSocket close detected. Drop cache. Next call lazy-restarts cleanly. |
| Process exit (SIGTERM/SIGINT) | Signal handler attempts `StopBrowserSession` (best-effort, non-blocking, 2s budget). Server-side TTL is the final safety net. |
| `StartBrowserSession` throttled / quota exceeded | Return MCP tool error. LLM either retries after a single backoff or tells the user the browser is busy. |
| Mid-call WebSocket disconnect | Manager catches, drops cache, retries the operation up to 3 times. If all 3 fail, surface as MCP tool error. |

### `thread_id` propagation

`MultiServerMCPClient` spawns one stdio subprocess per server entry per session. We extend the registry so the `"browser"` entry is keyed on `f"browser-{thread_id}"` and passes `BROWSER_THREAD_ID={thread_id}` in the spawn env. This avoids parsing MCP `request_context` and keeps the session manager logic trivially testable.

## Tool contract

Names, argument shapes, and return shapes match `@playwright/mcp` exactly so the LLM behaves identically in dev and prod.

| Tool | Args | Returns | Read-only? |
|---|---|---|---|
| `browser_navigate` | `url: str` | `"Navigated to <url>"` on success; error string on failure | yes |
| `browser_snapshot` | (none) | Accessibility tree as flattened structured text (Playwright `page.accessibility.snapshot()`) | yes |
| `browser_take_screenshot` | `filename: str` (workspace-relative under `screenshots/`) | Workspace-relative path written | yes |

Screenshots write into the agent container's workspace (S3-backed when `WORKSPACE_BACKEND=s3`, local otherwise) — **separate** from the AgentCore session *recording*, which captures full DOM/network replay into the dedicated recording bucket.

## Error handling

| Failure | Behavior |
|---|---|
| `StartBrowserSession` throttled / quota | MCP error string up; LLM retries once or reports busy. |
| WebSocket disconnect mid-call | Auto-reconnect up to 3x; surface only if all retries fail. |
| Playwright navigation timeout (30s default) | Error string up; LLM falls back to Tavily or reports failure. |
| Invalid URL / DNS / 4xx | Error string up; same path as today's local backend. |
| Recording S3 `PutObject` fails | Logged. Session continues — recording is non-critical evidence, not the data path. |
| Process exit with live sessions | Signal handler best-effort stop; server-side TTL is the safety net. |

No new prompts. The existing `ERROR_RECOVERY_PROMPT` in `app/agent/prompts/system.py` already covers "tool returned an error, decide what to do."

## Testing

### Unit tests (`tests/mcp/test_browser_server.py`)

`moto` does not yet support `bedrock-agentcore`. Stub at the boto3 client layer via `botocore.stub.Stubber`.

- Lazy-start: first call triggers `StartBrowserSession`, second call reuses session.
- Idle eviction: simulate clock past `BROWSER_IDLE_TTL_S`; assert `StopBrowserSession` called and next call re-starts.
- Hard timeout: simulate WebSocket close; assert next call lazy-restarts cleanly.
- Auto-reconnect: simulate one mid-call disconnect; assert retry succeeds. Simulate three disconnects; assert MCP error surfaces.
- Signal handler: send SIGTERM; assert `StopBrowserSession` called within 2s budget.

No real Playwright in unit tests.

### Integration probe (`prod/ci/probe_browser.py`)

Hits live AWS. Gated behind `workflow_dispatch` — not on push, costs money.

- Navigate to `https://example.com`.
- Snapshot — assert `Example Domain` substring in returned text.
- Screenshot to `example.png` — assert file exists in workspace.
- Stop session; poll the recording bucket for 60s; assert at least one object under the session prefix.

### Grounded QA (`prod/ci/qa_playground.py`)

- **Case 19** — `browser_navigate("https://example.com") → browser_snapshot()`. Assert `"Example Domain"` in agent's final answer.
- **Case 20** — `browser_navigate → browser_take_screenshot("evidence.png") → write_file("brief.md", …)`. Two-step interrupt path — screenshot is read-only, write_file gates HITL approve. Assert the final brief references `evidence.png`.

Target: **20/20** after cutover.

## Cutover order (zero-downtime)

1. Code-side prereqs land on master: `BROWSER_BACKEND` switch, `prod/mcp/browser/`, session manager, unit tests. CI green, all 18 existing QA cases still pass.
2. Deploy `BrowserStack` (Custom Browser + S3 + execution role). Agent still uses local mode in dev; **no behavioral change in prod** (BROWSER_BACKEND defaulted to `local` in the existing runtime container until step 3).
3. Deploy `RuntimeStack` update with `BROWSER_BACKEND=agentcore` env var and IAM additions. Container restart switches paths.
4. Run `probe_browser.py` from a laptop against the live runtime.
5. Run `qa_playground.py` — must hit 20/20.

### Rollback

Flip `BROWSER_BACKEND` back to `local` in `RuntimeStack` env and redeploy. (Note: `local` in the prod container means the dev-mode `npx @playwright/mcp` path, which won't function without Chromium baked in — so rollback is really "redeploy the previous container tag." `BrowserStack` itself stays — idle cost ≈ $0/mo with no sessions running.)

## IAM detail

### Runtime role additions (existing role, new statement)

```json
{
  "Sid": "AgentCoreBrowser",
  "Effect": "Allow",
  "Action": [
    "bedrock-agentcore:StartBrowserSession",
    "bedrock-agentcore:StopBrowserSession",
    "bedrock-agentcore:GetBrowserSession",
    "bedrock-agentcore:ConnectBrowserAutomationStream"
  ],
  "Resource": "<custom-browser-arn>"
}
```

### Custom Browser execution role (new)

Trust policy with confused-deputy guards:

```json
{
  "Effect": "Allow",
  "Principal": { "Service": "bedrock-agentcore.amazonaws.com" },
  "Action": "sts:AssumeRole",
  "Condition": {
    "StringEquals": { "aws:SourceAccount": "<acct>" },
    "ArnLike":      { "aws:SourceArn":     "arn:aws:bedrock-agentcore:us-east-1:<acct>:*" }
  }
}
```

Permissions: only `s3:PutObject` / `s3:ListMultipartUploadParts` / `s3:AbortMultipartUpload` on the recording bucket prefix, with `aws:ResourceAccount` equality condition.

## New env vars

| Var | Default | Purpose |
|---|---|---|
| `BROWSER_BACKEND` | `local` | `local` (npx @playwright/mcp) or `agentcore` (custom MCP server → AgentCore Browser) |
| `BROWSER_TOOL_ID` | — | Custom Browser ARN. Required when `BROWSER_BACKEND=agentcore`. |
| `BROWSER_IDLE_TTL_S` | `300` | Idle seconds before the session manager stops the AgentCore session. |
| `BROWSER_THREAD_ID` | — | Set by the registry per-spawn. Not user-facing. |

## Cost estimate (demo scale)

- Browser CPU+memory: per-session-second. A 5-min research task ≈ $0.01–0.02. Demo volume: <$2/mo.
- S3 recordings: ~10–50MB per session, 30-day lifecycle ≈ $0.10/mo.
- Total new monthly add: **~$1–5/mo** at demo scale.

OpenAI tokens still dominate total spend per the cost memo.

## Out of scope (v1)

- Live View streaming (real-time human watch / takeover). Useful for demos, not required for the tool surface. Add later if asked.
- Multi-tenant `actor_id` derivation. Inherits the same tech debt as the durable checkpointer — single `mia-agent` actor for now.
- AgentCore Code Interpreter. Separate phase if/when needed.
- Replacing local dev Chromium with always-on AgentCore. Dev parity matters; this stays an env switch.
