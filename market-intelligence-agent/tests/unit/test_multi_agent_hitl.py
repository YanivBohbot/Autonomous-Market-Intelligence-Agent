"""HITL through the whole multi-agent graph with the official middleware:
send_email pauses the graph; approve / reject / edit decide what runs."""
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agent.orchestration.graph import build_multi_agent_app
from app.agent.agents_specialist import email_agent as email_mod
from app.agent.orchestration import supervisor as supervisor_mod
from app.agent.orchestration.supervisor import RoutingDecision
from tests.unit.fake_chat import FakeToolModel
from tests.unit.router_fakes import routed

SENT = []


@tool("send_email")
async def _fake_send_email(
    recipient: str,
    subject: str,
    body: str,
    attachment_filename: str | None = None,
) -> str:
    """Fake send."""
    SENT.append({
        "recipient": recipient,
        "subject": subject,
        "body": body,
        "attachment_filename": attachment_filename,
    })
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
        patch.object(supervisor_mod, "router_agent"),
    ]
    for p in patches:
        p.start()
    supervisor_mod.router_agent.invoke.return_value = routed("email_agent", "email")
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
        assert SENT == [{**_CALL["args"], "attachment_filename": None}]
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
        assert SENT == [{**edited["args"], "attachment_filename": None}]
    finally:
        for p in patches:
            p.stop()


@pytest.mark.anyio
async def test_edit_sends_the_selected_report_filename():
    graph, cfg, _, patches = await _run_until_interrupt()
    try:
        filename = "margaret-collins-portfolio-brief-2026-10-06.xlsx"
        edited = {
            "name": "send_email",
            "args": {**_CALL["args"], "attachment_filename": filename},
        }
        await graph.ainvoke(
            Command(resume={"decisions": [{"type": "edit", "edited_action": edited}]}),
            cfg,
        )
        assert SENT == [edited["args"]]
    finally:
        for p in patches:
            p.stop()


@tool("send_email")
async def _failing_send_email(
    recipient: str,
    subject: str,
    body: str,
    attachment_filename: str | None = None,
) -> str:
    """Fake SES rejection."""
    SENT.append({"recipient": recipient})
    return "Erreur SES (MessageRejected) : Email address is not verified."


@pytest.mark.anyio
async def test_a_failed_send_is_not_retried_and_asks_no_second_approval():
    """Regression (LangSmith trace 2026-10-12): approve -> SES rejects ->
    the model calls send_email again for the same recipient -> a second
    approval card. The retry must be dropped before HITL sees it."""
    SENT.clear()
    retry = {"id": "e2", "name": "send_email",
             "args": {"recipient": "a@example.com", "subject": "Hi", "body": "Report again"}}
    fake = FakeToolModel([
        AIMessage(content="", tool_calls=[_CALL]),
        AIMessage(content="", tool_calls=[retry]),
        AIMessage(content="should never be reached"),
    ])
    patches = [
        patch.object(email_mod, "specialist_model", return_value=fake),
        patch.object(email_mod, "_TOOLS", [_failing_send_email]),
        patch.object(email_mod, "_is_client_email", _always_known),
        patch.object(supervisor_mod, "router_agent"),
    ]
    for p in patches:
        p.start()
    try:
        supervisor_mod.router_agent.invoke.return_value = routed("email_agent", "email")
        graph = build_multi_agent_app(InMemorySaver())
        cfg = {"configurable": {"thread_id": "hitl-retry"}}
        first = await graph.ainvoke(
            {"question": "email the report", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}, cfg)
        assert first["__interrupt__"]
        result = await graph.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg)
        assert "__interrupt__" not in result
        assert len(SENT) == 1
        final = result["messages"][-1].content
        assert "a@example.com" in final and "not sent" in final.lower()
    finally:
        for p in patches:
            p.stop()
