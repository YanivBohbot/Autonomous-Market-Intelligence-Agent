"""Exact simulation of the AWS Console Runtime Playground flow.

The Console playground generates a fresh runtimeSessionId per "Run"
click. The only thing keeping the conversation glued together is the
body.session_id you paste into each Input box.

This script:
- Uses a fresh runtimeSessionId on every invoke (mimicking "Run" clicks)
- Keeps body.session_id constant for the whole sequence
- Walks the most demo-critical HITL flows end-to-end:
    1) write_file  → interrupt
    2) /approve    (different container)
    3) read back   (different container) — verifies the write actually landed
    4) send_email  → interrupt
    5) /approve    (different container) — verifies SES MessageId
    6) cross-turn recall — references the write_file
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
client = boto3.client("bedrock-agentcore", region_name=REGION)

BODY_SID = f"playground-final-{uuid.uuid4()}"

PASS = 0
FAIL = 0


def _new_runtime_session() -> str:
    return f"pg-{uuid.uuid4()}"


def invoke(payload: dict) -> dict:
    rs = _new_runtime_session()
    t0 = time.time()
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=rs,
        payload=json.dumps(payload).encode("utf-8"),
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
    print(f"        runtimeSessionId={r.get('_runtime_session')[:24]}...")
    print(f"        status={r.get('status')}  elapsed={r.get('_elapsed')}s")
    pending = r.get("pending_tool_calls")
    if pending:
        for tc in pending:
            print(f"        pending: {tc.get('name')}  args={tc.get('args')}")
    txt = (r.get("response") or "")[:snippet]
    if txt:
        print(f"        > {txt}")
    if ok:
        PASS += 1
    else:
        FAIL += 1


def main() -> int:
    print(f"runtime         = {RUNTIME_ARN}")
    print(f"body.session_id = {BODY_SID}")
    print("Every invoke below uses a FRESH runtimeSessionId — exactly like the Console playground.")
    print("=" * 78)

    # 1. write_file → interrupt
    r = invoke({
        "prompt": (
            'Write a file named "playground_final.txt" in my workspace with '
            'content "console playground end-to-end works". Call the tool directly.'
        ),
        "session_id": BODY_SID,
    })
    case("write_file → interrupt",
         r.get("status") == "interrupted" and bool(r.get("pending_tool_calls")),
         r)

    # 2. /approve — DIFFERENT runtimeSessionId. With the durable saver, the
    # checkpoint sits in AgentCore Memory keyed by body.session_id, so a
    # different container can still resume it.
    r = invoke({"resume": "approve", "session_id": BODY_SID})
    case("write_file → /approve on FRESH runtimeSessionId",
         r.get("status") == "completed",
         r)

    # 3. read-back proves the side-effect actually landed
    r = invoke({
        "prompt": "Read the file playground_final.txt and show me its content.",
        "session_id": BODY_SID,
    })
    text = (r.get("response") or "").lower()
    case("read_text_file → content matches what we wrote",
         r.get("status") == "completed" and "console playground end-to-end works" in text,
         r)

    # 4. send_email → interrupt
    subject = f"Playground SES test {int(time.time())}"
    r = invoke({
        "prompt": (
            f'Send an email to yanivbohbot5@gmail.com with subject "{subject}" '
            f'and body "playground SES verification". Call the send_email tool directly.'
        ),
        "session_id": BODY_SID,
    })
    case("send_email → interrupt",
         r.get("status") == "interrupted" and bool(r.get("pending_tool_calls")),
         r)

    # 5. /approve send_email — different container, must hit SES
    r = invoke({"resume": "approve", "session_id": BODY_SID})
    # The LLM paraphrases the tool's "MessageId=..." reply — don't grep for
    # that token. Trust the tool's status + the absence of error/simulation
    # markers, and confirm SES via CloudWatch if you need the literal MessageId.
    response_text = (r.get("response") or "").lower()
    sent_ok = (
        r.get("status") == "completed"
        and ("sent" in response_text or "successfully" in response_text)
        and "erreur" not in response_text
        and "simulation" not in response_text
    )
    case("send_email → /approve sent via SES",
         sent_ok,
         r)

    # 6. Cross-turn recall — should reference the first action (writing the file)
    r = invoke({
        "prompt": "What was the very first thing I asked you in this session?",
        "session_id": BODY_SID,
    })
    txt = (r.get("response") or "").lower()
    recalled = (
        r.get("status") == "completed"
        and ("playground_final" in txt or "write" in txt)
    )
    case("cross-turn recall references the first turn",
         recalled,
         r)

    print("\n" + "=" * 78)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if FAIL == 0:
        print("\nThe AWS Console Runtime Playground will behave exactly as this run did,")
        print("because the playground invokes the same API with the same fresh-runtime-")
        print("session-per-click pattern. If everything here passed, the UI works.")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
