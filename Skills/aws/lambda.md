# aws-dev-toolkit:lambda

**Type:** AWS — Lambda design
**Plugin:** aws-dev-toolkit

## What it is
Design, build, and optimize AWS Lambda functions — event sources, packaging, sizing,
cold starts.

## How we used it on this project
The 3 MCP servers behind AgentCore Gateway are Lambda functions (`prod/lambdas/`):

- `mia-mcp-yfinance` — outbound HTTPS only
- `mia-mcp-filesystem` — S3-backed (`mia-workspace`), replaces stdio filesystem server
- `mia-mcp-sqlite-crm` — reads `customers.db` from `mia-data`

Python 3.12, ARM64, 256 MB, ~500 ms each. A key bugfix lived here:
`5c402f3 fix(lambdas): read tool name from Gateway client_context, not event`.
