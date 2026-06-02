# aws-dev-toolkit:agentcore

**Type:** Domain / implementation
**Plugin:** aws-dev-toolkit

## What it is
Deep-dive guidance for the Amazon Bedrock AgentCore platform — service selection,
deployment, and production operations (Runtime, Memory, Gateway, Identity, Browser, etc.).

## How we used it on this project
The backbone of the entire AWS deployment (the "locked design" — Option A: AgentCore
Runtime + Gateway w/ 3 Lambda MCP targets + AgentCore Memory). Concrete outputs:

- **Runtime:** `mia_runtime_demo-...` hosting the LangGraph agent
- **Gateway:** fronting 3 Lambda MCP targets (yfinance, sqlite-crm, filesystem)
- **Memory:** durable checkpointer via `AgentCoreMemorySaver` (HITL across containers)
- **Browser (Phase 8):** Custom Browser `mia_browser_demo-3zRFIUdmM7` + S3 recordings,
  the `mia-browser-demo` CDK stack, and `notes/agentcore-browser-sdk-surface.md`

Stacks: `mia-storage / secrets / mcp-lambdas / gateway / runtime / observability / browser`.
