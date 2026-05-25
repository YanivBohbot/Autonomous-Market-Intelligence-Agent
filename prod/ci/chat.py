"""Interactive REPL for the deployed AgentCore Runtime — with proper session affinity.

Why this exists: the Runtime Playground in the AWS console generates a fresh
`runtimeSessionId` per click, which makes AgentCore route follow-up invocations
to a different container than the one holding the checkpoint. With the
in-memory checkpointer we use in prod, that breaks HITL approval and cross-turn
memory. This script holds `runtimeSessionId` constant for the life of the REPL,
so the same container handles every turn and the checkpoint is always there.

Usage:
    python prod/ci/chat.py
    python prod/ci/chat.py --session my-test-session

Inside the REPL:
    <any text>            → send as a prompt
    /approve              → resume an interrupted run, approving the pending tool call
    /reject               → resume an interrupted run, cancelling the pending tool call
    /session              → print the current runtimeSessionId
    /new                  → start a fresh session (new runtimeSessionId)
    /quit  or  /exit      → leave

When the agent interrupts, the script prints the pending tool call(s) and waits
for `/approve` or `/reject` — you get full visibility into what the agent wants
to do BEFORE it runs the side-effect tool.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:584246028688:runtime/"
    "mia_runtime_demo-tio2ELGaQB"
)


def _invoke(client, runtime_session_id: str, payload: dict) -> dict:
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=runtime_session_id,
        payload=json.dumps(payload).encode("utf-8"),
        contentType="application/json",
        accept="application/json",
    )
    body = resp["response"].read().decode("utf-8")
    return json.loads(body) if body else {}


def _print_result(r: dict) -> None:
    status = r.get("status", "?")
    print(f"\n[{status}]  session={r.get('session_id')}  next={r.get('next_step')}")
    text = r.get("response") or ""
    if text:
        print(f"> {text}")
    pending = r.get("pending_tool_calls")
    if pending:
        print("\n⏸  PENDING TOOL CALL(S) — type /approve or /reject:")
        for tc in pending:
            print(f"    - {tc.get('name')}  args={tc.get('args')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--session",
        default=None,
        help="runtimeSessionId to use (a stable string keeps the same container). "
             "Default: a fresh UUID.",
    )
    args = parser.parse_args()

    # AgentCore requires runtimeSessionId to be >= 33 chars, so a UUID (36 chars
    # with dashes) is fine; user-provided strings get padded to be safe.
    session_id = args.session or f"chat-{uuid.uuid4()}"
    if len(session_id) < 33:
        session_id = (session_id + "-" + "x" * 33)[:33]

    client = boto3.client("bedrock-agentcore", region_name=REGION)

    print(f"runtime = {RUNTIME_ARN}")
    print(f"session = {session_id}")
    print("Commands: /approve  /reject  /session  /new  /quit\n")

    interrupted = False
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue

        if line in ("/quit", "/exit"):
            return 0
        if line == "/session":
            print(f"session_id = {session_id}")
            continue
        if line == "/new":
            session_id = f"chat-{uuid.uuid4()}"
            interrupted = False
            print(f"started new session: {session_id}")
            continue

        try:
            if line == "/approve":
                if not interrupted:
                    print("(no pending interrupt; ignoring /approve)")
                    continue
                r = _invoke(client, session_id, {"resume": "approve"})
            elif line == "/reject":
                if not interrupted:
                    print("(no pending interrupt; ignoring /reject)")
                    continue
                r = _invoke(client, session_id, {"resume": "reject"})
            else:
                r = _invoke(client, session_id, {"prompt": line})
        except Exception as e:
            print(f"\n[ERROR] {e}")
            continue

        _print_result(r)
        interrupted = r.get("status") == "interrupted"

    return 0


if __name__ == "__main__":
    sys.exit(main())
