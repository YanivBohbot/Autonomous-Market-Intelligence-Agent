from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent import browser_agent as mod
from app.agent.middleware import base_middleware
from app.agent.multi_agent.display import market_desk_display


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
    from app.agent.middleware import strip_tool_images
    mw = kw["middleware"]
    base = base_middleware()
    assert [type(m) for m in mw[:len(base)]] == [type(m) for m in base]
    assert (mw[len(base)].pii_type, mw[len(base)].strategy) == ("email", "redact")
    assert mw[len(base) + 1] is market_desk_display
    assert mw[len(base) + 2] is strip_tool_images
    assert len(mw) == len(base) + 3
    assert not any(isinstance(m, HumanInTheLoopMiddleware) for m in kw["middleware"])


def test_builds_a_real_agent():
    assert "model" in mod.build_browser_agent().get_graph().nodes


def test_prompt_says_snapshot_takes_no_arguments():
    """Regression: live QA showed the model call browser_snapshot with a
    hallucinated `target` arg (e.g. "h1") the tool doesn't support, get a
    clean tool-error, then wrongly report the whole source unreachable even
    though browser_navigate had already succeeded earlier in the turn."""
    from app.agent.prompts.specialist_agent_prompts import BROWSER_SYSTEM_PROMPT
    assert "takes no arguments" in BROWSER_SYSTEM_PROMPT.lower()


def test_prompt_distinguishes_navigate_failure_from_snapshot_or_screenshot_failure():
    from app.agent.prompts.specialist_agent_prompts import BROWSER_SYSTEM_PROMPT
    assert "is not the same thing" in BROWSER_SYSTEM_PROMPT.lower()
