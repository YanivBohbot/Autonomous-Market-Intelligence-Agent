from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.agents_specialist import filesystem_agent as mod
from app.agent.middleware import RedactEmailsForModel, base_middleware
from app.agent.display import market_desk_display


def _kwargs():
    with patch.object(mod, "create_agent") as ca:
        mod.build_filesystem_agent()
    return ca.call_args.kwargs


def test_tools():
    assert {t.name for t in mod._TOOLS} == {"read_text_file", "list_directory", "write_file"}


def test_create_agent_call_with_hitl_on_write_file():
    from app.agent.prompts.agents_specialist_prompts import FILESYSTEM_SYSTEM_PROMPT
    kw = _kwargs()
    assert kw["system_prompt"] == FILESYSTEM_SYSTEM_PROMPT
    assert kw["tools"] == mod._TOOLS
    assert kw["name"] == "filesystem_agent"
    mw = kw["middleware"]
    base = base_middleware(mod._TOOLS)
    assert [type(m) for m in mw[:len(base)]] == [type(m) for m in base]
    assert isinstance(mw[len(base)], HumanInTheLoopMiddleware)
    assert set(mw[len(base)].interrupt_on) == {"write_file"}
    assert mw[len(base) + 1] is market_desk_display
    assert len(mw) == len(base) + 2


def test_builds_a_real_agent_with_hitl_node():
    nodes = mod.build_filesystem_agent().get_graph().nodes
    assert "HumanInTheLoopMiddleware.after_model" in nodes


def test_keeps_email_addresses_it_needs_to_work():
    kw = _kwargs()
    assert not any(getattr(m, "pii_type", None) == "email" for m in kw["middleware"])
    assert not any(isinstance(m, RedactEmailsForModel) for m in kw["middleware"])


def test_prompt_tells_the_model_not_to_pre_confirm_in_prose():
    """Regression: live QA showed the model reply "Would you like me to
    proceed with writing the file X?" in plain text and end the turn WITHOUT
    calling write_file at all -- costing the user an extra "yes" before the
    real HITL approval card (which already asks for consent) ever appeared."""
    from app.agent.prompts.agents_specialist_prompts import FILESYSTEM_SYSTEM_PROMPT
    assert "do not ask the user to confirm in your reply" in FILESYSTEM_SYSTEM_PROMPT.lower()


def test_prompt_tells_the_model_the_card_already_shows_the_listing():
    """The Market Desk file_list card renders list_directory's result, so the
    reply must not repeat the whole listing in prose."""
    from app.agent.prompts.agents_specialist_prompts import FILESYSTEM_SYSTEM_PROMPT
    assert "card already lists" in FILESYSTEM_SYSTEM_PROMPT.lower()
