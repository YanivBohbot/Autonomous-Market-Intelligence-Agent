from datetime import date

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from langchain.agents.middleware import PIIMiddleware, SummarizationMiddleware

from app.agent.multi_agent.common import (
    base_middleware,
    call_limit,
    mask_credit_cards,
    redact_emails,
    specialist_model,
    strip_tool_images,
    summarization,
    today_prompt,
    tool_errors_to_messages,
)
from tests.unit.fake_chat import FakeToolModel


def test_specialist_model_uses_configured_openai_model():
    from app.core.config import settings
    m = specialist_model()
    assert m.model_name == settings.OPENAI_MODEL
    assert m.temperature == 0


def test_call_limit_is_10_per_run_and_ends_gracefully():
    m = call_limit()
    assert isinstance(m, ModelCallLimitMiddleware)
    assert m.run_limit == 10
    assert m.exit_behavior == "end"


def test_base_middleware_order():
    mw = base_middleware()
    assert mw[0] is today_prompt
    assert isinstance(mw[1], SummarizationMiddleware)
    assert isinstance(mw[2], PIIMiddleware) and mw[2].pii_type == "credit_card"
    assert isinstance(mw[3], ModelCallLimitMiddleware)
    assert mw[4] is tool_errors_to_messages
    assert len(mw) == 5


def test_summarization_triggers_at_6000_tokens_and_keeps_last_10_messages():
    m = summarization()
    assert m.trigger == ("tokens", 6000)
    assert m.keep == ("messages", 10)


def test_mask_credit_cards_and_redact_emails_configuration():
    cards = mask_credit_cards()
    assert (cards.pii_type, cards.strategy) == ("credit_card", "mask")
    emails = redact_emails()
    assert (emails.pii_type, emails.strategy) == ("email", "redact")


@pytest.mark.anyio
async def test_credit_card_is_masked_before_the_model_sees_it():
    model = FakeToolModel([AIMessage(content="ok")])
    agent = create_agent(model=model, tools=[], system_prompt="S", middleware=[mask_credit_cards()])
    await agent.ainvoke({"messages": [HumanMessage("my card is 4111 1111 1111 1111")]})
    seen = " ".join(str(m.content) for m in model.seen[0])
    assert "4111 1111 1111 1111" not in seen
    assert "1111" in seen  # last digits kept by the mask strategy


@pytest.mark.anyio
async def test_email_is_redacted_before_the_model_sees_it():
    model = FakeToolModel([AIMessage(content="ok")])
    agent = create_agent(model=model, tools=[], system_prompt="S", middleware=[redact_emails()])
    await agent.ainvoke({"messages": [HumanMessage("contact jane.doe@example.com please")]})
    seen = " ".join(str(m.content) for m in model.seen[0])
    assert "jane.doe@example.com" not in seen


@pytest.mark.anyio
async def test_today_prompt_appends_todays_date_to_the_static_prompt():
    model = FakeToolModel([AIMessage(content="hi")])
    agent = create_agent(model=model, tools=[], system_prompt="You are X.", middleware=[today_prompt])
    await agent.ainvoke({"messages": [HumanMessage("q")]})
    system_text = model.seen[0][0].content
    assert system_text.startswith("You are X.")
    assert f"Today's date is {date.today().isoformat()}." in system_text


@tool
async def _boom() -> str:
    """Always fails."""
    raise RuntimeError("kaboom")


@pytest.mark.anyio
async def test_tool_errors_become_error_tool_messages_instead_of_crashing():
    model = FakeToolModel([
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "_boom", "args": {}}]),
        AIMessage(content="recovered"),
    ])
    agent = create_agent(model=model, tools=[_boom], system_prompt="S", middleware=[tool_errors_to_messages])
    result = await agent.ainvoke({"messages": [HumanMessage("q")]})
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs[0].status == "error"
    assert "kaboom" in tool_msgs[0].content
    assert result["messages"][-1].content == "recovered"


@tool
async def _shot() -> list:
    """Returns text + image content."""
    return [{"type": "text", "text": "took screenshot"}, {"type": "image", "data": "b64", "mimeType": "image/png"}]


@pytest.mark.anyio
async def test_strip_tool_images_keeps_text_and_drops_images():
    model = FakeToolModel([
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "_shot", "args": {}}]),
        AIMessage(content="done"),
    ])
    agent = create_agent(model=model, tools=[_shot], system_prompt="S", middleware=[strip_tool_images])
    result = await agent.ainvoke({"messages": [HumanMessage("q")]})
    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    parts = tool_msg.content if isinstance(tool_msg.content, list) else [tool_msg.content]
    assert not any(isinstance(p, dict) and p.get("type") in ("image", "image_url") for p in parts)
    assert "took screenshot" in str(tool_msg.content)


@tool
def _sync_boom() -> str:
    """Always fails (sync)."""
    raise RuntimeError("sync kaboom")


def test_tool_errors_become_error_tool_messages_on_the_sync_path_too():
    model = FakeToolModel([
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "_sync_boom", "args": {}}]),
        AIMessage(content="recovered"),
    ])
    agent = create_agent(model=model, tools=[_sync_boom], system_prompt="S", middleware=[tool_errors_to_messages])
    result = agent.invoke({"messages": [HumanMessage("q")]})
    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_msg.status == "error"
    assert "sync kaboom" in tool_msg.content
