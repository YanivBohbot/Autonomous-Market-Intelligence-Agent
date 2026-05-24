# `prod/ci/` — deploy / rollback / smoke-test runbook

## One-time setup (before first `cdk deploy`)

### 1. Bootstrap CDK in the target account

```bash
cd prod/iac
cdk bootstrap aws://<ACCOUNT_ID>/us-east-1
```

### 2. Create the GitHub OIDC trust + deploy role

The pipeline uses GitHub OIDC to assume an IAM role — no long-lived AWS keys
in repo secrets. Create the role once via the AWS Console or `aws iam`:

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

Then create `GitHubDeployRole` trusted by `repo:YanivBohbot/Autonomous-Market-Intelligence-Agent:ref:refs/heads/master`
with the AdministratorAccess managed policy attached (demo only — tighten for real prod).

### 3. Add GitHub secrets

In `Settings → Secrets and variables → Actions`, set:

- `AWS_DEPLOY_ROLE_ARN`  — ARN of the role created above.
- `AWS_ACCOUNT_ID`        — Twelve-digit account ID.
- `MIA_ALERT_EMAIL`       — Address to receive budget/security alerts.

### 4. Populate Secrets Manager values

After the first `cdk deploy` of `MiaSecretsStack`, the entries exist with empty
values. Fill them in:

```bash
aws secretsmanager put-secret-value --secret-id mia/openai-api-key   --secret-string "$OPENAI_API_KEY"
aws secretsmanager put-secret-value --secret-id mia/pinecone-api-key --secret-string "$PINECONE_API_KEY"
aws secretsmanager put-secret-value --secret-id mia/tavily-api-key   --secret-string "$TAVILY_API_KEY"
aws secretsmanager put-secret-value --secret-id mia/email-password   --secret-string "$EMAIL_PASSWORD"
```

### 5. Upload static data

```bash
aws s3 cp market-intelligence-agent/customers.db s3://mia-data-<account>/customers.db --sse aws:kms
# upload PDFs into s3://mia-data-<account>/pdfs/ for RAG ingestion (separate job, future)
```

## Routine deploys

Just push to `master`. The pipeline runs `test → deploy → smoke`. To redeploy
without code changes, use the `workflow_dispatch` button in Actions.

## Rollback

```bash
# Find the previous successful deployment
git log --oneline

# Revert the bad commit and push — the pipeline redeploys the previous state.
git revert <bad-sha> && git push

# Or: redeploy a single stack from a local checkout of a known-good commit.
git checkout <good-sha>
cd prod/iac && cdk deploy mia-runtime-demo
```

CDK retains the previous CloudFormation template; `cdk deploy` does a normal
update. There's no separate rollback command — re-deploying old IaC IS the
rollback.

## Smoke test

`prod/ci/smoke.py` runs four `InvokeAgentRuntime` checks (hello / yfinance /
sqlite-crm / filesystem). To run it locally against a deployed env:

```bash
export AWS_REGION=us-east-1
export MIA_ENV=demo
pip install boto3
python prod/ci/smoke.py
```
