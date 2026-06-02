# aws-dev-toolkit:cost-check

**Type:** AWS — cost analysis/optimization
**Plugin:** aws-dev-toolkit

## What it is
Estimate costs for new architectures, analyze spend, and find savings — service-by-service
breakdowns against a budget.

## How we used it on this project
Produced `prod/SPEC.md` Section 6 (the cost table) and stayed under the $200/mo cap:

- **~$3 idle, ~$10–25 light demo, ~$60–175 peak** — OpenAI tokens dominate
- AgentCore $200 Free Tier credits cover ~2 months light
- Drove cost-shaped architecture decisions: no VPC (avoid NAT GW ~$33/mo), AgentCore Memory
  over EFS, Lambda free-tier for MCP tools

Memory: `project_deployment_cost`.
