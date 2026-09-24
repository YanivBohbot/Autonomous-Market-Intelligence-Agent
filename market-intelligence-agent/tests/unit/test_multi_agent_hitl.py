"""HITL through the whole multi-agent graph with the official middleware:
send_email pauses the graph; approve / reject / edit decide what runs."""
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agent.multi_agent import build_multi_agent_app
from app.agent.multi_agent import email_agent as email_mod
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision
from tests.unit.fake_chat import FakeToolModel

SENT = []


@tool("send_email")
async def _fake_send_email(recipient: str, subject: str, body: str) -> str:
    """Fake send."""
    SENT.append({"recipient": recipient, "subject": subject, "body": body})
    return f"sent to {recipient}"


async def _always_known(address: str) -> bool:
    return True


_CALL = {"id": "e1", "name": "send_email",
         "args": {"recipient": "a@example.com", "subject": "Hi", "body": "Report"}}


async def _run_until_interrupt():
    SENT.clear()
    fake = FakeToolModel([AIMessage(content="", tool_calls=[_CALL]), AIMessage(content="Email handled.")])
    patches = [
        patch.object(email_mod, "specialist_model", return_value=fake),
        patch.object(email_mod, "_TOOLS", [_fake_send_email]),
        patch.object(email_mod, "_is_client_email", _always_known),
        patch.object(supervisor_mod, "_router"),
    ]
    for p in patches:
        p.start()
    supervisor_mod._router.invoke.return_value = RoutingDecision(next="email_agent", reasoning="email")
    graph = build_multi_agent_app(InMemorySaver())
    cfg = {"configurable": {"thread_id": "hitl"}}
    first = await graph.ainvoke(
        {"question": "email the report", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}, cfg)
    return graph, cfg, first, patches


@pytest.mark.anyio
async def test_send_email_pauses_before_sending():
    graph, cfg, first, patches = await _run_until_interrupt()
    try:
        assert first["__interrupt__"]
        request = first["__interrupt__"][0].value["action_requests"][0]
        assert request["name"] == "send_email"
        assert SENT == []
    finally:
        for p in patches:
            p.stop()


@pytest.mark.anyio
async def test_approve_sends():
    graph, cfg, _, patches = await _run_until_interrupt()
    try:
        result = await graph.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg)
        assert SENT == [_CALL["args"]]
        assert result["messages"][-1].content == "Email handled."
    finally:
        for p in patches:
            p.stop()


@pytest.mark.anyio
async def test_reject_does_not_send():
    graph, cfg, _, patches = await _run_until_interrupt()
    try:
        await graph.ainvoke(Command(resume={"decisions": [{"type": "reject", "message": "not now"}]}), cfg)
        assert SENT == []
    finally:
        for p in patches:
            p.stop()


@pytest.mark.anyio
async def test_edit_sends_the_corrected_email():
    graph, cfg, _, patches = await _run_until_interrupt()
    try:
        edited = {"name": "send_email", "args": {**_CALL["args"], "subject": "Weekly report"}}
        await graph.ainvoke(Command(resume={"decisions": [{"type": "edit", "edited_action": edited}]}), cfg)
        assert SENT == [edited["args"]]
    finally:
        for p in patches:
            p.stop()
