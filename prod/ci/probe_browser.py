"""Live integration probe for AgentCore Browser.

Costs money. Run manually after the BrowserStack + RuntimeStack are deployed.

    export MIA_BROWSER_BUCKET=<bucket-from-cdk-output>
    uv run python prod/ci/probe_browser.py

Asserts:
  1. browser_navigate("https://example.com") returns without error.
  2. browser_snapshot() returns text containing "Example Domain".
  3. browser_take_screenshot("probe-evidence.png") writes the file.
  4. Within 60s, S3 recording bucket has >=1 object under sessions/.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
RUNTIME_ARN = os.environ.get(
    "MIA_RUNTIME_ARN",
    "arn:aws:bedrock-agentcore:us-east-1:584246028688:runtime/mia_runtime_demo-tio2ELGaQB",
)
RECORDING_BUCKET = os.environ.get("MIA_BROWSER_BUCKET", "")

rt = boto3.client("bedrock-agentcore", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)

BODY_SID = f"probe-browser-{uuid.uuid4()}"
PASS = 0
FAIL = 0


def invoke(query: str) -> dict:
    rs = f"pg-{uuid.uuid4()}"
    t0 = time.time()
    resp = rt.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=rs,
        payload=json.dumps({"query": query, "session_id": BODY_SID}).encode("utf-8"),
        contentType="application/json",
        accept="application/json",
    )
    body = resp["response"].read().decode("utf-8")
    r = json.loads(body) if body else {}
    r["_runtime_session"] = rs
    r["_elapsed"] = round(time.time() - t0, 2)
    return r


def case(label: str, ok: bool, r: dict, snippet: int = 240) -> None:
    global PASS, FAIL
    flag = "[OK]  " if ok else "[FAIL]"
    print(f"\n{flag} {label}")
    rs = r.get("_runtime_session") or ""
    if rs:
        print(f"        runtimeSessionId={rs[:24]}...")
    print(f"        status={r.get('status')}  elapsed={r.get('_elapsed')}s")
    pending = r.get("pending_tool_calls")
    if pending:
        for tc in pending:
            print(f"        pending: {tc.get('name')}  args={tc.get('args')}")
    txt = (r.get("response") or "")[:snippet]
    if txt:
        print(f"        > {txt}")
    PASS += int(ok)
    FAIL += int(not ok)


def main() -> int:
    if not RECORDING_BUCKET:
        print("MIA_BROWSER_BUCKET env var must be set", file=sys.stderr)
        return 2

    print(f"runtime          = {RUNTIME_ARN}")
    print(f"recording bucket = {RECORDING_BUCKET}")
    print(f"body.session_id  = {BODY_SID}")
    print("Every invoke uses a FRESH runtimeSessionId — exactly like the Console playground.")
    print("=" * 78)

    # 1. Navigate to example.com — accept any non-error (completed) response
    r = invoke("Use browser_navigate to open https://example.com and tell me you did it.")
    case("navigate example.com", r.get("status") == "completed", r)

    # 2. Snapshot — assert "Example Domain" appears in the agent response
    r = invoke("Now call browser_snapshot and tell me the page title.")
    case(
        "snapshot contains 'Example Domain'",
        r.get("status") == "completed" and "Example Domain" in (r.get("response") or ""),
        r,
    )

    # 3. Screenshot — accept any non-error (completed) response
    r = invoke("Now call browser_take_screenshot with filename 'probe-evidence.png' and confirm.")
    case("screenshot probe-evidence.png", r.get("status") == "completed", r)

    # 4. Poll S3 recording bucket for sessions/ prefix — up to 60s
    print(f"\nPolling s3://{RECORDING_BUCKET}/sessions/ for up to 60s...")
    deadline = time.time() + 60
    found = 0
    while time.time() < deadline:
        resp = s3.list_objects_v2(Bucket=RECORDING_BUCKET, Prefix="sessions/")
        found = resp.get("KeyCount", 0)
        if found > 0:
            break
        time.sleep(5)
    case(
        f"recording bucket has >=1 object under sessions/ (found {found})",
        found > 0,
        {"status": "completed", "_elapsed": None},
    )

    print("\n" + "=" * 78)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
