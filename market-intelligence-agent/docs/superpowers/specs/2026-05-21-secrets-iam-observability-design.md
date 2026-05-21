# Secrets, IAM least-priv, Observability — Design Spec (Phase 5)

**Date:** 2026-05-21
**Status:** Approved (pending implementation)
**Branch:** `feat/agentcore-prod`
**Depends on:** Phase 4c complete (commit `363187e`).

## Goal

Make the prod agent deploy-ready by:
1. Moving the 4 real API-key secrets out of code/env-file into **AWS Secrets Manager**.
2. Tightening **IAM** so the runtime exec role grants only what's needed, scoped to specific ARNs.
3. Wiring **observability** — AgentCore Runtime auto-exports OTel to CloudWatch + X-Ray; we add a CloudWatch Log Group output and ensure `LangchainInstrumentor` (already in `main.py`) runs first so spans are tagged correctly.

## Secrets — what moves and what stays

| Key | Where it lives in prod | Why |
|---|---|---|
| `OPENAI_API_KEY` | Secrets Manager (JSON blob `agent/api-keys`) | Real secret |
| `PINECONE_API_KEY` | same | Real secret |
| `TAVILY_API_KEY` | same | Real secret |
| `EMAIL_PASSWORD` | same | Real secret |
| `OPENAI_MODEL`, `OPENAI_EMBEDDING_MODEL` | CDK plain env var | Non-secret config |
| `PINECONE_INDEX_NAME` | CDK plain env var | Non-secret |
| `EMAIL_SENDER`, `EMAIL_SMTP_SERVER`, `EMAIL_SMTP_PORT` | CDK plain env var | Non-secret |
| `LOG_LEVEL` | CDK plain env var (default INFO) | Non-secret |
| `LIVEKIT_*`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY` | CDK env var with literal value `"unused-in-prod-agent"` | Voice runtime owns these — agent doesn't use them but pydantic-settings requires the keys to exist |

**One JSON secret, not four**: simpler — one IAM grant, one fetch at boot, one rotation event.

## Secret lifecycle

- CDK provisions the secret with a **placeholder** JSON value: `{"OPENAI_API_KEY": "REPLACE_ME", ...}`. RemovalPolicy.RETAIN so a stack destroy doesn't wipe real keys.
- After first deploy, the operator fills the real values via AWS Console → Secrets Manager → "Retrieve secret value" → "Edit".
- The runtime fetches at boot via boto3 (`get_secret_value(SecretId=arn)`), parses JSON, populates `os.environ` for each key.
- Pydantic-settings then reads `os.environ` at `Settings()` instantiation as today.

## Boot sequence

```
main.py module load
  ├── from app.bootstrap import load_secrets   # NEW — runs first
  │     └── if API_KEYS_SECRET_ARN set: fetch + populate os.environ
  ├── from app.agent.graph import build_agent_app
  │     └── transitively imports app.core.config which reads os.environ
  └── ... rest of main.py
```

A new `app/bootstrap.py` module isolates the fetch logic and runs at import time via a single `import app.bootstrap` at the top of `main.py`. Local dev (no `API_KEYS_SECRET_ARN`) → no-op, `.env.local` continues to provide values.

## IAM hardening checklist

Existing grants (Phases 3-4b) are already scoped — auditing for completeness:
- **DDB**: GetItem/PutItem/Query/BatchGetItem/BatchWriteItem on `checkpointTable.tableArn` ✓
- **S3 screenshots**: PutObject/GetObject on `screenshotBucket.arnForObjects('*')` ✓
- **AgentCore Browser**: 4 actions on `browser/*` in this region ✓
- **AgentCore Memory**: auto-granted by the L3 construct on the memory ARN ✓
- **Secrets Manager** (NEW): `secretsmanager:GetSecretValue` on `apiKeysSecret.secretArn` only

No wildcards anywhere. No cross-account perms.

## Observability — what we add

AgentCore Runtime exports OTel automatically when the container has `aws-opentelemetry-distro` (already in `pyproject.toml`). `LangchainInstrumentor()` already runs in `main.py` line 22, so LangChain spans propagate.

CDK additions:
- A **CloudWatch Log Group** `agent-runtime` with retention 30 days, RemovalPolicy.RETAIN — outputs the log group name for easy console lookup.
- **CfnOutput** `LogGroupName`, `ApiKeysSecretArn` for operator convenience.

No custom dashboard, no alarms — those are best built once we have real prod traffic and know what to watch (Phase 7 work).

## Modified files

- **`prod/agent/app/agent/app/bootstrap.py`** — NEW. Single function `load_secrets()` called at module load.
- **`prod/agent/app/agent/main.py`** — `import app.bootstrap` at top (runs before any other imports that touch `os.environ`).
- **`prod/agent/agentcore/cdk/lib/cdk-stack.ts`**:
  - New `aws_secretsmanager.Secret` with placeholder JSON, RETAIN.
  - Inject `API_KEYS_SECRET_ARN` env var.
  - Grant `secretsmanager:GetSecretValue` on that ARN only.
  - Set plain env vars for non-secret config + dummy voice keys.
  - New CloudWatch Log Group + CfnOutputs.

## Decisions

| Question | Answer | Why |
|---|---|---|
| Secret shape | One JSON blob | Simpler IAM + boot fetch; rotation per-key not yet needed |
| Initial values | Placeholder, manual fill via Console | Keys never touch git/CI/CDK template |
| Voice keys in prod agent | CDK env var `"unused-in-prod-agent"` | Voice has its own runtime (`prod/voice/`); avoid hard-coding `Optional` in the shared config.py |
| Observability scope | Minimal (log group + outputs) | AgentCore + OTel auto-export is enough until we have traffic |

## Non-goals

- Secret rotation Lambda (defer to when we have multiple environments).
- Custom CloudWatch dashboard / alarms.
- KMS CMK on the secret (use AWS-managed key for now).
- Splitting the voice keys into their own runtime stack (Phase 8 work).

## Acceptance criteria

1. `npx tsc --noEmit` clean.
2. `agentcore validate` clean.
3. Local dev still boots — `API_KEYS_SECRET_ARN` unset → `bootstrap.load_secrets()` logs "no secret ARN, skipping" and returns. `.env.local` continues to provide keys.
4. 2 commits pushed.
