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

## Phase status

See [`../../docs/AGENTCORE_DEPLOYMENT.md`](../../docs/AGENTCORE_DEPLOYMENT.md) for the full multi-phase plan and what's done so far.
