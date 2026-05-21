# AgentCore production deployment plan

Living document. Branch: `feat/agentcore-prod`. Updated 2026-05-21.

## Goal

Deploy the dev project (LangGraph + MCP + HITL + RAG + Streamlit) to **Amazon Bedrock AgentCore Runtime** in `us-east-1`, with the rest of the stack on adjacent AWS services.

## Target architecture

```
                        ┌─────────────────────────────────┐
   Streamlit UI ───────►│  AgentCore Runtime              │
   (App Runner          │   ├─ LangGraph agent (container)│
    or ECS Fargate)     │   ├─ Bedrock Claude Sonnet 4    │
                        │   ├─ DynamoDB checkpoint table  │
                        │   └─ AgentCore Gateway (MCP)    │──► Lambda tools
                        │                                 │       (yfinance,
                        │   OTel → CloudWatch + X-Ray     │        CRM,
                        └─────────────────────────────────┘        filesystem→S3)
```

## Phase map

| # | Title | Status | Notes |
|---|---|---|---|
| 0 | Clean slate + branch | ✅ done | wiped untrusted `aws/`, scaffolded `prod/`, new branch |
| 1 | Scaffold via AgentCore CLI | ✅ done | `npm i -g @aws/agentcore`; `agentcore create` with `LangChain_LangGraph` + Container build |
| 2 | Local dev validation | ✅ done | `agentcore dev -p 8090` — graph + HITL verified end-to-end inside container |
| 3 | Durable checkpointer | ✅ done | `langgraph-checkpoint-aws.DynamoDBSaver` + CDK provisions table + grants IAM |
| 4a | yfinance + CRM via Gateway | ✅ done | Lambda-backed MCP servers behind `market-gw`; local-dev fallback when `GATEWAY_URL` unset |
| 4b | AgentCore Browser | ⏳ | replace Playwright stdio tool with native Browser service |
| 4c | AgentCore Memory | ⏳ | replace in-container memory tools with managed Memory |
| 5 | IAM, Secrets Manager, observability | ⏳ | Anthropic/OpenAI/Pinecone keys → Secrets Manager; finalize execution role; OTel → CloudWatch |
| 6 | First `agentcore deploy` to AWS | ⏳ | smoke test in cloud; verify CFN outputs |
| 7 | Promote / refine CDK | ⏳ | shared infra stack, CI/CD wiring |
| 8 | Streamlit frontend | ⏳ | App Runner (or ECS Fargate) hosting Streamlit, calls Runtime via HTTPS + Cognito |

## What's done

### Phase 0 — clean slate (commit `3832286`)
- Wiped previous untrusted `market-intelligence-agent/aws/`
- New branch `feat/agentcore-prod` off `master`
- Scaffolded `prod/{agent,frontend,voice,jobs/ingest,iam,infra}/`

### Phase 1 — AgentCore scaffold (commit `aebc90b` partial)
- Installed `@aws/agentcore` v0.14.1 (npm-distributed CLI; pip toolkit is deprecated)
- `agentcore create --framework LangChain_LangGraph --protocol HTTP --model-provider Bedrock --memory none --build Container`
- Generated `prod/agent/{agentcore/, app/agent/, README.md, AGENTS.md}`

### Phase 2 — local dev validation (commit `aebc90b`)
- Copied dev agent code into `prod/agent/app/agent/app/{agent,core}/` — nested layout preserves `from app.agent.X` imports (28 lines, no refactor needed)
- Rewrote `main.py` as the AgentCore `@app.entrypoint` — supports both fresh prompts and HITL `Command(resume=...)`
- Updated `pyproject.toml` with prod deps (langchain-openai, pinecone, tavily-python, yfmcp, ...), regenerated `uv.lock`
- **Disabled MCP stdio tools** (CRM, yfinance, filesystem, browser) in the prod copy — they need `uvx`/`npx` which aren't in the slim container. Phase 4 restores them via Gateway.
- Verified inside the container on `localhost:8090`:
  - simple prompt → `status: completed`
  - email prompt → `status: interrupted` with `pending_tool_calls`
  - `{"resume":"reject"}` → cancel + acknowledgement
- Discovered: `agentcore dev` must run from `prod/agent/`, not the build context.

### Phase 3 — durable checkpointer (commit `1a926da`)
- Added `langgraph-checkpoint-aws >= 1.0.7` (provides `DynamoDBSaver`)
- `main.py` checkpointer factory: `DDB_CHECKPOINT_TABLE` env → DynamoDB, else MemorySaver
- CDK stack (`cdk/lib/cdk-stack.ts`) now:
  - Provisions the table: composite PK/SK, `ttl` attribute, PITR + SSE on, `PAY_PER_REQUEST`, `RemovalPolicy.RETAIN`
  - Injects `DDB_CHECKPOINT_TABLE` env var into the runtime
  - Grants minimum DDB perms (`GetItem`, `PutItem`, `Query`, `BatchGetItem`, `BatchWriteItem`) on the runtime exec role, scoped to the table ARN
  - New CFN outputs: `CheckpointTableArn`, `CheckpointTableWiredToagent`
- `npx tsc --noEmit` clean; local dev still passes with the MemorySaver fallback log line

### Phase 4a — Gateway + yfinance + CRM (commit `d5156ef`)
- Two Lambda MCP servers under `prod/agent/app/{yfinance_tool,crm_tool}/` using `mcp.server.fastmcp.FastMCP`. CRM bundles `customers.db` (read-only via `?mode=ro&immutable=1`); yfinance applies a 10 s socket timeout.
- `agentcore.json` `market-gw` Gateway gains two `lambda`-type targets with inline `toolDefinitions` (3 yfinance tools + `read_query`) and `compute.implementation` blocks pointing at the new directories.
- `tools/mcp_clients/registry.py` rewritten to `streamable_http` `MultiServerMCPClient` keyed on `GATEWAY_URL`. Unset → empty tool list + warning log (local-dev path); `select_tool` returns a no-op tool whose `.func` raises only if invoked.
- `tools/__init__.py` re-enables yfinance + CRM imports behind a try/except; only extends `TOOLS` when the Gateway registry actually produced tools. `READ_ONLY_TOOLS` keeps the full name union.
- CDK stack instantiates `AgentCoreMcp` and publishes `GATEWAY_URL` (from `gateways.get('market-gw').attrGatewayUrl`) into every runtime alongside the Phase 3 `DDB_CHECKPOINT_TABLE`.
- `npx tsc --noEmit` clean; `agentcore validate` clean. Smoke tests deferred (per project convention — Gateway-bound tests are first-class in Phase 6 against the real deployed endpoint).

## What's next — Phase 4 design questions

Open decisions before starting:

1. **Lambda-backed vs OpenAPI-backed Gateway targets.** Lambda is the natural fit for the Python tools — each tool becomes a small Lambda; Gateway exposes them as MCP tools.
2. **Browser tool — keep or replace?** AgentCore has a native **Browser** service that's purpose-built. Likely cheaper / faster than Playwright in a Lambda. Decision: probably swap.
3. **Filesystem tool — keep or replace?** In a serverless world, "filesystem" usually means S3. Decision: probably swap to an S3-backed tool, or drop entirely if not used.
4. **yfinance + CRM** — straightforward Lambdas wrapping the existing logic.

## Reference

- Local dev: see `prod/agent/README.md`
- Memory note for AI tools: `[[project-agentcore-prod-inflight]]`
- AWS doc that drove Phase 3: <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ddb-langgraph-checkpoint.html>
