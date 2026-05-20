# Production deployment — AgentCore

This folder holds **deployment artifacts only**. The agent source code lives in the parent `market-intelligence-agent/` (single source of truth — do not duplicate code here).

## Layout

- `agent/` — Dockerfile, AgentCore entrypoint, prod-pinned requirements
- `iam/` — IAM execution + trust policies for the AgentCore Runtime role
- `infra/` — CDK stack (added in Phase 7)

## Deploy phases

1. Scaffold with AgentCore CLI (`agent/`)
2. Local dev validation (`agentcore dev`)
3. Swap SqliteSaver for a durable checkpointer
4. Wrap MCP tools via AgentCore Gateway
5. IAM + Secrets Manager + observability
6. First cloud deploy (`agentcore deploy`)
7. Promote to CDK IaC (`infra/`)
8. Streamlit frontend on App Runner / ECS Fargate
