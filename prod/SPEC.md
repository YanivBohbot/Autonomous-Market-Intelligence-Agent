# Deployment Spec — Autonomous Market Intelligence Agent on AWS AgentCore

> **Status:** Draft — phases 1 & 2 complete; phases 3–5 in progress.
> **Owner:** Yaniv Bohbot
> **Last updated:** 2026-05-24

This document is the source of truth for the v1 AWS deployment of the agent. IaC, CI/CD, and runbooks under `prod/` will implement what is described here.

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

### 3.4 Deferred to v1.1+

- Playwright MCP → AgentCore **Browser Tool** (managed Chromium).
- LiveKit voice worker → ECS Fargate (long-running, not Runtime-shaped).
- Streamlit UI → CloudFront + Lambda Web Adapter, or App Runner.
- Pinecone → OpenSearch Serverless (if cost or data-residency demands it).

## 4. Security review (Phase 3)

_To be completed._

## 5. Cost estimate (Phase 4)

_To be completed. Preliminary: $15–$40/mo at demo traffic._

## 6. Trade-offs & decisions

- **Why OpenAI not Bedrock:** zero code change; demo budget doesn't need single-cloud benefits.
- **Why no Gateway for Playwright in v1:** Chromium is too heavy for cheap Lambda; AgentCore Browser is the managed answer and will replace it cleanly in v1.1.
- **Why AgentCore Memory over SQLite-on-EFS:** EFS forces a VPC, which raises floor cost (NAT GW ~$33/mo) and complexity. Managed memory is cheaper and simpler at this scale.
- **Why no auth:** ≤10 internal users + signed URL is sufficient for demo. Cognito or AgentCore Identity goes in alongside the UI in v1.1.

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| OpenAI rate limits during demo | Med | Cache RAG results; short timeouts. |
| Pinecone outage | Low | Web search fallback already in graph (`web_search` node). |
| AgentCore Runtime cold start | Med | Acceptable for demo; warm-up cron in v1.1 if needed. |
| Lambda cold start on Gateway tool | Low | Sub-second for these handlers; tolerable. |
| Secrets leakage in logs | Low | Logger redacts known keys; review pending in Phase 3. |

## 8. Next steps

1. Phase 3 — Security review of this design.
2. Phase 4 — Detailed cost estimate.
3. Phase 5 — Finalize this spec, then scaffold `prod/iac/` (Terraform or CDK — TBD).
4. Phase 6 — Build + push images, deploy, smoke-test.
