# Production agent — AgentCore Runtime

Containerized LangGraph agent deployed to **Amazon Bedrock AgentCore Runtime** (us-east-1).

The source agent code is **copied** from the parent dev project at branch-cut time (Option B in the deployment plan). Re-sync manually from `../../app/agent/` when promoting a new dev version to prod.

## Layout

```
prod/agent/
├── agentcore/
│   ├── agentcore.json        # AgentCore CLI project spec
│   ├── aws-targets.json      # deploys to us-east-1
│   ├── .env.local            # local-dev secrets (gitignored)
│   └── cdk/                  # CDK stack: provisions runtime + DDB table
├── app/agent/                # container build context — becomes /app at runtime
│   ├── Dockerfile            # python:3.12-slim + uv sync
│   ├── main.py               # BedrockAgentCoreApp entrypoint
│   ├── pyproject.toml        # pinned prod deps (uv-managed)
│   ├── uv.lock
│   └── app/                  # YOUR code (mirrors dev layout)
│       ├── agent/            #   graph, nodes, tools, prompts, memory
│       └── core/             #   config, logging
└── README.md (this file)
```

## Local development

Requires: Docker Desktop running, Node 20+, AWS credentials, Bedrock model access (Claude Sonnet 4 enabled in us-east-1).

```powershell
# install the AgentCore CLI globally (one-time)
npm install -g @aws/agentcore

# from prod/agent/ — NOT prod/agent/app/agent/
cd market-intelligence-agent\prod\agent

# start local dev container on port 8090 (8080 collides with the dev Streamlit stack)
agentcore dev -p 8090 --logs
```

In a second terminal:

```powershell
cd market-intelligence-agent\prod\agent

# new prompt
agentcore dev -p 8090 "What is Apple's stock price?"

# HITL approve/reject resume (use the running container's session-id header)
curl -X POST http://localhost:8090/invocations `
  -H "Content-Type: application/json" `
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: local-dev-session" `
  -d '{"resume":"reject"}'
```

The local checkpointer defaults to `MemorySaver` (volatile). To exercise the DynamoDB path locally, set `DDB_CHECKPOINT_TABLE` in `agentcore/.env.local` and point at a DDB-Local container or a real table.

### After editing `pyproject.toml`

The Dockerfile uses `uv sync --frozen`, so a missing/stale `uv.lock` means dependencies silently don't install. Always regenerate after edits:

```powershell
cd market-intelligence-agent\prod\agent\app\agent
uv lock
```

## Deploy (first time, manual)

> **Not yet executed.** This is the target for Phase 6.

```powershell
cd market-intelligence-agent\prod\agent
agentcore deploy
```

That command:
1. Builds the container, pushes to ECR
2. Synthesizes the CDK stack (provisions: Runtime, ECR repo, IAM role, **DynamoDB checkpoint table**)
3. Calls CloudFormation to deploy
4. Outputs the runtime ARN + checkpoint table name

## Architecture decisions

| Concern | Choice | Rationale |
|---|---|---|
| Build type | Container | Dep tree too heavy for CodeZip (pinecone, langchain-pinecone, mcp libs) |
| Code source | Copy of dev | Snapshot for prod stability; manual re-sync |
| Layout | Nested `app/agent/app/agent/` | Preserves `from app.agent.X` imports — zero refactor |
| Checkpointer | `langgraph-checkpoint-aws.DynamoDBSaver` | Serverless, pay-per-request, TTL'd, S3 offload for large state |
| Memory store | MemorySaver locally / DynamoDB in cloud | Env-driven switch via `DDB_CHECKPOINT_TABLE` |
| MCP tools | Disabled in Phase 2, restored via **AgentCore Gateway** in Phase 4 | Stdio MCPs don't survive in serverless containers (no `uvx`/`npx`) |

## Gateway tools (Phase 4a)

The `yfinance_*` and `read_query` (CRM) tools live in Lambda-backed MCP servers under `prod/agent/app/yfinance_tool/` and `prod/agent/app/crm_tool/`, registered as targets of the `market-gw` AgentCore Gateway in `agentcore/agentcore.json`.

At runtime the agent reads `GATEWAY_URL` (injected by the CDK stack) and connects to the Gateway over `streamable_http` via `MultiServerMCPClient`. In **local dev** `GATEWAY_URL` is unset — the registry logs `[registry] GATEWAY_URL unset — Gateway tools skipped` and the agent runs with email + memory tools only. The Gateway-backed tools come alive only after Phase 6 (`agentcore deploy`).

To exercise the Gateway path locally against a deployed dev stack, set `GATEWAY_URL` in `agentcore/.env.local`.

## Browser tool (Phase 4b)

The `browser_navigate`, `browser_snapshot`, and `browser_take_screenshot` tools are powered by **Amazon Bedrock AgentCore Browser** — managed headless Chromium that runs on AWS. The container ships only the Playwright Python client (no local Chromium binary), connects to the remote browser over CDP via WebSocket, and uploads screenshots to a dedicated S3 bucket.

- Sessions are **per-call**: each tool invocation opens a fresh `StartBrowserSession`, navigates, returns, closes.
- Screenshots land in `$SCREENSHOT_BUCKET` under `screenshots/<uuid>.png`. The tool returns a **1-hour pre-signed URL** to the LLM. Lifecycle rule deletes objects after 30 days.
- Gated on `BROWSER_ENABLED=true`. The CDK stack injects this in cloud; locally the var is unset so `tools/__init__.py` never even imports the browser module — the LLM doesn't see the tools.

## Memory store (Phase 4c)

The agent's three memory tools (`save_memory`, `recall_memory`, `list_memories`) write to a LangGraph `BaseStore`. In production that store is **AgentCore Memory** (`AgentCoreMemoryStore`) — a managed long-term memory service with semantic indexing. The Memory resource (name `user_facts`, 90-day event expiry, SEMANTIC strategy) is declared in `agentcore/agentcore.json` and provisioned automatically by the CDK `AgentCoreApplication` L3 construct, which also grants the runtime the needed `bedrock-agentcore:*` permissions and injects `MEMORY_USER_FACTS_ID` as an env var.

Local dev: `MEMORY_USER_FACTS_ID` unset → falls back to `InMemoryStore` (volatile, in-process). The memory tools themselves are unchanged — they use `InjectedStore()` and receive whatever store the graph was compiled with.

The Phase 3 DynamoDB checkpointer is kept for per-thread conversational state — only the long-term cross-thread store moves to AgentCore Memory.

## Secrets & observability (Phase 5)

Real API-key secrets (`OPENAI_API_KEY`, `PINECONE_API_KEY`, `TAVILY_API_KEY`, `EMAIL_PASSWORD`) live in a single **AWS Secrets Manager** JSON bundle named `agent/api-keys`. The bundle is provisioned with placeholder `"REPLACE_ME"` values by CDK; **fill the real values via the AWS Console after the first deploy** (Secrets Manager → `agent/api-keys` → Retrieve secret value → Edit). The secret has `RemovalPolicy.RETAIN` so a stack tear-down doesn't wipe your keys.

At container boot, `app/bootstrap.py` reads `API_KEYS_SECRET_ARN` (injected by CDK), fetches the JSON, and copies every key into `os.environ` **before** `app.core.config.Settings()` runs. Local dev has the var unset → bootstrap logs "skipping" and `.env.local` continues to provide the keys.

Non-secret config (model IDs, SMTP host, voice-stack dummies) is set as plain env vars in the CDK stack. The voice keys (`LIVEKIT_*`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`) get literal `"unused-in-prod-agent"` values — the shared `Settings` schema requires them but the agent runtime doesn't use them.

Observability is mostly AgentCore-native: the runtime exports OTel to CloudWatch + X-Ray automatically (the container ships `aws-opentelemetry-distro`), and `LangchainInstrumentor()` in `main.py` annotates LangChain spans. CDK adds an explicit log group `/aws/bedrock-agentcore/runtimes/agent` with 30-day retention; the ARN is in stack outputs.

## Phase status

See [`../../docs/AGENTCORE_DEPLOYMENT.md`](../../docs/AGENTCORE_DEPLOYMENT.md) for the full multi-phase plan and what's done so far.
