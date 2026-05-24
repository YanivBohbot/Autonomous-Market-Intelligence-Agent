# Deployment Spec — Autonomous Market Intelligence Agent on AWS AgentCore

> **Status:** ✅ Final — planning phases 1–5 complete. Ready for IaC scaffolding (Phase 6).
> **Owner:** Yaniv Bohbot
> **Last updated:** 2026-05-24

This document is the source of truth for the v1 AWS deployment of the agent. IaC, CI/CD, and runbooks under `prod/` implement what is described here.

## 0. Executive summary

Deploy the existing LangGraph + MCP market-intelligence agent to AWS using **Amazon Bedrock AgentCore Runtime** (agent container) + **AgentCore Gateway** (unified MCP endpoint with three Lambda-backed tool targets) + **AgentCore Memory** (replaces local SQLite checkpointer). External SaaS — OpenAI, Pinecone, Tavily, Gmail — are kept as-is. Region `us-east-1`. No VPC.

- **Scale:** ≤10 internal users, demo.
- **Cost:** ~$3 idle, ~$10–25 light demo, ~$60–175 peak — under the $200/mo cap. AgentCore $200 Free Tier credits cover ~2 months light.
- **Security:** 5 architectural findings (none critical) addressed in Section 4. Three per-function Lambda roles, one CMK `alias/mia`, baseline SCPs proposed.
- **IaC:** AWS CDK in Python. One stack per concern (network-free, so it's mainly compute + identity + storage + observability).
- **CI/CD:** GitHub Actions with OIDC trust to AWS (no static keys). On push to `master`: test → build ARM64 image → push ECR → `cdk deploy`.
- **Path to prod:** Phase 6 scaffolds `prod/`, Phase 7 deploys to a sandbox account and smoke-tests every tool end-to-end before cutover.

---

## 1. Goal

Deploy the existing LangGraph + MCP market-intelligence agent to AWS production using **Amazon Bedrock AgentCore Runtime** as the host and **AgentCore Gateway** as the unified MCP endpoint. v1 is a demo-grade deployment for ≤10 internal users. Voice mode (LiveKit) and a hosted UI are deferred to v1.1+.

## 2. Discovery summary (Phase 1)

| Dimension | Decision |
|---|---|
| Scale | ≤10 users, demo / internal |
| LLM | Keep OpenAI (no Bedrock swap); Pinecone kept |
| Budget | $50–$200/mo target |
| v1 scope | Text agent + MCP Gateway only |
| Region | `us-east-1` |
| Auth | None (signed URL / IAM SigV4) |

## 3. Architecture (Phase 2)

### 3.1 Services

| Service | Purpose | Notes |
|---|---|---|
| **AgentCore Runtime** | Hosts the agent container (FastAPI + LangGraph). | ARM64 image in ECR. Exposes `/ping` and `/invocations` on :8080. Scale-to-zero, pay per active CPU/mem. |
| **AgentCore Gateway** | Unified MCP endpoint for all tools. | Three Lambda targets in v1: yfinance, filesystem, sqlite-crm. |
| **AgentCore Memory** | Replaces the local SQLite checkpointer for graph state. | Removes the need for EFS or VPC. |
| **AWS Lambda × 3** | MCP servers behind Gateway. | `mia-mcp-yfinance`, `mia-mcp-filesystem`, `mia-mcp-sqlite-crm`. Python 3.12, ARM64. |
| **Amazon ECR** | Container registry for the agent image. | Private repo `mia-agent`. |
| **AWS Secrets Manager** | Stores `OPENAI_API_KEY`, `PINECONE_API_KEY`, `TAVILY_API_KEY`, `EMAIL_PASSWORD`. | Read by Runtime + Lambdas via IAM. |
| **Amazon S3** | (a) `mia-workspace` — replaces `data/workspace/`. (b) `mia-data` — hosts `customers.db` snapshot + RAG PDFs. | Versioning on; SSE-S3. |
| **CloudWatch Logs** | Logs from Runtime + Lambdas + Gateway. | 30-day retention. |
| **AgentCore Observability** | Traces of agent runs. | Default-on. |
| **IAM** | Roles: `mia-runtime-exec`, `mia-gateway-exec`, `mia-lambda-mcp-exec`. | Least privilege per resource. |

### 3.2 Request flow

```
Caller ──SigV4──▶ AgentCore Runtime (/invocations)
                       │
                       ├─▶ OpenAI Chat Completions (egress)
                       ├─▶ Pinecone query (egress)
                       ├─▶ Tavily search (egress)
                       ├─▶ AgentCore Memory (checkpoint read/write)
                       └─▶ AgentCore Gateway (MCP/HTTPS)
                                │
                                ├─▶ Lambda: yfinance MCP
                                ├─▶ Lambda: filesystem MCP ──▶ S3 mia-workspace
                                └─▶ Lambda: sqlite-crm MCP  ──▶ S3 mia-data/customers.db
```

### 3.3 Code-level changes required

1. **`app/api/server.py`** — add an `/invocations` POST handler that wraps `chat_router` for AgentCore's contract. Keep `/chat` for local dev parity.
2. **`app/agent/memory/checkpointer.py`** — add an `AgentCoreMemoryCheckpointer` implementation; choose backend via `CHECKPOINTER_BACKEND=agentcore|sqlite` env var.
3. **`app/agent/tools/mcp_clients/registry.py`** — when `MCP_TRANSPORT=gateway`, build clients over `streamable-http` to `$AGENTCORE_GATEWAY_URL` instead of stdio.
4. **New: `prod/lambdas/yfinance/`, `prod/lambdas/filesystem/`, `prod/lambdas/sqlite-crm/`** — Lambda handlers that wrap each MCP server.
5. **`app/agent/tools/mcp_clients/filesystem_client.py`** — file ops must target S3 when `WORKSPACE_BACKEND=s3`.
6. **`app/core/logging.py`** — add a redaction filter that masks the four secret values (`OPENAI_API_KEY`, `PINECONE_API_KEY`, `TAVILY_API_KEY`, `EMAIL_PASSWORD`) from any log record. Unit test asserting redaction (see security finding F3).

### 3.4 Deferred to v1.1+

- Playwright MCP → AgentCore **Browser Tool** (managed Chromium).
- LiveKit voice worker → ECS Fargate (long-running, not Runtime-shaped).
- Streamlit UI → CloudFront + Lambda Web Adapter, or App Runner.
- Pinecone → OpenSearch Serverless (if cost or data-residency demands it).

## 4. Security review (Phase 3)

Architectural review against the proposed design (no IaC yet — re-run with `iac-reviewer` once Terraform/CDK exists).

### 4.1 IAM (least privilege)

Three execution roles, scoped tightly:

| Role | Allowed actions | Scoped to |
|---|---|---|
| `mia-runtime-exec` (AgentCore Runtime) | `secretsmanager:GetSecretValue` (4 secrets), `bedrock-agentcore:InvokeGateway`, `bedrock-agentcore:CreateEvent`/`RetrieveMemory` (Memory), `s3:GetObject` on `mia-data/*`, `s3:GetObject`/`PutObject` on `mia-workspace/*`, `logs:CreateLogStream`/`PutLogEvents`, ECR pull. | Specific secret ARNs, specific bucket ARNs, the one Gateway ARN, the one Memory store ARN. No wildcards. |
| `mia-gateway-exec` (AgentCore Gateway) | `lambda:InvokeFunction` on the 3 MCP Lambda ARNs only. | Per-target ARN. |
| `mia-lambda-mcp-exec` (one shared role for the 3 MCP Lambdas, OR three per-function roles — *recommend three per-function*) | yfinance: outbound HTTPS (no AWS perms needed beyond logs). filesystem: `s3:GetObject`/`PutObject`/`ListBucket` on `mia-workspace/*` only. sqlite-crm: `s3:GetObject` on `mia-data/customers.db` only. | Per-bucket and per-prefix. |

**Decision:** three per-function Lambda roles, not one shared role — blast radius matters more than role-count savings.

Trust policies: each role's `AssumeRole` principal restricted to the exact AWS service principal (`bedrock-agentcore.amazonaws.com`, `lambda.amazonaws.com`).

No human IAM users — admin access via IAM Identity Center / SSO only.

### 4.2 Encryption

| Resource | At rest | In transit |
|---|---|---|
| S3 `mia-workspace`, `mia-data` | SSE-S3 minimum; **SSE-KMS with a customer-managed KMS key recommended** so we can deny non-KMS uploads via SCP. | TLS via `aws:SecureTransport` bucket policy condition. |
| Secrets Manager | KMS-encrypted by default (AWS-managed key fine for v1). | TLS only. |
| CloudWatch Logs | KMS-encrypted log group (use the same CMK as S3). | TLS only. |
| AgentCore Memory | Managed — encrypted at rest by AWS. | TLS only. |
| ECR | Default encryption fine for v1. | TLS only. |
| AgentCore Runtime ↔ Gateway ↔ Lambda | All AWS-internal HTTPS; nothing to configure. | n/a |

Add an S3 bucket policy on both buckets denying non-TLS requests:
```json
{"Effect":"Deny","Principal":"*","Action":"s3:*",
 "Resource":["arn:aws:s3:::mia-*","arn:aws:s3:::mia-*/*"],
 "Condition":{"Bool":{"aws:SecureTransport":"false"}}}
```

### 4.3 Secrets management

- All four secrets (`OPENAI_API_KEY`, `PINECONE_API_KEY`, `TAVILY_API_KEY`, `EMAIL_PASSWORD`) live in Secrets Manager, fetched at container start. **Never** bake into the image or env-var defaults.
- `app/core/logging.py` must redact these four values from log output (logger filter). Add a unit test that asserts redaction.
- Rotation: enable rotation reminders (no auto-rotation possible — external SaaS keys). 90-day reminder via EventBridge → SNS to your email.
- `.env` stays gitignored locally; spec explicitly forbids checking secrets into the repo.

### 4.4 Public exposure

| Surface | Exposure | Hardening |
|---|---|---|
| AgentCore Runtime `/invocations` endpoint | Public AWS endpoint, **IAM/SigV4 required**. | No "no-auth" option exists on Runtime — this is already authenticated. Caller signs with IAM creds. The "no auth" v1 decision means we issue a long-lived IAM access key for a `mia-demo-caller` user (or use STS for short-lived). |
| AgentCore Gateway URL | Public, **IAM/SigV4 required** (or OAuth — using IAM in v1). | Same — the Runtime IAM role signs requests; no anonymous access. |
| S3 buckets | Private. Block Public Access ON. | Hard requirement — see SCPs. |
| Lambda functions | Not directly invokable from internet (only via Gateway). | Function URLs disabled. |
| ECR repo | Private. | No public push. |
| External egress | OpenAI/Pinecone/Tavily/Gmail SMTP. | Runtime has internet egress by default (managed). No SSRF surface in our code paths. |

**Finding:** "No auth" in discovery actually means "no end-user auth"; AWS layer is SigV4-authenticated regardless. Update Section 6 to make this distinction clear.

### 4.5 Network isolation

- **No VPC for v1** — all components managed and use public AWS endpoints. This is intentional (avoids NAT GW ≈ $33/mo).
- No security groups, no NACLs (no VPC resources).
- If we later add OpenSearch Serverless or RDS, we'll need a VPC + VPC endpoints to Secrets Manager and S3 — out of scope for v1.

### 4.6 Logging & audit

- CloudTrail (org or account level): **must** be enabled. Captures all `InvokeAgentRuntime`, `GetSecretValue`, `s3:*` API calls.
- AgentCore Observability: on by default — captures graph traces.
- CloudWatch alarm: `GetSecretValue` denied count > 0 in 5 min → SNS email.

### 4.7 Findings summary

| # | Severity | Finding | Action |
|---|---|---|---|
| F1 | Med | Spec implied "no auth" — needs clarification: Runtime endpoint is always SigV4-protected. | Edit Section 6 to say "no end-user auth layer; AWS-layer SigV4 only." |
| F2 | Med | No KMS CMK called out — using AWS-managed keys means we can't enforce non-KMS-deny via SCP. | Add a single CMK `alias/mia` used by S3 + CloudWatch Logs. |
| F3 | Low | Logger redaction not yet implemented for the four secret values. | Add filter + unit test in code-changes section 3.3. |
| F4 | Low | No rotation reminder for external API keys. | EventBridge 90-day rule → SNS. |
| F5 | Info | CloudTrail assumed present — confirm before deploy. | Account check in Phase 6 runbook. |

No critical findings. No blockers for proceeding to cost estimate.

### 4.8 Baseline SCPs (recommended for the deploy account/OU)

If the AWS account is part of an Organization, attach these as a `mia-baseline` SCP. If standalone, implement equivalent checks as IAM permission boundaries on the admin role.

```
1. DenyDisableCloudTrail                — protect audit trail
2. DenyS3PublicAccessGrants             — no public buckets or ACLs
3. DenyUnencryptedS3Uploads             — require SSE-KMS via alias/mia
4. DenyNonTLSS3                         — require aws:SecureTransport
5. DenyRDSPublicEndpoint                — n/a in v1 but cheap insurance
6. DenyEC2WithoutIMDSv2                 — n/a in v1, future-proof
7. DenyRootAccessKeyCreation            — no root keys, ever
8. DenyLambdaFunctionURLPublicAuth      — no anonymous Lambda URLs
9. RequireIAMSSOForConsoleLogin         — no static IAM-user console access
```

The first four are hard requirements for this design; the rest are baseline hygiene that costs nothing to add now.

## 5. Cost estimate (Phase 4)

### 5.1 Traffic assumptions

| Scenario | Invocations / mo | Avg active CPU / invocation | Tool calls / mo |
|---|---|---|---|
| Idle | 0 | — | 0 |
| Light demo (~5 users, ~10 chats/user/day) | ~1,500 | ~10 s | ~3,000 |
| Peak demo (~10 users, ~50 chats/user/day) | ~15,000 | ~10 s | ~30,000 |

Container sizing for Runtime: **1 vCPU + 2 GB RAM, ARM64**. Lambda MCP tools: 256 MB, ~500 ms each.

### 5.2 AWS-side line items

| Service | Light demo | Peak demo | Notes |
|---|---|---|---|
| AgentCore Runtime (vCPU + memory, active-only) | ~$0.50 | ~$5 | 1,500 × 10 s ≈ 4.2 vCPU-h × $0.0895 + 2 GB × $0.00945. Scale-to-zero. |
| AgentCore Gateway (tool invocations) | ~$0.02 | ~$0.15 | $0.005 per 1K invocations. Per-target listing fee negligible at 3 targets. |
| AgentCore Memory | ~$1–3 | ~$10–15 | $0.25 per 1K events stored + $0.10 per 1K retrieved. |
| AgentCore Observability | ~$0.50 | ~$5 | Trace events; scales with invocations. |
| Lambda (3 MCP functions) | ~$0 (free tier) | ~$0.50 | Tiny billed duration; free tier covers light demo entirely. |
| Secrets Manager | $1.60 | $1.60 | 4 secrets × $0.40. API calls trivial. |
| S3 (storage + requests, both buckets) | ~$0.10 | ~$0.50 | <1 GB each in v1. |
| CloudWatch Logs (ingest + 30-day retention) | ~$1 | ~$5 | $0.50/GB ingest + $0.03/GB-month. |
| KMS (1 CMK `alias/mia`) | $1 | $1 | Per-key fee. API calls trivial. |
| ECR (image storage) | $0.10 | $0.10 | ~1 GB private repo. |
| CloudTrail (mgmt events, single trail) | $0 | $0 | First trail free. |
| Data egress (Runtime → OpenAI/Pinecone/Tavily) | ~$0.10 | ~$1 | $0.09/GB after 100 GB free. |
| **AWS subtotal** | **~$5–8 / mo** | **~$30–45 / mo** | |

### 5.3 External SaaS (not AWS, but in your bill)

| Provider | Light demo | Peak demo | Notes |
|---|---|---|---|
| OpenAI (gpt-4o-mini + embeddings) | ~$5–15 | ~$30–60 | Single biggest variable cost. Caching trim recommended. |
| Pinecone (Starter or pod) | $0 (Starter) | $0–70 | Starter tier covers light demo. |
| Tavily | $0 (free tier) | $0 | 1,000 searches/mo free. |
| Gmail SMTP | $0 | $0 | Send-only; volume tiny. |
| **SaaS subtotal** | **~$5–15 / mo** | **~$30–130 / mo** | |

### 5.4 Bottom line

| Scenario | AWS | SaaS | **Total** | Budget |
|---|---|---|---|---|
| Idle | ~$3 | $0 | **~$3 / mo** | ✅ floor cost |
| Light demo | ~$5–8 | ~$5–15 | **~$10–25 / mo** | ✅ well under $200 cap |
| Peak demo | ~$30–45 | ~$30–130 | **~$60–175 / mo** | ✅ inside $200 cap |

**Free Tier credit:** new AgentCore customers get $200 — covers ~2 months of light demo entirely AWS-side.

### 5.5 Optimization opportunities

1. **Prompt caching on OpenAI** — system prompt + RAG context don't change between turns; enable caching to cut input-token cost ~50%. *Highest ROI lever.*
2. **Trim CloudWatch retention from 30 → 14 days** in v1.x — halves log storage cost. Easy.
3. **Bedrock-backed embeddings (Titan)** — if you ever migrate Pinecone to OpenSearch Serverless, Titan embeddings are cheaper than OpenAI's at scale. Out of v1 scope.
4. **Right-size Runtime container to 0.5 vCPU + 1 GB** if profiling shows headroom — halves Runtime cost.
5. **Scheduled scale-down** isn't needed — Runtime scales to zero by default.

### 5.6 Cost guardrails to add in Phase 6

- AWS Budgets alert at $50/mo and $150/mo (SNS to email).
- Cost anomaly detection on the deploy account.
- Tag every resource `Project=mia`, `Env=demo` so Cost Explorer can group cleanly.

## 6. Trade-offs & decisions

- **Why OpenAI not Bedrock:** zero code change; demo budget doesn't need single-cloud benefits.
- **Why no Gateway for Playwright in v1:** Chromium is too heavy for cheap Lambda; AgentCore Browser is the managed answer and will replace it cleanly in v1.1.
- **Why AgentCore Memory over SQLite-on-EFS:** EFS forces a VPC, which raises floor cost (NAT GW ~$33/mo) and complexity. Managed memory is cheaper and simpler at this scale.
- **Why no auth:** No *end-user* auth layer in v1. The AWS-side endpoint is always SigV4-protected — the demo caller uses an IAM access key (or STS) to sign requests. Cognito or AgentCore Identity for human login goes in alongside the UI in v1.1.

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| OpenAI rate limits during demo | Med | Cache RAG results; short timeouts. |
| Pinecone outage | Low | Web search fallback already in graph (`web_search` node). |
| AgentCore Runtime cold start | Med | Acceptable for demo; warm-up cron in v1.1 if needed. |
| Lambda cold start on Gateway tool | Low | Sub-second for these handlers; tolerable. |
| Secrets leakage in logs | Low | Logger redacts known keys; review pending in Phase 3. |

## 8. Implementation plan (Phase 6 onward)

### 8.1 `prod/` folder layout

```
prod/
├── SPEC.md                       ← this file
├── iac/                          ← AWS CDK (Python) app
│   ├── app.py                    ← cdk app entrypoint
│   ├── cdk.json
│   ├── stacks/
│   │   ├── identity_stack.py     ← KMS CMK, IAM roles, IAM Identity Center bindings
│   │   ├── storage_stack.py      ← S3 buckets (mia-workspace, mia-data), bucket policies
│   │   ├── secrets_stack.py      ← Secrets Manager entries (values injected, not in repo)
│   │   ├── mcp_lambdas_stack.py  ← 3 Lambda functions (yfinance, filesystem, sqlite-crm)
│   │   ├── gateway_stack.py      ← AgentCore Gateway + 3 LambdaTargetConfigurations
│   │   ├── runtime_stack.py      ← ECR repo + AgentCore Runtime + AgentCore Memory
│   │   └── observability_stack.py← CloudWatch log groups, alarms, Budgets, CloudTrail check
│   └── tests/                    ← cdk snapshot + assertion tests
├── lambdas/
│   ├── yfinance/                 ← MCP server packaged as Lambda handler
│   ├── filesystem/               ← S3-backed; replaces stdio @modelcontextprotocol/server-filesystem
│   └── sqlite-crm/               ← reads customers.db from S3 at cold start
├── docker/
│   └── agent/
│       ├── Dockerfile            ← ARM64; FastAPI + LangGraph; entrypoint exposes /ping + /invocations on :8080
│       └── entrypoint.py         ← AgentCore contract adapter around app.api.server
└── ci/
    ├── .github/workflows/deploy.yml  (symlinked / copied to repo root .github/)
    └── README.md                     ← deploy / rollback / smoke-test runbook
```

### 8.2 Stack dependency graph

```
identity_stack ─┬─▶ storage_stack
                ├─▶ secrets_stack
                ├─▶ mcp_lambdas_stack ─▶ gateway_stack
                └─▶ runtime_stack ◀──── gateway_stack
                        │
                        └────────▶ observability_stack
```

### 8.3 GitHub Actions pipeline (`deploy.yml`)

Triggers: push to `master`, manual `workflow_dispatch`.

Jobs:
1. **test** — `uv run pytest tests/ -v` (existing suite + new redaction test).
2. **build** — `docker buildx build --platform linux/arm64 -t mia-agent:$SHA prod/docker/agent/`. Push to ECR via OIDC role.
3. **package-lambdas** — zip each `prod/lambdas/*` with deps; upload artifacts.
4. **deploy** — `cdk deploy --all --require-approval never`. Uses the OIDC role assumed via `aws-actions/configure-aws-credentials@v4`.
5. **smoke** — `python prod/ci/smoke.py` invokes Runtime via `InvokeAgentRuntime`, asserts each MCP tool is reachable through Gateway.

### 8.4 Code-side prerequisites (do these before Phase 6 IaC)

These touch the existing `market-intelligence-agent/app/` code, not `prod/`:

1. Add `/invocations` handler to `app/api/server.py` (AgentCore contract: POST, JSON body, returns JSON).
2. Add `CHECKPOINTER_BACKEND={sqlite|agentcore}` env switch in `app/agent/memory/checkpointer.py`.
3. Add `MCP_TRANSPORT={stdio|gateway}` switch in `app/agent/tools/mcp_clients/registry.py`.
4. Add `WORKSPACE_BACKEND={local|s3}` switch in `filesystem_client.py`.
5. Add logger redaction filter in `app/core/logging.py` + unit test (Phase 3 finding F3).
6. Add OpenAI prompt caching for system prompt + RAG context (Phase 4 optimization #1).

### 8.5 Phase 7 smoke-test checklist

Run against a dev/sandbox AWS account before declaring the demo deployable.

- [ ] `InvokeAgentRuntime` returns a non-error response on a "hello" prompt.
- [ ] Each of the 3 Gateway tools returns a successful tool call from a synthetic agent run:
  - [ ] `yfinance_get_ticker_info` for `AAPL`
  - [ ] `list_directory` against `mia-workspace`
  - [ ] `read_query` against `customers.db`
- [ ] HITL interrupt flow works: a side-effect call (e.g., `write_file`) triggers the interrupt; resume with `Command(resume="approve")` succeeds.
- [ ] AgentCore Memory persists a session across two invocations with the same `session_id`.
- [ ] Secrets Manager values are read by the Runtime (no env-var fallback used).
- [ ] CloudWatch Logs show no leaked secret values (redaction filter works).
- [ ] AWS Budgets alarm fires correctly on a synthetic threshold breach.

### 8.6 Out of scope for v1 (tracked for v1.1+)

- Voice mode (LiveKit worker) on ECS Fargate.
- Streamlit (or React) UI behind CloudFront + Cognito.
- Playwright MCP → AgentCore Browser Tool.
- Pinecone → OpenSearch Serverless (only if data-residency or cost demands it).
- Multi-region / DR.

---

## Appendix A — Decisions log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-24 | Region `us-east-1` | Widest AgentCore feature availability. |
| 2026-05-24 | Keep OpenAI (not Bedrock) | Zero code change; cost difference is wash at this scale. |
| 2026-05-24 | Tight budget $50–$200/mo | Demo / portfolio scale. |
| 2026-05-24 | v1 scope = text + MCP only | Voice and UI deferred per user request. |
| 2026-05-24 | Option A architecture | Honors "AgentCore + MCP Gateway" goal. |
| 2026-05-24 | AgentCore Memory over SQLite-on-EFS | Avoids VPC + NAT GW ~$33/mo. |
| 2026-05-24 | Three per-function Lambda roles | Smaller blast radius than one shared role. |
| 2026-05-24 | One CMK `alias/mia` for S3 + Logs | Enables SCP-level KMS enforcement. |
| 2026-05-24 | No VPC in v1 | All services managed-public; avoids floor cost. |
| 2026-05-24 | AWS CDK (Python) for IaC | Stays in Python; native AgentCore L2 constructs available. |
| 2026-05-24 | GitHub Actions + OIDC for CI/CD | No long-lived AWS keys; fits solo dev. |
