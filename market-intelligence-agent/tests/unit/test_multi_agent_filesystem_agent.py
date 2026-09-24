from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent import filesystem_agent as mod
from app.agent.multi_agent.common import base_middleware


def _kwargs():
    with patch.object(mod, "create_agent") as ca:
        mod.build_filesystem_agent()
    return ca.call_args.kwargs


def test_tools():
    assert {t.name for t in mod._TOOLS} == {"read_text_file", "list_directory", "write_file"}


def test_create_agent_call_with_hitl_on_write_file():
    from app.agent.prompts.specialist_agent_prompts import FILESYSTEM_SYSTEM_PROMPT
    kw = _kwargs()
    assert kw["system_prompt"] == FILESYSTEM_SYSTEM_PROMPT
    assert kw["tools"] == mod._TOOLS
    assert kw["name"] == "filesystem_agent"
    mw = kw["middleware"]
    base = base_middleware()
    assert [type(m) for m in mw[:len(base)]] == [type(m) for m in base]
    assert isinstance(mw[len(base)], HumanInTheLoopMiddleware)
    assert set(mw[len(base)].interrupt_on) == {"write_file"}
    assert len(mw) == len(base) + 1


def test_builds_a_real_agent_with_hitl_node():
    nodes = mod.build_filesystem_agent().get_graph().nodes
    assert "HumanInTheLoopMiddleware.after_model" in nodes


def test_keeps_email_addresses_it_needs_to_work():
    kw = _kwargs()
    assert not any(getattr(m, "pii_type", None) == "email" for m in kw["middleware"])
