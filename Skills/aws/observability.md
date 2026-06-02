# aws-dev-toolkit:observability

**Type:** AWS — observability design
**Plugin:** aws-dev-toolkit

## What it is
Design CloudWatch metrics/logs/alarms/dashboards, X-Ray tracing, and log aggregation.

## How we used it on this project
The dedicated `mia-observability-demo` CDK stack and the logging/tracing plan in
`prod/SPEC.md`:

- CloudWatch Logs from Runtime + Lambdas + Gateway, 30-day retention
- **AgentCore Observability** traces (default-on) for agent runs
- Logger redaction of known secret keys (security finding follow-up)

Used in operations too — e.g. tailing
`/aws/bedrock-agentcore/runtimes/...` to confirm one Browser session served a multi-turn flow.
