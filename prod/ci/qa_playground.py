"""Simulate the AgentCore Runtime Playground from CLI.

The console playground generates a fresh runtimeSessionId every "Run" click.
This script does the same — a brand-new UUID per call — and runs the same
suite of scenarios. The point is to map which tests pass in the playground
flow and which require sticky-session affinity (i.e., HITL approve, multi-
turn memory).

For comparison, the second half re-runs the multi-turn scenarios with a
SINGLE pinned runtimeSessionId, so you can see the difference.
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

PASS = 0
FAIL = 0


def _new_runtime_session() -> str:
    # AgentCore requires runtimeSessionId length >= 33; UUID is 36.
    return f"pg-{uuid.uuid4()}"


def invoke(runtime_session: str, payload: dict) -> dict:
    t0 = time.time()
    try:
        resp = client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            runtimeSessionId=runtime_session,
            payload=json.dumps(payload).encode("utf-8"),
            contentType="application/json",
            accept="application/json",
        )
        body = resp["response"].read().decode("utf-8")
        r = json.loads(body) if body else {}
    except Exception as e:
        r = {"_error": str(e)}
    r["_elapsed"] = round(time.time() - t0, 2)
    return r


def show(r: dict) -> None:
    if "_error" in r:
        print(f"        ERROR: {r['_error']}")
        return
    print(f"        status={r.get('status')}  next={r.get('next_step')}  elapsed={r['_elapsed']}s")
    pending = r.get("pending_tool_calls")
    if pending:
        for tc in pending:
            print(f"        pending: {tc.get('name')}  args={tc.get('args')}")
    text = (r.get("response") or "")[:200]
    if text:
        print(f"        > {text}")


def case(label: str, ok: bool, r: dict) -> None:
    global PASS, FAIL
    flag = "[OK]  " if ok else "[FAIL]"
    print(f"\n{flag} {label}")
    show(r)
    if ok:
        PASS += 1
    else:
        FAIL += 1


def kw(r: dict, words: list[str]) -> bool:
    text = (r.get("response") or "").lower()
    return any(w.lower() in text for w in words)


def hr() -> None:
    print("\n" + "=" * 72)


def part_one_playground_style() -> None:
    """Each call uses a FRESH runtimeSessionId — exactly like the console
    playground."""
    print("\n>>> PART 1: PLAYGROUND-STYLE (fresh runtimeSessionId every call)\n")

    # Single-turn read-only — these should all work in the playground
    r = invoke(_new_runtime_session(),
               {"prompt": "What is NVDA's current stock price?"})
    case("playground:yfinance_get_ticker_info",
         r.get("status") == "completed" and kw(r, ["nvda", "$", "nvidia"]), r)

    r = invoke(_new_runtime_session(),
               {"prompt": "Show TSLA price history for the last 1 month — high and low close."})
    case("playground:yfinance_get_price_history",
         r.get("status") == "completed" and kw(r, ["tsla", "high", "low", "$"]), r)

    r = invoke(_new_runtime_session(),
               {"prompt": "Latest 3 news headlines for AAPL."})
    case("playground:yfinance_get_ticker_news",
         r.get("status") == "completed", r)

    r = invoke(_new_runtime_session(),
               {"prompt": "List CRM customers with status VIP."})
    case("playground:read_query (CRM)",
         r.get("status") == "completed" and kw(r, ["vip", "yaniv", "customer"]), r)

    r = invoke(_new_runtime_session(),
               {"prompt": "List the files in my workspace."})
    case("playground:list_directory",
         r.get("status") == "completed", r)

    r = invoke(_new_runtime_session(),
               {"prompt": "List the user facts you have stored about me."})
    case("playground:list_memories",
         r.get("status") == "completed", r)

    r = invoke(_new_runtime_session(),
               {"prompt": "Who are you and what can you do?"})
    case("playground:identity anchored",
         r.get("status") == "completed" and "market intelligence" in (r.get("response") or "").lower(), r)

    # Now: HITL — the exact scenario the user hit in the AWS Console
    # playground. The console UI generates a fresh runtimeSessionId per
    # "Run" click, but the user pastes the same body.session_id on both
    # calls. Our agentcore.py router prefers body.session_id over the
    # runtime-session header, so thread_id stays constant — and with the
    # durable AgentCore Memory checkpointer the second container can
    # load the checkpoint the first one wrote.
    body_session = f"playground-hitl-{uuid.uuid4()}"
    print("\n--- HITL probe (durable checkpointer must keep state across containers) ---")
    print(f"        body.session_id={body_session}")
    r = invoke(
        _new_runtime_session(),
        {
            "prompt": 'Please write a file named "pg_test.txt" with content "playground style".',
            "session_id": body_session,
        },
    )
    case("playground:write_file → interrupt (turn 1)",
         r.get("status") == "interrupted", r)

    # Different runtimeSessionId (mimics a second console click), but
    # same body.session_id. With the durable saver this resume now
    # succeeds even though a different container is handling it.
    r = invoke(
        _new_runtime_session(),
        {"resume": "approve", "session_id": body_session},
    )
    ok = r.get("status") == "completed"
    case("playground:write_file → approve on FRESH runtimeSessionId (durable saver)",
         ok, r)


def part_two_sticky_session() -> None:
    """Same scenarios, but every call reuses ONE runtimeSessionId — the way
    chat.py / qa_full.py / any properly-scripted client does it."""
    print("\n\n>>> PART 2: STICKY runtimeSessionId (same container every call)\n")
    rs = _new_runtime_session()
    print(f"runtimeSessionId = {rs}\n")

    r = invoke(rs, {"prompt": 'Please write a file named "sticky_test.txt" with content "sticky session works".'})
    case("sticky:write_file → interrupt",
         r.get("status") == "interrupted", r)

    r = invoke(rs, {"resume": "approve"})
    case("sticky:write_file → approve",
         r.get("status") == "completed", r)

    r = invoke(rs, {"prompt": "Read the file sticky_test.txt and show me the content."})
    case("sticky:read_text_file",
         r.get("status") == "completed" and "sticky session works" in (r.get("response") or ""), r)

    r = invoke(rs, {"prompt": "Remember that my preferred reporting period is 1 quarter."})
    case("sticky:save_memory → interrupt",
         r.get("status") == "interrupted", r)

    r = invoke(rs, {"resume": "approve"})
    case("sticky:save_memory → approve",
         r.get("status") == "completed", r)

    r = invoke(rs, {"prompt": "What's my preferred reporting period? Use recall_memory."})
    case("sticky:recall_memory",
         r.get("status") == "completed" and "quarter" in (r.get("response") or "").lower(), r)

    r = invoke(rs, {"prompt": "Send an email to yanivbohbot5@gmail.com with subject 'qa' and body 'probe'."})
    case("sticky:send_email → interrupt",
         r.get("status") == "interrupted", r)

    r = invoke(rs, {"resume": "reject"})
    case("sticky:send_email → reject",
         r.get("status") == "completed", r)

    r = invoke(rs, {"prompt": "What was the very first thing I asked you in this session?"})
    case("sticky:cross-turn recall",
         r.get("status") == "completed" and "sticky_test" in (r.get("response") or "").lower(), r)


def part_three_browser() -> None:
    """Cases 19-20: browser tools — read-only snapshot and HITL screenshot→brief."""
    print("\n\n>>> PART 3: BROWSER TOOLS (cases 19-20)\n")

    # Case 19 — read-only browser flow: navigate then snapshot.
    # browser_navigate and browser_snapshot are both in READ_ONLY_TOOLS, so
    # the graph should complete without an interrupt.
    rs19 = _new_runtime_session()
    r = invoke(
        rs19,
        {
            "prompt": (
                "Use browser_navigate to open https://example.com, "
                "then call browser_snapshot and tell me what the page title is."
            )
        },
    )
    resp_text = (r.get("response") or "").lower()
    case(
        "case-19: browser_navigate + browser_snapshot → 'Example Domain' in response",
        r.get("status") == "completed" and "example domain" in resp_text,
        r,
    )

    # Case 20 — browser → screenshot → write_file with HITL approve.
    # Turn 1: ask agent to open example.com, screenshot it as evidence.png,
    #         and write example_brief.md referencing the screenshot.
    #         write_file is a side-effect tool → expect status=="interrupted".
    rs20 = _new_runtime_session()
    r = invoke(
        rs20,
        {
            "prompt": (
                "Open https://example.com with browser_navigate, take a screenshot "
                "named 'evidence.png' with browser_take_screenshot, then write a "
                "short file called 'example_brief.md' that describes the page and "
                "references the screenshot. Do all of this now."
            )
        },
    )
    pending = r.get("pending_tool_calls") or []
    pending_names = [tc.get("name", "") for tc in pending]
    pending_args = str([tc.get("args", {}) for tc in pending]).lower()
    case(
        "case-20 turn-1: write_file gates on HITL → interrupted",
        r.get("status") == "interrupted" and bool(pending),
        r,
    )

    # Turn 2: approve — same runtimeSessionId so the checkpoint is reachable.
    r = invoke(rs20, {"resume": "approve"})
    completed_text = (r.get("response") or "").lower()
    args_mention = "evidence.png" in pending_args or "example_brief" in pending_args
    response_mention = (
        "evidence.png" in completed_text or "example_brief" in completed_text
    )
    case(
        "case-20 turn-2: approve → completed, response/args mention evidence.png or example_brief.md",
        r.get("status") == "completed" and (args_mention or response_mention),
        r,
    )


def main() -> int:
    print(f"runtime = {RUNTIME_ARN}")
    print(f"region  = {REGION}")

    part_one_playground_style()
    hr()
    part_two_sticky_session()
    hr()
    part_three_browser()
    hr()

    print(f"\nRESULT: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
