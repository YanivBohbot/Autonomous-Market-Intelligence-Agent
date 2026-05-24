# `prod/iac/` — AWS CDK (Python) app

Infrastructure-as-code for the Autonomous Market Intelligence Agent deployment, per `prod/SPEC.md` §3 and §8.

## Stacks (deploy order follows the dependency graph in SPEC §8.2)

1. `MiaIdentityStack` — KMS CMK `alias/mia`, shared IAM policy fragments.
2. `MiaStorageStack` — S3 buckets (`mia-workspace`, `mia-data`), bucket policies (TLS-only).
3. `MiaSecretsStack` — Secrets Manager entries (values injected outside CDK).
4. `MiaMcpLambdasStack` — three Lambda functions (`yfinance`, `filesystem`, `sqlite-crm`).
5. `MiaGatewayStack` — AgentCore Gateway + 3 Lambda targets.
6. `MiaRuntimeStack` — ECR repo + AgentCore Runtime + AgentCore Memory.
7. `MiaObservabilityStack` — CloudWatch alarms, AWS Budgets, log retention.

## Usage

```bash
cd prod/iac
uv venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
uv pip install -r requirements.txt
cdk bootstrap            # one-time per account/region
cdk synth                # render CloudFormation locally
cdk deploy --all         # deploy everything
cdk deploy MiaRuntimeStack    # deploy a single stack
```

## Environment

The app reads two env vars at synth/deploy time:

| Env var | Default | Meaning |
|---|---|---|
| `CDK_DEFAULT_ACCOUNT` | (from creds) | AWS account ID |
| `CDK_DEFAULT_REGION` | `us-east-1` | Target region (must match SPEC.md) |

Secrets are **not** stored in CDK code. After `cdk deploy MiaSecretsStack` creates the empty Secrets Manager entries, populate them via:

```bash
aws secretsmanager put-secret-value --secret-id mia/openai-api-key --secret-string "$OPENAI_API_KEY"
# ...repeat for each secret
```
