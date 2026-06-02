# aws-dev-toolkit:aws-architect

**Type:** AWS — architecture design/review
**Plugin:** aws-dev-toolkit

## What it is
Design and review AWS architectures following Well-Architected Framework principles —
service selection, trade-offs, best practices.

## How we used it on this project
Produced `prod/SPEC.md` Section 3 (the component table + data-flow diagram) and the locked
"Option A" decision. Key architectural choices it drove, each with a recorded rationale:

- AgentCore Memory **over** SQLite-on-EFS — avoids a VPC + NAT GW (~$33/mo floor)
- **No VPC in v1** — all services managed-public
- Region `us-east-1`, ARM64 everywhere (Runtime 1 vCPU/2 GB, Lambdas 256 MB)
- One stack per concern: storage / secrets / mcp-lambdas / gateway / runtime / observability

See the "Decisions log" table at the bottom of `prod/SPEC.md`.

## Storage design (S3)
The `mia-storage-demo` stack's buckets, designed as part of the architecture:

- `mia-data-...` — CRM `customers.db` snapshot + RAG PDFs (read-only to the agent)
- `mia-workspace-...` — replaces local `data/workspace/` (filesystem tool RW)
- `mia-browser-recordings-...` — Phase 8 AgentCore Browser recordings (KMS, 30-day lifecycle)

All: Block Public Access ON, versioning, SSE; access scoped per-prefix in the IAM roles.
