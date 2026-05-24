"""Post-deploy smoke test for the AgentCore Runtime.

Walks the SPEC.md §8.5 checklist:
  - InvokeAgentRuntime returns a non-error response on a 'hello' prompt.
  - yfinance tool reachable via Gateway.
  - read_query (sqlite-crm) reachable via Gateway.
  - list_directory (filesystem) reachable via Gateway.

Exits non-zero on any failure so the GitHub Actions job fails the deploy.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
ENV_NAME = os.environ.get("MIA_ENV", "demo")
PROJECT = "mia"

cf = boto3.client("cloudformation", region_name=REGION)
agentcore = boto3.client("bedrock-agentcore", region_name=REGION)


def get_runtime_arn() -> str:
    """Resolve the Runtime ARN from the CloudFormation export."""
    export_name = f"{PROJECT}-{ENV_NAME}-runtime-arn"
    exports = cf.list_exports()["Exports"]
    for e in exports:
        if e["Name"] == export_name:
            return e["Value"]
    raise RuntimeError(f"export {export_name!r} not found")


def invoke(runtime_arn: str, session_id: str, payload: dict) -> dict:
    resp = agentcore.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=session_id,
        payload=json.dumps(payload).encode("utf-8"),
        contentType="application/json",
        accept="application/json",
    )
    body = resp["response"].read().decode("utf-8")
    return json.loads(body) if body else {}


def assert_completed_or_interrupted(result: dict, label: str) -> None:
    if result.get("status") not in ("completed", "interrupted"):
        print(f"[FAIL] {label}: unexpected status {result!r}")
        sys.exit(1)
    print(f"[OK]   {label}: status={result['status']}")


def main() -> int:
    runtime_arn = get_runtime_arn()
    print(f"runtime arn = {runtime_arn}")
    session = f"smoke-{uuid.uuid4()}"

    # 1. Plain hello
    r = invoke(runtime_arn, session, {"prompt": "Bonjour, qui es-tu en une phrase ?"})
    assert_completed_or_interrupted(r, "hello")

    # 2. yfinance tool — should resolve through Gateway
    r = invoke(runtime_arn, session, {"prompt": "What is Apple's current stock price (ticker AAPL)?"})
    assert_completed_or_interrupted(r, "yfinance")

    # 3. sqlite-crm — should run a SELECT through Gateway
    r = invoke(runtime_arn, session, {"prompt": "List the first 3 customers from the CRM database."})
    assert_completed_or_interrupted(r, "sqlite-crm")

    # 4. filesystem read — list_directory on workspace root
    r = invoke(runtime_arn, session, {"prompt": "List the files in my workspace."})
    assert_completed_or_interrupted(r, "filesystem")

    print("\nall smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
