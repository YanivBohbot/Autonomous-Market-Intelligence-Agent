"""Full tool-by-tool QA suite for the deployed AgentCore Runtime.

Walks every production tool the agent can call:

  Read-only (single turn, no HITL):
    1. yfinance_get_ticker_info
    2. yfinance_get_price_history
    3. yfinance_get_ticker_news
    4. read_query (CRM)
    5. list_directory (filesystem)
    6. list_memories
    7. recall_memory

  Side-effect (two-step: turn → interrupt → approve):
    8. write_file (filesystem) — then list/read to confirm
    9. save_memory — then list_memories / recall_memory to confirm
   10. send_email — interrupt + reject (don't actually send)

Also probes the graph features that wrap the tools:
   - cross-turn memory recall (now that record_question node persists turns)
   - HITL approval flow via the /invocations resume contract

Exits non-zero on any failure.
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

agentcore = boto3.client("bedrock-agentcore", region_name=REGION)


def invoke(session_id: str, payload: dict) -> dict:
    t0 = time.time()
    resp = agentcore.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=session_id,
        payload=json.dumps(payload).encode("utf-8"),
        contentType="application/json",
        accept="application/json",
    )
    body = resp["response"].read().decode("utf-8")
    r = json.loads(body) if body else {}
    r["_elapsed"] = round(time.time() - t0, 2)
    return r


def ask(session: str, prompt: str) -> dict:
    return invoke(session, {"prompt": prompt})


def resume(session: str, decision: str) -> dict:
    return invoke(session, {"resume": decision})


def show(label: str, r: dict, snippet: int = 220) -> None:
    status = r.get("status")
    pending = r.get("pending_tool_calls")
    print(f"        status={status}  elapsed={r.get('_elapsed')}s")
    if pending:
        print(f"        pending_tool_calls={pending}")
    text = (r.get("response") or "")[:snippet]
    print(f"        > {text}")


PASS = 0
FAIL = 0


def case(label: str, ok: bool, r: dict, reason: str = "") -> None:
    global PASS, FAIL
    flag = "[OK]  " if ok else "[FAIL]"
    print(f"\n{flag} {label}")
    if reason and not ok:
        print(f"        reason: {reason}")
    show(label, r)
    if ok:
        PASS += 1
    else:
        FAIL += 1


def kw_any(r: dict, keywords: list[str]) -> bool:
    text = (r.get("response") or "").lower()
    return any(k.lower() in text for k in keywords)


def main() -> int:
    session = f"qafull-{uuid.uuid4()}"
    print(f"runtime = {RUNTIME_ARN}")
    print(f"session = {session}")
    print("=" * 70)

    # --- Read-only single-turn tools ----------------------------------------

    r = ask(session, "What is NVDA's current stock price?")
    case("yfinance_get_ticker_info",
         r.get("status") == "completed" and kw_any(r, ["$", "nvda", "nvidia"]),
         r, "expected ticker info with price")

    r = ask(session, "Show me TSLA price history for the last 1 month — give me the highest and lowest close.")
    case("yfinance_get_price_history",
         r.get("status") == "completed" and kw_any(r, ["tsla", "high", "low", "close", "$"]),
         r, "expected high/low close mention")

    r = ask(session, "What are the latest 3 news headlines about Apple (AAPL)?")
    case("yfinance_get_ticker_news",
         r.get("status") == "completed",
         r, "expected completion (news may be empty)")

    r = ask(session, "List all customers in the CRM with status VIP.")
    case("read_query (CRM)",
         r.get("status") == "completed" and kw_any(r, ["vip", "yaniv", "customer"]),
         r, "expected at least one VIP customer")

    r = ask(session, "List the files in my workspace.")
    case("list_directory (empty)",
         r.get("status") == "completed",
         r, "expected workspace listing")

    r = ask(session, "What user facts do you have stored about me? Use list_memories.")
    case("list_memories (empty)",
         r.get("status") == "completed",
         r, "expected list of memories")

    # --- Side-effect: write_file (HITL approve) -----------------------------

    r = ask(session, 'Please write a file named "test_qa.txt" in my workspace with the content "qa run marker".')
    interrupted = r.get("status") == "interrupted"
    has_write = bool(r.get("pending_tool_calls") and
                     any("write_file" in (tc.get("name") or "") for tc in r["pending_tool_calls"]))
    case("write_file → interrupt",
         interrupted and has_write,
         r, "expected interrupt with write_file pending")

    if interrupted and has_write:
        r = resume(session, "approve")
        case("write_file → approve",
             r.get("status") == "completed",
             r, "expected completion after approve")

    # Now confirm the write took effect via list + read
    r = ask(session, "List the files in my workspace again.")
    case("list_directory (after write)",
         r.get("status") == "completed" and "test_qa.txt" in (r.get("response") or ""),
         r, "expected test_qa.txt in listing")

    r = ask(session, 'Read the file "test_qa.txt" and show me its content.')
    case("read_text_file",
         r.get("status") == "completed" and "qa run marker" in (r.get("response") or ""),
         r, "expected file content 'qa run marker'")

    # --- Side-effect: save_memory (HITL approve) ----------------------------

    r = ask(session, "Please remember that my favorite ticker is NVDA. Save it as a memory.")
    interrupted = r.get("status") == "interrupted"
    has_save = bool(r.get("pending_tool_calls") and
                    any("save_memory" in (tc.get("name") or "") for tc in r["pending_tool_calls"]))
    case("save_memory → interrupt",
         interrupted and has_save,
         r, "expected interrupt with save_memory pending")

    if interrupted and has_save:
        r = resume(session, "approve")
        case("save_memory → approve",
             r.get("status") == "completed",
             r, "expected completion after approve")

    r = ask(session, "What's my favorite ticker? Use recall_memory.")
    case("recall_memory",
         r.get("status") == "completed" and "nvda" in (r.get("response") or "").lower(),
         r, "expected NVDA mentioned")

    r = ask(session, "List all the user facts you have stored. Use list_memories.")
    case("list_memories (after save)",
         r.get("status") == "completed" and "nvda" in (r.get("response") or "").lower(),
         r, "expected NVDA in stored memories")

    # --- Side-effect: send_email (HITL reject — don't actually send) --------

    r = ask(session, 'Send an email to yanivbohbot5@gmail.com with subject "QA test" and body "this is a QA probe".')
    interrupted = r.get("status") == "interrupted"
    has_email = bool(r.get("pending_tool_calls") and
                     any("send_email" in (tc.get("name") or "") for tc in r["pending_tool_calls"]))
    case("send_email → interrupt",
         interrupted and has_email,
         r, "expected interrupt with send_email pending")

    if interrupted and has_email:
        r = resume(session, "reject")
        case("send_email → reject (cancel)",
             r.get("status") == "completed" and kw_any(r, ["cancel", "not", "sent", "abort"]),
             r, "expected the model to acknowledge cancellation")

    # --- Cross-turn memory recall (graph-level, not a tool) -----------------

    r = ask(session, "What was the very first question I asked you in this session?")
    case("cross-turn recall",
         r.get("status") == "completed" and "nvda" in (r.get("response") or "").lower() and "price" in (r.get("response") or "").lower(),
         r, "expected: refers to NVDA stock price question (turn 1)")

    # --- Identity stays anchored after many turns ---------------------------

    r = ask(session, "Just to confirm — who are you and what can you do?")
    case("identity anchored",
         r.get("status") == "completed" and "market intelligence" in (r.get("response") or "").lower(),
         r, "expected 'Market Intelligence Agent' identity")

    print("\n" + "=" * 70)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
