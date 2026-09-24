from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent import browser_agent as mod
from app.agent.multi_agent.common import base_middleware


def _kwargs():
    with patch.object(mod, "create_agent") as ca:
        mod.build_browser_agent()
    return ca.call_args.kwargs


def test_tools():
    assert {t.name for t in mod._TOOLS} == {"browser_navigate", "browser_snapshot", "browser_take_screenshot"}


def test_create_agent_call():
    kw = _kwargs()
    from app.agent.prompts.specialist_agent_prompts import BROWSER_SYSTEM_PROMPT
    assert kw["system_prompt"] == BROWSER_SYSTEM_PROMPT
    assert kw["tools"] == mod._TOOLS
    assert kw["name"] == "browser_agent"
    from app.agent.multi_agent.common import strip_tool_images
    mw = kw["middleware"]
    base = base_middleware()
    assert [type(m) for m in mw[:len(base)]] == [type(m) for m in base]
    assert (mw[len(base)].pii_type, mw[len(base)].strategy) == ("email", "redact")
    assert mw[len(base) + 1] is strip_tool_images
    assert len(mw) == len(base) + 2
    assert not any(isinstance(m, HumanInTheLoopMiddleware) for m in kw["middleware"])


def test_builds_a_real_agent():
    assert "model" in mod.build_browser_agent().get_graph().nodes
