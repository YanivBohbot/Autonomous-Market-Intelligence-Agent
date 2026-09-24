"""POST /copilot/market-desk: AG-UI SSE over the multi-agent graph.
Every LLM is faked; the router is exercised on a bare FastAPI app so the
test doesn't depend on the COPILOT_ENABLED flag (see test_copilot_wiring)."""
import json
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import email_agent as email_mod
from app.agent.multi_agent import finance_agent as finance_mod
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision
from app.api.routers.copilot import attach_market_desk, router
from tests.unit.fake_chat import FakeToolModel, StreamingFakeToolModel

PATH = "/copilot/market-desk"
SENT: list[dict] = []


@tool("send_email")
async def _fake_send_email(recipient: str, subject: str, body: str) -> str:
    """Fake send."""
    SENT.append({"recipient": recipient, "subject": subject, "body": body})
    return f"sent to {recipient}"


async def _always_known(address: str) -> bool:
    return True


def _events(body: str) -> list[dict]:
    """AG-UI SSE frames are `data: {json}` lines."""
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]


def _run_input(thread_id: str, run_id: str, messages: list[dict], **extra) -> dict:
    return {"threadId": thread_id, "runId": run_id, "messages": messages,
            "state": {}, "tools": [], "context": [], "forwardedProps": {}, **extra}


def _client_with(stack: ExitStack, route_to: str) -> tuple[TestClient, FastAPI]:
    router_mock = stack.enter_context(patch.object(supervisor_mod, "_router"))
    router_mock.invoke.return_value = RoutingDecision(next=route_to, reasoning="test")
    app = FastAPI()
    app.include_router(router)
    attach_market_desk(app, InMemorySaver(), None)
    return TestClient(app), app


@pytest.fixture
def finance_client():
    fake = FakeToolModel([AIMessage(content="AAPL is trading at $200."),
                          AIMessage(content="MSFT is trading at $400.")])
    with ExitStack() as stack:
        stack.enter_context(patch.object(finance_mod, "specialist_model", return_value=fake))
        client, app = _client_with(stack, "finance_agent")
        yield client, app


@pytest.fixture
def email_client():
    SENT.clear()
    call = {"id": "e1", "name": "send_email",
            "args": {"recipient": "a@example.com", "subject": "Hi", "body": "Report"}}
    fake = StreamingFakeToolModel([AIMessage(content="", tool_calls=[call]), AIMessage(content="Email handled.")])
    with ExitStack() as stack:
        stack.enter_context(patch.object(email_mod, "specialist_model", return_value=fake))
        stack.enter_context(patch.object(email_mod, "_TOOLS", [_fake_send_email]))
        stack.enter_context(patch.object(email_mod, "_is_client_email", _always_known))
        client, _ = _client_with(stack, "email_agent")
        yield client


def test_returns_503_when_agent_not_ready():
    app = FastAPI()
    app.include_router(router)  # no attach_market_desk: startup not finished
    resp = TestClient(app).post(PATH, json=_run_input("t0", "r0", []))
    assert resp.status_code == 503


def test_streams_a_finance_answer(finance_client):
    client, _ = finance_client
    resp = client.post(PATH, json=_run_input("t1", "r1", [{"id": "u1", "role": "user", "content": "AAPL price?"}]),
                       headers={"accept": "text/event-stream"})
    assert resp.status_code == 200
    events = _events(resp.text)
    types = [e["type"] for e in events]
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    text = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "AAPL is trading at $200." in text
    # Routing JSON is never rendered as chat text.
    assert '"next"' not in text
    assert any(e["type"] == "STEP_STARTED" and e.get("stepName") == "finance_agent" for e in events)


def test_second_turn_does_not_duplicate_history(finance_client):
    # CopilotKit re-sends the whole thread on every run; ag-ui-langgraph must
    # merge by message id so the checkpoint keeps each question once.
    client, app = finance_client
    first = {"id": "u1", "role": "user", "content": "AAPL price?"}
    client.post(PATH, json=_run_input("t2", "r1", [first]))
    second = {"id": "u2", "role": "user", "content": "And MSFT?"}
    client.post(PATH, json=_run_input("t2", "r2", [first, second]))

    graph = app.state.market_desk_agent.graph
    state = graph.get_state({"configurable": {"thread_id": "t2"}})
    humans = [m.content for m in state.values["messages"] if isinstance(m, HumanMessage)]
    assert humans == ["AAPL price?", "And MSFT?"]


def test_email_interrupts_then_reject_does_not_send(email_client):
    ask = {"id": "u1", "role": "user", "content": "email the report"}
    first = _events(email_client.post(PATH, json=_run_input("t3", "r1", [ask])).text)
    finished = [e for e in first if e["type"] == "RUN_FINISHED"][-1]
    assert finished["outcome"]["type"] == "interrupt"
    interrupt = finished["outcome"]["interrupts"][0]
    request = interrupt["metadata"]["langgraph"]["raw"]["action_requests"][0]
    assert request["name"] == "send_email"
    assert SENT == []

    resume = [{"interruptId": interrupt["id"], "status": "resolved",
               "payload": {"decisions": [{"type": "reject", "message": "not now"}]}}]
    second = email_client.post(PATH, json=_run_input("t3", "r2", [ask], resume=resume))
    assert second.status_code == 200
    assert [e["type"] for e in _events(second.text)][-1] == "RUN_FINISHED"
    assert SENT == []


@tool("yfinance_get_ticker_info")
async def _fake_quote(ticker: str) -> str:
    """Fake quote."""
    return f"{ticker}: 100"


def test_long_tool_loop_finishes():
    # Live QA: a portfolio question made ~7 tool calls; with create_agent's
    # middleware nodes that blew LangGraph's default recursion limit (25).
    calls = [AIMessage(content="", tool_calls=[{"id": f"q{i}", "name": "yfinance_get_ticker_info",
                                                "args": {"ticker": f"T{i}"}}]) for i in range(8)]
    fake = StreamingFakeToolModel([*calls, AIMessage(content="All quotes fetched.")])
    with ExitStack() as stack:
        stack.enter_context(patch.object(finance_mod, "specialist_model", return_value=fake))
        stack.enter_context(patch.object(finance_mod, "_TOOLS", [_fake_quote]))
        client, _ = _client_with(stack, "finance_agent")
        resp = client.post(PATH, json=_run_input("t4", "r1", [{"id": "u1", "role": "user", "content": "quotes"}]))
    events = _events(resp.text)
    assert events[-1]["type"] == "RUN_FINISHED"
    assert "All quotes fetched." in "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")


def test_graph_error_becomes_run_error_event():
    # A crash mid-run must reach the browser as RUN_ERROR, not a cut stream.
    with ExitStack() as stack:
        client, _ = _client_with(stack, "finance_agent")
        supervisor_mod._router.invoke.side_effect = RuntimeError("router down")
        resp = client.post(PATH, json=_run_input("t5", "r1", [{"id": "u1", "role": "user", "content": "hi"}]))
    assert resp.status_code == 200
    last = _events(resp.text)[-1]
    assert last["type"] == "RUN_ERROR"
    assert "router down" in last["message"]
