# aws-dev-toolkit:iam

**Type:** AWS — IAM design/review
**Plugin:** aws-dev-toolkit

## What it is
Design and review IAM — least-privilege policies, roles, permission boundaries, SCPs, trust
policies, and OIDC federation.

## How we used it on this project
Produced `prod/SPEC.md` Section 4.1 (least-privilege role design) and the GitHub Actions
OIDC setup:

- **3 execution roles:** `mia-runtime-exec`, `mia-gateway-exec`, `mia-lambda-mcp-exec`
- **Decision:** three per-function Lambda roles, not one shared — smaller blast radius
- Trust policies scoped to exact service principals; **no human IAM users** (SSO only)
- **GitHub Actions OIDC** — `mia-github-deploy` role assumed via
  `aws-actions/configure-aws-credentials@v4` (memory `project_github_oidc_done`)

See `prod/iac/README-github-oidc.md`.
