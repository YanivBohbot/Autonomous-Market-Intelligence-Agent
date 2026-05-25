"""One-shot live test of the send_email tool against the deployed runtime.

Sticky runtimeSessionId + stable body.session_id so HITL approve works.
Sends to yanivbohbot5@gmail.com (the same address as EMAIL_SENDER —
self-send is the cleanest demo because the inbox is the proof).
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:584246028688:runtime/"
    "mia_runtime_demo-tio2ELGaQB"
)
RECIPIENT = "yanivbohbot5@gmail.com"

client = boto3.client("bedrock-agentcore", region_name=REGION)


def invoke(session: str, payload: dict) -> dict:
    t0 = time.time()
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=session,
        payload=json.dumps(payload).encode("utf-8"),
        contentType="application/json",
        accept="application/json",
    )
    body = resp["response"].read().decode("utf-8")
    r = json.loads(body) if body else {}
    r["_elapsed"] = round(time.time() - t0, 2)
    return r


def main() -> int:
    session = f"email-live-{uuid.uuid4()}"
    body_sid = f"email-test-{uuid.uuid4()}"
    print(f"runtime = {RUNTIME_ARN}")
    print(f"session = {session}")
    print(f"body.session_id = {body_sid}\n")

    subject = f"AgentCore live send {int(time.time())}"
    body = "Real send from prod/ci/probe_email.py — durable saver + STARTTLS-on-587 fix."

    print(f"[1/2] sending interrupt prompt — subject={subject!r}")
    r = invoke(
        session,
        {
            "prompt": (
                f'Send an email to {RECIPIENT} with subject "{subject}" '
                f'and body "{body}". Call the send_email tool directly — '
                "do not ask me to confirm in chat."
            ),
            "session_id": body_sid,
        },
    )
    print(f"        status={r.get('status')}  elapsed={r['_elapsed']}s")
    print(f"        pending={r.get('pending_tool_calls')}")
    print(f"        > {(r.get('response') or '')[:240]}\n")

    if r.get("status") != "interrupted":
        print("[FAIL] interrupt did not fire — agent likely asked for verbal confirmation. Aborting.")
        return 1

    print("[2/2] resuming with approve")
    r = invoke(session, {"resume": "approve", "session_id": body_sid})
    print(f"        status={r.get('status')}  elapsed={r['_elapsed']}s")
    text = r.get("response") or ""
    print(f"        > {text[:400]}\n")

    if r.get("status") != "completed":
        print("[FAIL] approve returned non-completed status")
        return 1

    # Heuristic: real send returns "Email envoyé avec succès" (French success
    # message in emails.py). Simulation returns "SIMULATION SUCCÈS".
    if "SIMULATION" in text:
        print("[FAIL] Simulation gate still triggered — sender or password placeholder detected.")
        return 1
    if "Erreur critique" in text or "Erreur" in text:
        print("[FAIL] SMTP path attempted but failed. Check CloudWatch.")
        return 1

    print(f"[OK] send_email completed. Subject sent: {subject!r}")
    print(f"     Check the inbox at {RECIPIENT} now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
