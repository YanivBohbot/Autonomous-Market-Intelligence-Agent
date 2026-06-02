# aws-dev-toolkit:aws-plan

**Type:** AWS — end-to-end planning (umbrella skill)
**Plugin:** aws-dev-toolkit

## What it is
End-to-end AWS architecture planning: discovery → design → security review → cost estimate
→ SCP recommendations. Orchestrates the more focused AWS skills below.

## How we used it on this project
This is the skill that produced the shape of **`prod/SPEC.md`** — the deployment spec runs
exactly its phases:

- **Discovery:** demo scale, keep OpenAI, tight budget (<$200/mo), v1 = text + MCP only
  (captured in memory `project_deployment_discovery`)
- **Design:** Option A — AgentCore Runtime + Gateway (3 Lambda targets) + Memory, no VPC
- **Security review:** Section 4 — 5 findings + SCPs (see [security-review](security-review.md))
- **Cost estimate:** Section 6 (see [cost-check](cost-check.md))
- **SCPs:** Section 4.8 — 9 baseline statements

Memory trail: `project_deployment_goal`, `project_deployment_design`, `project_deployment_plan_final`.

## Alternatives considered
Part of planning was weighing options side-by-side (recorded in `prod/SPEC.md`'s
"alternatives considered" + decisions-log sections):

- AgentCore Memory **vs** SQLite-on-EFS → Memory (no VPC/NAT floor cost)
- OpenAI **vs** Bedrock models → OpenAI (zero code change, budget)
- Streamlit UI deferred: CloudFront + Lambda Web Adapter **vs** App Runner
- Pinecone **vs** OpenSearch Serverless → kept Pinecone for v1
