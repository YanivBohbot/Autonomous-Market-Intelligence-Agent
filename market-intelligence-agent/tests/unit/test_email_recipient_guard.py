"""EmailRecipientGuard: send_email only to addresses of clients in the DB.
Runs at tool execution, i.e. after HITL approval — a mistaken approval of an
unknown address still sends nothing."""
import pytest
from langchain_core.messages import ToolMessage

from app.agent.multi_agent import email_agent as mod
from app.agent.multi_agent.email_agent import EmailRecipientGuard


class _Req:
    def __init__(self, name, args):
        self.tool_call = {"id": "c1", "name": name, "args": args}


def _guard(known):
    async def is_known(address):
        return address.lower() in known
    return EmailRecipientGuard(is_known_recipient=is_known)


@pytest.mark.anyio
async def test_known_client_address_is_sent():
    calls = []

    async def handler(req):
        calls.append(req)
        return ToolMessage(content="sent", tool_call_id="c1")

    result = await _guard({"client@example.com"}).awrap_tool_call(
        _Req("send_email", {"recipient": "Client@Example.com", "subject": "s", "body": "b"}), handler)
    assert result.content == "sent"
    assert len(calls) == 1


@pytest.mark.anyio
async def test_unknown_address_is_blocked_and_nothing_is_sent():
    async def handler(req):
        raise AssertionError("must not send")

    result = await _guard({"client@example.com"}).awrap_tool_call(
        _Req("send_email", {"recipient": "stranger@evil.com", "subject": "s", "body": "b"}), handler)
    assert result.status == "error"
    assert "stranger@evil.com" in result.content
    assert "not a client" in result.content


@pytest.mark.anyio
async def test_other_tools_pass_through_untouched():
    async def handler(req):
        return ToolMessage(content="ok", tool_call_id="c1")

    result = await _guard(set()).awrap_tool_call(_Req("read_query", {"query": "SELECT 1"}), handler)
    assert result.content == "ok"


def test_sync_path_fails_closed():
    def handler(req):
        raise AssertionError("must not send")

    result = _guard({"client@example.com"}).wrap_tool_call(
        _Req("send_email", {"recipient": "client@example.com", "subject": "s", "body": "b"}), handler)
    assert result.status == "error"


@pytest.mark.anyio
async def test_is_client_email_queries_the_clients_table(monkeypatch):
    seen = []

    class _FakeCrm:
        async def ainvoke(self, args):
            seen.append(args["query"])
            return [{"type": "text", "text": "[{'n': 1}]"}]

    monkeypatch.setattr(mod, "crm_tool", _FakeCrm())
    assert await mod._is_client_email("O'Brien@example.com") is True
    assert "FROM clients" in seen[0]
    assert "lower('o''brien@example.com')" in seen[0].lower()
