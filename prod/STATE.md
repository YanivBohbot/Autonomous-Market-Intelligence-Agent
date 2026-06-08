# Production state — Market Intelligence Agent

> Single source of truth for what's deployed, where, and how to verify it.
> Updated 2026-05-25. Keep this in sync when production changes — failing
> that, trust the AWS console + `prod/ci/qa_full.py` over this doc.

## Live deployment (us-east-1, account 584246028688)

| Component | Identifier |
|---|---|
| Agent runtime | `arn:aws:bedrock-agentcore:us-east-1:584246028688:runtime/mia_runtime_demo-tio2ELGaQB` |
| Gateway URL (MCP-over-HTTPS) | `https://mia-gateway-demo-ighmbonbou.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp` |
| AgentCore Memory (also durable checkpoint store) | `mia_memory_demo-UOKiBF3nx2` |
| Cognito user pool | `us-east-1_KxtN9pzgf` |
| S3 buckets | `mia-data-584246028688` (CRM read-only), `mia-workspace-584246028688` (filesystem RW) |
| Lambdas | `mia-mcp-yfinance-demo`, `mia-mcp-sqlite-crm-demo`, `mia-mcp-filesystem-demo` |
| AgentCore Browser (Custom) | `arn:aws:bedrock-agentcore:us-east-1:584246028688:browser-custom/mia_browser_demo-3zRFIUdmM7` |
| Browser recordings bucket | `mia-browser-recordings-584246028688-us-east-1` (KMS, 30-day lifecycle) |
| Stacks | `mia-storage-demo`, `mia-secrets-demo`, `mia-mcp-lambdas-demo`, `mia-gateway-demo`, `mia-runtime-demo`, `mia-observability-demo`, `mia-browser-demo` |
| Deploy pipeline | GitHub Actions OIDC via `mia-github-deploy` IAM role (master branch only) |

## What the agent can do (13 tools)

### Read-only (no HITL approval needed)

| Tool | Backend | What it does |
|---|---|---|
| `yfinance_get_ticker_info` | Lambda `mia-mcp-yfinance-demo` | Current price + day stats for a ticker |
| `yfinance_get_price_history` | same | OHLCV history over a period |
| `yfinance_get_ticker_news` | same | Recent news headlines for a ticker |
| `read_query` | Lambda `mia-mcp-sqlite-crm-demo` | Read-only SELECT against `customers.db` in S3 |
| `read_text_file` | Lambda `mia-mcp-filesystem-demo` | Read UTF-8 file from `mia-workspace` bucket |
| `list_directory` | same | List files in a workspace path |
| `recall_memory` | LangGraph `BaseStore` (in-process) | Look up one saved user fact by key |
| `list_memories` | same | List all saved user facts |

### Side-effect (HITL `interrupt()` + `Command(resume=...)`)

| Tool | Backend | What it does |
|---|---|---|
| `write_file` | Lambda `mia-mcp-filesystem-demo` | Write a text file into the workspace bucket |
| `save_memory` | LangGraph `BaseStore` | Persist a user fact (key + value) |
| `send_email` | **Amazon SES** via boto3 | Send a plain-text email (sandbox: sender + recipient must be verified) |

### Browser (Phase 8 — Amazon Bedrock AgentCore Browser, deployed 2026-05-27)

| Tool | Backend | What it does |
|---|---|---|
| `browser_navigate` | Custom stdio MCP server in `app/mcp/browser/` → AgentCore Browser (managed Chromium) | Navigate the page to a URL |
| `browser_snapshot` | same | Return the body inner text of the current page |
| `browser_take_screenshot` | same | Save a PNG into the workspace; AgentCore session recording captured separately to S3 |

**Known v1 limitation — cross-call tab state.** `langchain-mcp-adapters` 0.1.0 spawns one stdio subprocess per tool call, so each `browser_*` call gets a fresh `BrowserSessionManager` → fresh `StartBrowserSession` → fresh tab. Multi-step browser flows (navigate → snapshot in separate tool calls) don't carry tab state. Single-call use works; chained workflows are a Phase 8.1 follow-up (move to a long-lived MCP server transport, or persist the AgentCore session id in checkpoint state and resume it on next call).

## Tools NOT yet in production (designed, deferred)

- **Voice mode** (LiveKit + Deepgram + ElevenLabs worker) — Phase 9

## Container env vars (`mia-runtime-demo` AgentCore Runtime)

```
CHECKPOINTER_BACKEND   = agentcore     # AgentCoreMemorySaver, durable across containers
MCP_TRANSPORT          = gateway
WORKSPACE_BACKEND      = s3
EMAIL_SENDER           = yanivbohbot5@gmail.com  # SES-verified
AGENTCORE_GATEWAY_URL  = <gateway mcp URL>
MIA_MEMORY_ID          = mia_memory_demo-UOKiBF3nx2
WORKSPACE_S3_BUCKET    = mia-workspace-584246028688
MIA_COGNITO_*          = hardcoded demo IDs (tech debt)
OPENAI_API_KEY_ARN     = <secret arn>
PINECONE_API_KEY_ARN   = <secret arn>
TAVILY_API_KEY_ARN     = <secret arn>
OPENAI_MODEL           = gpt-4o-mini
OPENAI_EMBEDDING_MODEL = text-embedding-3-small
PINECONE_INDEX_NAME    = mia-rag      # index is empty — RAG falls through to web_search
```

`EMAIL_PASSWORD_ARN`, `EMAIL_SMTP_SERVER`, `EMAIL_SMTP_PORT` were dropped when send_email migrated to SES. The Secrets Manager entry `mia/email-password` still exists for rollback.

## How to verify the live system

Run any/all from the repo root:

```bash
python prod/ci/smoke.py          # 4 cases, status-only (used by CI)
python prod/ci/qa.py             # 8 cases, loose grounded
python prod/ci/qa_full.py        # 18 cases, full tool coverage + HITL
python prod/ci/qa_playground.py  # 18 cases, sticky + fresh-runtime-session
python prod/ci/probe_email.py    # 1 case, returns a real SES MessageId
python prod/ci/probe_playground.py  # 6 cases, mimics the Console UI
python prod/ci/chat.py           # interactive REPL with sticky session
```

All 4 grounded suites currently pass 100%.

## How the AWS Console Runtime Playground works for HITL

The Console UI generates a new `runtimeSessionId` per "Run" click. AgentCore
routes to any container. With the durable checkpointer, that's fine — what
keeps a multi-turn conversation glued is the `body.session_id` you paste:

```json
{"prompt": "Write a file ...", "session_id": "console-demo-1"}
```
Hit Run → status=interrupted, pending_tool_calls.

```json
{"resume": "approve", "session_id": "console-demo-1"}
```
Hit Run → status=completed, tool actually ran.

```json
{"prompt": "What was the first thing I asked?", "session_id": "console-demo-1"}
```
Hit Run → references your first turn.

The rule: same `session_id` value across every step in a flow.

## Rollback recipes

| If this breaks | Rollback |
|---|---|
| `agentcore` checkpoint backend | Set `CHECKPOINTER_BACKEND=memory` in `prod/iac/stacks/runtime_stack.py`, push. The `memory` branch in `app/agent/memory/checkpointer.py` is intact. |
| SES send_email | `git revert e1acf43 30d7570 1728ece`, push. App Password still in `mia/email-password` Secret. |
| GH Actions OIDC | Local `cdk deploy <stack>` from `prod/iac/` still works as long as you have aws creds. |

## Tech debt / follow-ups (not urgent)

- `actor_id="mia-agent"` hardcoded in 5 files — derive per-user when auth multi-tenancy lands.
- 4 hardcoded Cognito IDs in `runtime_stack.py` — pull from gateway construct outputs next gateway rebuild.
- IAM `runtime/*` wildcard on the OIDC role's `InvokeAgentRuntime` — tighten when runtime ARN stops drifting.
- SES still in sandbox (200/day, verified recipients only). Request production access for arbitrary recipients (24h SLA).
- Pinecone RAG index empty — agent always falls back to Tavily.
- AgentCore Memory `expiration_duration=30 days` — review for short-term events.
- `mia/email-password` Secret unused after SES migration — delete after grace period.

## Quick links

- Spec: `market-intelligence-agent/docs/superpowers/specs/2026-05-25-durable-checkpointer-design.md`
- Plan: `market-intelligence-agent/docs/superpowers/plans/2026-05-25-durable-checkpointer.md`
- OIDC setup: `prod/iac/README-github-oidc.md`
- CI workflow: `.github/workflows/deploy.yml`
- Smoke script: `prod/ci/smoke.py` (post-deploy gate)
