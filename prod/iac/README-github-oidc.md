# GitHub Actions OIDC setup for CDK deploys

The `.github/workflows/deploy.yml` pipeline assumes an IAM role via OIDC instead of
using long-lived access keys. This document records how the role was set up so the
configuration is reproducible.

## Resources created (one-time, manual)

| Resource | Identifier |
|---|---|
| OIDC provider | `arn:aws:iam::584246028688:oidc-provider/token.actions.githubusercontent.com` |
| Deploy role | `arn:aws:iam::584246028688:role/mia-github-deploy` |
| Trust policy | `trust-github-oidc.json` (in this folder) |
| Inline policy | `policy-assume-cdk.json` (in this folder) |
| Repo secret `AWS_DEPLOY_ROLE_ARN` | Role ARN above |
| Repo secret `AWS_ACCOUNT_ID` | `584246028688` |

## Trust scope

The role can only be assumed by GitHub Actions runs from:

- Repo: `YanivBohbot/Autonomous-Market-Intelligence-Agent`
- Branch: `master`

Anyone else (fork, feature branch, different repo) gets denied. Edit
`trust-github-oidc.json` and re-apply the trust policy to allow more refs.

## Permission scope

The role itself has minimal permissions — it can:

1. Assume the four CDK bootstrap roles (`cdk-hnb659fds-*`).
2. Read CloudFormation exports / describe stacks (used by `prod/ci/smoke.py`).
3. Call `bedrock-agentcore:InvokeAgentRuntime` on `mia-*` runtimes (for the smoke step).

All actual resource creation flows through the CDK bootstrap roles, which already
have the necessary permissions from `cdk bootstrap`.

## Re-applying after a trust policy change

```bash
aws iam update-assume-role-policy \
  --role-name mia-github-deploy \
  --policy-document file://prod/iac/trust-github-oidc.json

aws iam put-role-policy \
  --role-name mia-github-deploy \
  --policy-name AssumeCDKBootstrapAndInvokeAgent \
  --policy-document file://prod/iac/policy-assume-cdk.json
```

## Re-creating from scratch

```bash
# 1. OIDC provider (one per AWS account)
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# 2. Role
aws iam create-role \
  --role-name mia-github-deploy \
  --assume-role-policy-document file://prod/iac/trust-github-oidc.json

# 3. Inline policy
aws iam put-role-policy \
  --role-name mia-github-deploy \
  --policy-name AssumeCDKBootstrapAndInvokeAgent \
  --policy-document file://prod/iac/policy-assume-cdk.json

# 4. GH secrets
gh secret set AWS_DEPLOY_ROLE_ARN  --body "arn:aws:iam::584246028688:role/mia-github-deploy"
gh secret set AWS_ACCOUNT_ID       --body "584246028688"
```

## Optional

`MIA_ALERT_EMAIL` — set as a repo secret if you want CloudWatch alarm SNS
notifications. The observability stack treats it as optional; without it the
SNS topic has no subscribers.
