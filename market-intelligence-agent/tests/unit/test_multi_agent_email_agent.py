from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.agents_specialist import email_agent as mod
from app.agent.middleware import RedactEmailsForModel, base_middleware


def _kwargs():
    with patch.object(mod, "create_agent") as ca:
        mod.build_email_agent()
    return ca.call_args.kwargs


def test_tools():
    assert {t.name for t in mod._TOOLS} == {"read_query", "send_email"}


def test_prompt_looks_up_client_email_via_read_query_before_sending():
    from app.agent.prompts.agents_specialist_prompts import EMAIL_SYSTEM_PROMPT
    assert "`read_query`" in EMAIL_SYSTEM_PROMPT
    assert "FROM clients WHERE name LIKE" in EMAIL_SYSTEM_PROMPT
    assert "ask the user if it's missing" not in EMAIL_SYSTEM_PROMPT
    assert EMAIL_SYSTEM_PROMPT.index("read_query") < EMAIL_SYSTEM_PROMPT.index("send_email")


def test_read_query_is_not_gated_by_hitl():
    mw = _kwargs()["middleware"]
    hitl = next(m for m in mw if isinstance(m, HumanInTheLoopMiddleware))
    assert "read_query" not in hitl.interrupt_on
    assert set(hitl.interrupt_on) == {"send_email"}


def test_create_agent_call_with_hitl_on_send_email():
    from app.agent.prompts.agents_specialist_prompts import EMAIL_SYSTEM_PROMPT
    kw = _kwargs()
    assert kw["system_prompt"] == EMAIL_SYSTEM_PROMPT
    assert kw["tools"] == mod._TOOLS
    assert kw["name"] == "email_agent"
    mw = kw["middleware"]
    base = base_middleware(mod._TOOLS)
    assert [type(m) for m in mw[:len(base)]] == [type(m) for m in base]
    assert isinstance(mw[len(base)], HumanInTheLoopMiddleware)
    assert set(mw[len(base)].interrupt_on) == {"send_email"}
    # Listed after HITL so its after_model runs before HITL's: a retry of a
    # failed send is dropped before any approval card is shown.
    assert isinstance(mw[len(base) + 1], mod.NoResendAfterFailure)
    # Guard runs at execution time (after approval): only clients' addresses.
    assert isinstance(mw[len(base) + 2], mod.EmailRecipientGuard)
    assert len(mw) == len(base) + 3


def test_builds_a_real_agent_with_hitl_node():
    nodes = mod.build_email_agent().get_graph().nodes
    assert "HumanInTheLoopMiddleware.after_model" in nodes


def test_keeps_email_addresses_it_needs_to_work():
    kw = _kwargs()
    assert not any(getattr(m, "pii_type", None) == "email" for m in kw["middleware"])
    assert not any(isinstance(m, RedactEmailsForModel) for m in kw["middleware"])


def test_prompt_opens_empty_draft_instead_of_asking_for_content():
    from app.agent.prompts.agents_specialist_prompts import EMAIL_SYSTEM_PROMPT
    assert 'EMPTY `subject` and `body` ("")' in EMAIL_SYSTEM_PROMPT
    assert "Never ask the user for the subject or body" in EMAIL_SYSTEM_PROMPT


def test_prompt_forbids_inventing_figures():
    from app.agent.prompts.agents_specialist_prompts import EMAIL_SYSTEM_PROMPT
    assert "never invent figures" in EMAIL_SYSTEM_PROMPT
    assert "portfolio_agent's answer" in EMAIL_SYSTEM_PROMPT


def test_prompt_says_not_to_retry_a_failed_send():
    """Regression (LangSmith trace 2026-10-12): after SES rejected the
    address, the agent re-called send_email and asked for approval again."""
    from app.agent.prompts.agents_specialist_prompts import EMAIL_SYSTEM_PROMPT
    assert "do not call `send_email` again" in EMAIL_SYSTEM_PROMPT.lower()


def test_prompt_asks_for_a_plain_text_body_without_markdown():
    """Live 2026-10-12: the body copied portfolio_agent's Markdown table
    (| Ticker | Shares |...) into a plain-text email."""
    from app.agent.prompts.agents_specialist_prompts import EMAIL_SYSTEM_PROMPT
    lowered = EMAIL_SYSTEM_PROMPT.lower()
    assert "no markdown" in lowered and "no tables" in lowered
