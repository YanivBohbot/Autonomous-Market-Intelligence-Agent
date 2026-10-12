from datetime import date

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)
from langchain_openai.middleware import OpenAIModerationMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from langchain.agents.middleware import PIIMiddleware, SummarizationMiddleware

from app.agent.middleware import (
    base_middleware,
    call_limit,
    client_context_prompt,
    fresh_documents_prompt,
    mask_credit_cards,
    redact_emails,
    specialist_model,
    strip_tool_images,
    summarization,
    today_prompt,
    tool_errors_to_messages,
)
from app.agent.orchestration.state import ClientContextState
from app.agent.prompts.ingested_documents_prompt import INGESTED_DOCUMENTS_PLACEHOLDER
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


def test_model_retry_uses_default_backoff():
    from app.agent.middleware import model_retry
    m = model_retry()
    assert isinstance(m, ModelRetryMiddleware)
    assert m.max_retries == 2


def test_model_fallback_is_none_without_an_anthropic_key(monkeypatch):
    import app.agent.middleware as mod
    monkeypatch.setattr(mod.settings, "ANTHROPIC_API_KEY", "")
    assert mod.model_fallback() is None


def test_model_fallback_targets_claude_when_a_key_is_configured(monkeypatch):
    import app.agent.middleware as mod
    monkeypatch.setattr(mod.settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    fb = mod.model_fallback()
    assert isinstance(fb, ModelFallbackMiddleware)


def test_summarization_triggers_at_6000_tokens_and_keeps_last_50_messages():
    m = summarization()
    assert m.trigger == ("tokens", 6000)
    assert m.keep == ("messages", 50)


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


@pytest.mark.anyio
async def test_client_context_prompt_appends_the_active_client_when_set():
    model = FakeToolModel([AIMessage(content="hi")])
    agent = create_agent(
        model=model, tools=[], system_prompt="You are X.",
        middleware=[client_context_prompt], state_schema=ClientContextState,
    )
    await agent.ainvoke({
        "messages": [HumanMessage("q")],
        "client_context": "Active client: Jane Doe, segment VIP, risk balanced, advisor Sam.",
    })
    system_text = model.seen[0][0].content
    assert system_text.startswith("You are X.")
    assert "Active client: Jane Doe" in system_text


@pytest.mark.anyio
async def test_client_context_prompt_leaves_the_prompt_unchanged_when_unset():
    model = FakeToolModel([AIMessage(content="hi")])
    agent = create_agent(
        model=model, tools=[], system_prompt="You are X.",
        middleware=[client_context_prompt], state_schema=ClientContextState,
    )
    await agent.ainvoke({"messages": [HumanMessage("q")]})
    assert model.seen[0][0].content == "You are X."


@pytest.mark.anyio
async def test_fresh_documents_prompt_substitutes_the_live_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text('["report-a.pdf"]', encoding="utf-8")
    monkeypatch.setattr(
        "app.agent.prompts.ingested_documents_prompt._KB_MANIFEST_PATH", manifest
    )

    model = FakeToolModel([AIMessage(content="hi"), AIMessage(content="hi again")])
    agent = create_agent(
        model=model,
        tools=[],
        system_prompt=f"Docs: {INGESTED_DOCUMENTS_PLACEHOLDER}",
        middleware=[fresh_documents_prompt],
    )
    await agent.ainvoke({"messages": [HumanMessage("q")]})
    assert model.seen[0][0].content == "Docs: report-a.pdf"

    # A document uploaded AFTER the agent was built (no rebuild/restart)
    # must still show up on the next call -- this is the whole point.
    manifest.write_text('["report-a.pdf", "report-b.pdf"]', encoding="utf-8")
    await agent.ainvoke({"messages": [HumanMessage("q2")]})
    assert model.seen[-1][0].content == "Docs: report-a.pdf, report-b.pdf"


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


def test_summary_model_output_is_hidden_from_ag_ui_streams():
    # Live QA: the summary text streamed into the Market Desk chat as if it
    # were the agent's answer. ag-ui-langgraph skips chunks whose run
    # metadata says emit-messages False; a chat model's own metadata is
    # merged into its run metadata.
    metadata = summarization().model.metadata
    assert metadata["emit-messages"] is False
    assert metadata["emit-tool-calls"] is False


@tool
def read_query(sql: str) -> str:
    """Read-only test tool."""
    return "rows"


@tool
def send_email(recipient: str, subject: str, body: str) -> str:
    """Side-effect test tool."""
    return "sent"


def test_base_middleware_order(monkeypatch):
    import app.agent.middleware as mod
    monkeypatch.setattr(mod.settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(mod.settings, "MODERATION_ENABLED", True)
    mw = base_middleware([read_query, send_email])
    assert isinstance(mw[0], PIIMiddleware) and mw[0].pii_type == "credit_card"
    assert isinstance(mw[1], OpenAIModerationMiddleware)
    assert mw[2] is today_prompt
    assert isinstance(mw[3], ContextEditingMiddleware)
    assert isinstance(mw[4], SummarizationMiddleware)
    assert isinstance(mw[5], ModelCallLimitMiddleware)
    assert isinstance(mw[6], ModelRetryMiddleware)
    assert mw[7] is tool_errors_to_messages
    assert isinstance(mw[8], ToolRetryMiddleware)  # inside ToolErrorMiddleware
    assert len(mw) == 9


def test_base_middleware_includes_fallback_before_retry_when_key_configured(monkeypatch):
    import app.agent.middleware as mod
    monkeypatch.setattr(mod.settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(mod.settings, "MODERATION_ENABLED", False)
    mw = base_middleware([read_query])
    assert isinstance(mw[5], ModelFallbackMiddleware)
    assert isinstance(mw[6], ModelRetryMiddleware)
    assert mw[7] is tool_errors_to_messages
    assert isinstance(mw[8], ToolRetryMiddleware)
    assert len(mw) == 9


def test_moderation_is_omitted_when_disabled(monkeypatch):
    import app.agent.middleware as mod
    monkeypatch.setattr(mod.settings, "MODERATION_ENABLED", False)
    assert mod.moderation() is None
    assert not any(isinstance(m, OpenAIModerationMiddleware) for m in base_middleware([read_query]))


def test_moderation_configuration(monkeypatch):
    import app.agent.middleware as mod
    monkeypatch.setattr(mod.settings, "MODERATION_ENABLED", True)
    m = mod.moderation()
    assert m.model == "omni-moderation-latest"
    assert (m.check_input, m.check_output, m.exit_behavior) == (True, True, "end")
    assert m.violation_message == mod.MODERATION_VIOLATION_MESSAGE


def test_no_sensitive_data_guard_left():
    import app.agent.guardrails as guardrails
    assert not hasattr(guardrails, "SensitiveDataGuard")


def test_pii_middleware_configuration():
    cards = mask_credit_cards()
    assert (cards.pii_type, cards.strategy) == ("credit_card", "mask")
    assert (cards.apply_to_input, cards.apply_to_output, cards.apply_to_tool_results) == (True, True, True)
    from app.agent.middleware import RedactEmailsForModel
    assert isinstance(redact_emails(), RedactEmailsForModel)


def test_tool_retry_covers_only_read_only_tools():
    from app.agent.middleware import tool_retry
    m = tool_retry([read_query, send_email])
    assert m._tool_filter == ["read_query"]
    assert m.max_retries == 2


def test_tool_retry_is_omitted_when_no_read_only_tools():
    from app.agent.middleware import tool_retry
    assert tool_retry([send_email]) is None


@pytest.mark.anyio
async def test_side_effect_tool_is_never_retried():
    from app.agent.middleware import tool_retry
    calls = {"n": 0}

    @tool("send_email")
    def flaky_send(recipient: str) -> str:
        """Side-effect tool that always fails."""
        calls["n"] += 1
        raise RuntimeError("smtp down")

    model = FakeToolModel([
        AIMessage(content="", tool_calls=[{"name": "send_email", "args": {"recipient": "a@b.c"}, "id": "c1"}]),
        AIMessage(content="done"),
    ])
    retry = tool_retry([flaky_send, read_query])
    agent = create_agent(model=model, tools=[flaky_send], system_prompt="S",
                         middleware=[tool_errors_to_messages, retry])
    await agent.ainvoke({"messages": [HumanMessage("send it")]})
    assert calls["n"] == 1


@pytest.mark.anyio
async def test_read_only_tool_is_retried_after_a_transient_failure():
    from app.agent.middleware import tool_retry
    calls = {"n": 0}

    @tool("read_query")
    def flaky_read(sql: str) -> str:
        """Read-only tool that fails once."""
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("mcp hiccup")
        return "rows"

    model = FakeToolModel([
        AIMessage(content="", tool_calls=[{"name": "read_query", "args": {"sql": "x"}, "id": "c1"}]),
        AIMessage(content="done"),
    ])
    agent = create_agent(model=model, tools=[flaky_read], system_prompt="S",
                         middleware=[tool_errors_to_messages, tool_retry([flaky_read])])
    result = await agent.ainvoke({"messages": [HumanMessage("query")]})
    assert calls["n"] == 2
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs[-1].content == "rows"


def test_tool_call_limits_on_rag_and_browser():
    from unittest.mock import patch
    import app.agent.agents_specialist.rag_agent as rag_mod
    import app.agent.agents_specialist.browser_agent as browser_mod
    for mod, build, tool_name, limit in (
        (rag_mod, "build_rag_agent", "web_search", 3),
        (browser_mod, "build_browser_agent", "browser_navigate", 5),
    ):
        with patch.object(mod, "create_agent") as ca:
            getattr(mod, build)()
        mw = ca.call_args.kwargs["middleware"]
        limits = [m for m in mw if isinstance(m, ToolCallLimitMiddleware)]
        assert [(m.tool_name, m.run_limit, m.exit_behavior) for m in limits] == [(tool_name, limit, "continue")]


@pytest.mark.anyio
async def test_email_redaction_does_not_rewrite_shared_history():
    """rag/finance/browser hide addresses from their model (third-party
    queries), but the stored conversation keeps them: a later email_agent
    hop in the same thread needs the real recipient."""
    model = FakeToolModel([AIMessage(content="ok")])
    agent = create_agent(model=model, tools=[], system_prompt="S", middleware=[redact_emails()])
    result = await agent.ainvoke(
        {"messages": [HumanMessage("news on AAPL then email margaret.collins@example.com")]}
    )
    seen = " ".join(str(m.content) for m in model.seen[0])
    assert "margaret.collins@example.com" not in seen
    stored = " ".join(str(m.content) for m in result["messages"])
    assert "margaret.collins@example.com" in stored
