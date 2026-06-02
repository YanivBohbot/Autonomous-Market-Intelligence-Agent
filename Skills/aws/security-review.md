# aws-dev-toolkit:security-review

**Type:** AWS — security audit
**Plugin:** aws-dev-toolkit

## What it is
Reviews AWS infrastructure / IaC for security issues — IAM policies, exposed resources,
encryption, misconfigurations — and proposes hardening + SCPs.

## How we used it on this project
Produced `prod/SPEC.md` Section 4 (the Phase 3 security review). Outputs:

- **5 architectural findings F1–F5** (none critical) — captured in memory `project_deployment_security`
- **Endpoint-exposure table** — Runtime + Gateway are SigV4-required; S3 Block-Public-Access
  ON; Lambda Function URLs disabled
- **Encryption decision** — AWS-managed keys at rest in v1 (no customer-managed KMS;
  KMS stack was later dropped, commit `78ce4bc`)
- **9 baseline SCPs** (Section 4.8) — e.g. DenyRootAccessKeyCreation,
  DenyLambdaFunctionURLPublicAuth, RequireIAMSSOForConsoleLogin
