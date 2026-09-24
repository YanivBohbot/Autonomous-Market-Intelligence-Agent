from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent import email_agent as mod
from app.agent.multi_agent.common import base_middleware


def _kwargs():
    with patch.object(mod, "create_agent") as ca:
        mod.build_email_agent()
    return ca.call_args.kwargs


def test_tools():
    assert {t.name for t in mod._TOOLS} == {"send_email"}


def test_create_agent_call_with_hitl_on_send_email():
    from app.agent.prompts.specialist_agent_prompts import EMAIL_SYSTEM_PROMPT
    kw = _kwargs()
    assert kw["system_prompt"] == EMAIL_SYSTEM_PROMPT
    assert kw["tools"] == mod._TOOLS
    assert kw["name"] == "email_agent"
    mw = kw["middleware"]
    base = base_middleware()
    assert [type(m) for m in mw[:len(base)]] == [type(m) for m in base]
    assert isinstance(mw[len(base)], HumanInTheLoopMiddleware)
    assert set(mw[len(base)].interrupt_on) == {"send_email"}
    # Guard runs at execution time (after approval): only clients' addresses.
    assert isinstance(mw[len(base) + 1], mod.EmailRecipientGuard)
    assert len(mw) == len(base) + 2


def test_builds_a_real_agent_with_hitl_node():
    nodes = mod.build_email_agent().get_graph().nodes
    assert "HumanInTheLoopMiddleware.after_model" in nodes


def test_keeps_email_addresses_it_needs_to_work():
    kw = _kwargs()
    assert not any(getattr(m, "pii_type", None) == "email" for m in kw["middleware"])
