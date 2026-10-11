# Guardrails on Prebuilt Middleware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop sensitive data before the supervisor's LLM call, and replace custom guard code with LangChain's prebuilt guardrail, moderation and tool-reliability middleware.

**Architecture:**
- A graph node `input_guard` (between `record_question` and `supervisor`) blocks credit cards using the official `detect_credit_card`.
- Specialists drop the custom `SensitiveDataGuard` and get prebuilt middleware from `base_middleware(tools)`:
  - `PIIMiddleware` (card mask in/out/tool results; email redaction in/out only on third-party specialists);
  - `OpenAIModerationMiddleware`;
  - `ToolRetryMiddleware` limited to read-only tools.
- `ToolCallLimitMiddleware` caps `web_search` and `browser_navigate`.

**Tech Stack:** langchain 1.4.2 (`langchain.agents.middleware`), langchain-openai (`langchain_openai.middleware.OpenAIModerationMiddleware`), LangGraph `Command`, FastAPI SSE, pytest + anyio.

**Spec:** `docs/superpowers/specs/2026-10-12-guardrails-prebuilt-middleware-design.md`

## Global Constraints

- Every Python command is prefixed with `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui` and run from the worktree root. The worktree `.venv` is broken by MAX_PATH.
- **Targeted tests only. Never run the full suite** (user rule). Each task names its test files.
- Use modern LangChain packages only. No `langchain-classic`.
- Never retry side-effect tools (`send_email`, `write_file`, `save_memory`, `save_portfolio_report`).
- Never apply email PII middleware to `email_agent`, `portfolio_agent`, `memory_agent` or `filesystem_agent`.
- Live QA never sends a real email: always reject the approval.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A follow-up turn after a blocked card message.** A clean question in the next turn must reach the supervisor, because the guard checks only the latest `HumanMessage`. Pinned by `test_clean_turn_after_blocked_turn_reaches_supervisor` (Task 1).
2. **A content-block list message (Market Desk / AG-UI shape)** containing a card must still be detected. Pinned by `test_detection_handles_content_block_lists` (Task 1).
3. **A specialist with zero read-only tools** must not get `ToolRetryMiddleware(tools=[])`. `tools=[]` would be a filter matching nothing, which is harmless, but `None` would retry everything. Pinned by `test_tool_retry_is_omitted_when_no_read_only_tools` (Task 2).
4. **A side-effect tool that raises** must run exactly once. Pinned by `test_side_effect_tool_is_never_retried` (Task 2).
5. **Unit tests must not hit the OpenAI moderation API.** `MODERATION_ENABLED=false` is set in `tests/conftest.py` (Task 2).

---

### Task 1: Official detectors + graph-level `input_guard`

**Files:**
- Modify: `app/agent/guardrails/detection.py` (full rewrite)
- Create: `app/agent/guardrails/input_guard.py`
- Modify: `app/agent/guardrails/__init__.py`
- Modify: `app/agent/multi_agent/graph.py` (`_build_workflow`)
- Test: `tests/unit/test_guardrails.py` (detection tests kept, new input_guard tests)
- Test: `tests/unit/test_multi_agent_graph_structure.py`

**Interfaces:**
- Produces: `contains_credit_card(content) -> bool`, `contains_email(content) -> bool`, `contains_sensitive_data(content, *, check_email=True) -> bool`, `SENSITIVE_DATA_WARNING: str`, `input_guard(state) -> Command[Literal["supervisor", "finalize_turn"]]`, and the graph node name `"input_guard"`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_guardrails.py`. Keep the 5 existing `contains_*` tests and the `test_contains_credit_card_and_contains_email_are_independent` test. Delete the three `SensitiveDataGuard` tests and the `# --- single-agent node ---` marker (Task 2 removes the class). Fix the imports to:

```python
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.guardrails import SENSITIVE_DATA_WARNING, contains_sensitive_data
from app.agent.guardrails.detection import contains_credit_card, contains_email
```

Append:

```python
def test_detection_handles_content_block_lists():
    content = [{"type": "text", "text": "my card is 4111 1111 1111 1111"}]
    assert contains_credit_card(content) is True
    assert contains_credit_card([{"type": "image_url", "image_url": {"url": "x"}}]) is False


def test_detection_does_not_call_pii_middleware_hooks():
    import inspect
    import app.agent.guardrails.detection as detection
    assert "before_model" not in inspect.getsource(detection)


def _run_graph(question: str, thread_id: str, router_mock):
    from app.agent.multi_agent import build_multi_agent_app
    from app.agent.multi_agent.supervisor import RoutingDecision
    router_mock.invoke.return_value = RoutingDecision(next="FINISH", reasoning="done")
    graph = build_multi_agent_app(InMemorySaver())
    return graph, graph.invoke(
        {"question": question}, {"configurable": {"thread_id": thread_id}}
    )


def test_input_guard_blocks_card_before_the_supervisor_llm_is_called():
    import app.agent.multi_agent.supervisor as supervisor_mod
    with patch.object(supervisor_mod, "_router") as router_mock:
        _, result = _run_graph("my card is 4111 1111 1111 1111", "t-guard-1", router_mock)
    router_mock.invoke.assert_not_called()
    assert result["messages"][-1].content == SENSITIVE_DATA_WARNING


def test_input_guard_lets_clean_questions_reach_the_supervisor():
    import app.agent.multi_agent.supervisor as supervisor_mod
    with patch.object(supervisor_mod, "_router") as router_mock:
        _run_graph("what is the price of AAPL?", "t-guard-2", router_mock)
    router_mock.invoke.assert_called_once()


def test_clean_turn_after_blocked_turn_reaches_supervisor():
    import app.agent.multi_agent.supervisor as supervisor_mod
    with patch.object(supervisor_mod, "_router") as router_mock:
        graph, _ = _run_graph("my card is 4111 1111 1111 1111", "t-guard-3", router_mock)
        router_mock.invoke.assert_not_called()
        graph.invoke(
            {"question": "what is the price of AAPL?"},
            {"configurable": {"thread_id": "t-guard-3"}},
        )
    router_mock.invoke.assert_called_once()
```

In `tests/unit/test_multi_agent_graph_structure.py`, add `"input_guard"` to the node-name tuple in `test_graph_has_supervisor_and_specialist_nodes`, and append:

```python
def test_input_guard_sits_between_record_question_and_supervisor():
    edges = {(e.source, e.target) for e in _build().get_graph().edges}
    assert ("record_question", "input_guard") in edges
    assert ("record_question", "supervisor") not in edges
    assert ("input_guard", "supervisor") in edges
    assert ("input_guard", "finalize_turn") in edges
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_guardrails.py tests/unit/test_multi_agent_graph_structure.py -q`
Expected: FAIL. `test_detection_does_not_call_pii_middleware_hooks` fails (the current source calls `before_model`), the input_guard tests fail (the router is called), and the edge test fails.

- [ ] **Step 3: Rewrite `app/agent/guardrails/detection.py`**

```python
"""Sensitive-data detection built on LangChain's documented PII detectors
(`langchain.agents.middleware.pii`), the same ones PIIMiddleware uses."""

from typing import Any

from langchain.agents.middleware.pii import detect_credit_card, detect_email

SENSITIVE_DATA_WARNING = (
    "This message appears to contain a credit card number. Sharing this kind "
    "of information in chat is not allowed, so I can't process this request "
    "— please resend your question without it."
)

Content = str | list[str | dict[str, Any]] | None


def _text(content: Content) -> str:
    """Flatten a message's content (a string or a content-block list) to its text."""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return " ".join(parts)


def contains_credit_card(content: Content) -> bool:
    """True if `content` contains a Luhn-valid credit card number."""
    return bool(detect_credit_card(_text(content)))


def contains_email(content: Content) -> bool:
    """True if `content` contains an email address."""
    return bool(detect_email(_text(content)))


def contains_sensitive_data(content: Content, *, check_email: bool = True) -> bool:
    """True if `content` contains a credit card number, or — when
    `check_email` — an email address."""
    if contains_credit_card(content):
        return True
    return check_email and contains_email(content)
```

- [ ] **Step 4: Create `app/agent/guardrails/input_guard.py`**

```python
"""Graph-level input guardrail: runs before the supervisor, whose router is
a raw ChatOpenAI call that no create_agent middleware can wrap. Without this
node a credit-card number reached OpenAI (via the supervisor) before any
specialist guard could block it."""

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.agent.guardrails.detection import SENSITIVE_DATA_WARNING, contains_credit_card


def input_guard(state) -> Command[Literal["supervisor", "finalize_turn"]]:
    """Ends the turn with a warning, and no LLM call, if the latest user
    message contains a credit card number. Emails pass: several specialists
    need real addresses, and the third-party ones redact them instead."""
    messages = state.get("messages", [])
    latest = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
    if latest is not None and contains_credit_card(latest.content):
        return Command(
            goto="finalize_turn",
            update={"messages": [AIMessage(content=SENSITIVE_DATA_WARNING)]},
        )
    return Command(goto="supervisor")
```

- [ ] **Step 5: Export it.** In `app/agent/guardrails/__init__.py`, replace the docstring and exports (keep `SensitiveDataGuard` exported until Task 2 deletes it, so nothing breaks in between):

```python
"""Guardrails: sensitive-data detection and the graph-level input guard.

Request-level blocking happens in `input_guard`, before the supervisor.
Specialists add LangChain's prebuilt PIIMiddleware / OpenAIModerationMiddleware
(see `app/agent/middleware.py`)."""

from app.agent.guardrails.detection import SENSITIVE_DATA_WARNING, contains_sensitive_data
from app.agent.guardrails.input_guard import input_guard
from app.agent.guardrails.middleware import SensitiveDataGuard

__all__ = [
    "SENSITIVE_DATA_WARNING",
    "SensitiveDataGuard",
    "contains_sensitive_data",
    "input_guard",
]
```

- [ ] **Step 6: Wire the node** in `app/agent/multi_agent/graph.py`. Add the import `from app.agent.guardrails import input_guard`. In `_build_workflow`, after `workflow.add_node("record_question", ...)`, add:

```python
    # Before the supervisor: its router is a raw LLM call no middleware wraps.
    workflow.add_node(
        "input_guard", input_guard, destinations=("supervisor", "finalize_turn")
    )
```

Replace `workflow.add_edge("record_question", "supervisor")` with `workflow.add_edge("record_question", "input_guard")`.

- [ ] **Step 7: Run the tests and watch them pass**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_guardrails.py tests/unit/test_multi_agent_graph_structure.py tests/unit/test_multi_agent_question_reaches_messages.py -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/agent/guardrails app/agent/multi_agent/graph.py tests/unit/test_guardrails.py tests/unit/test_multi_agent_graph_structure.py
git commit -m "feat(guardrails): block credit cards in a graph node before the supervisor LLM

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Prebuilt middleware in `base_middleware(tools)`

**Files:**
- Modify: `app/core/config.py` (add `MODERATION_ENABLED: bool = True` next to `ANTHROPIC_API_KEY`)
- Modify: `tests/conftest.py` (add `os.environ.setdefault("MODERATION_ENABLED", "false")` after the other `setdefault` lines)
- Modify: `app/agent/middleware.py`
- Delete: `app/agent/guardrails/middleware.py`; drop `SensitiveDataGuard` from `app/agent/guardrails/__init__.py`
- Modify: the 7 specialist files `app/agent/multi_agent/{rag,finance,browser,email,portfolio,memory,filesystem}_agent.py`
- Test: `tests/unit/test_middleware.py`, `tests/unit/test_multi_agent_{email,portfolio,memory,filesystem}_agent.py`

**Interfaces:**
- Consumes: `is_read_only(name)` from `app.agent.tools`.
- Produces: `base_middleware(tools: Sequence[BaseTool]) -> list[AgentMiddleware]`, `mask_credit_cards() -> PIIMiddleware`, `redact_emails() -> PIIMiddleware`, `moderation() -> OpenAIModerationMiddleware | None`, `tool_retry(tools) -> ToolRetryMiddleware | None`, `MODERATION_VIOLATION_MESSAGE: str`.

Ruling taken in planning: moderation uses one instance with `exit_behavior="end"`. On input this ends the run with no model call. On output the flagged answer stays in state with the violation message appended after it (`"replace"` would rewrite the user message and still call the model). The spec's "replaces the answer in state" line is corrected in Task 4.

- [ ] **Step 1: Write the failing tests.** In `tests/unit/test_middleware.py`:
  - Remove the `SensitiveDataGuard` import and `test_base_middleware_check_email_false_for_specialists_that_need_real_addresses`.
  - Replace `test_base_middleware_order` and `test_base_middleware_includes_fallback_before_retry_when_key_configured` with the code below.
  - Replace `test_mask_credit_cards_and_redact_emails_configuration` with the configuration test below.
  - Add the imports `ToolCallLimitMiddleware, ToolRetryMiddleware` from `langchain.agents.middleware` and `from langchain_openai.middleware import OpenAIModerationMiddleware`.

```python
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
    assert isinstance(mw[3], SummarizationMiddleware)
    assert isinstance(mw[4], ModelCallLimitMiddleware)
    assert isinstance(mw[5], ModelRetryMiddleware)
    assert mw[6] is tool_errors_to_messages
    assert isinstance(mw[7], ToolRetryMiddleware)  # inside ToolErrorMiddleware
    assert len(mw) == 8


def test_base_middleware_includes_fallback_before_retry_when_key_configured(monkeypatch):
    import app.agent.middleware as mod
    monkeypatch.setattr(mod.settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(mod.settings, "MODERATION_ENABLED", False)
    mw = base_middleware([read_query])
    assert isinstance(mw[3], ModelFallbackMiddleware)
    assert isinstance(mw[4], ModelRetryMiddleware)
    assert mw[5] is tool_errors_to_messages
    assert isinstance(mw[6], ToolRetryMiddleware)
    assert len(mw) == 7


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
    emails = redact_emails()
    assert (emails.pii_type, emails.strategy) == ("email", "redact")
    assert (emails.apply_to_input, emails.apply_to_output) == (True, True)


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


@pytest.mark.anyio
async def test_email_redacted_in_model_output():
    model = FakeToolModel([AIMessage(content="write to jane.doe@example.com")])
    agent = create_agent(model=model, tools=[], system_prompt="S", middleware=[redact_emails()])
    result = await agent.ainvoke({"messages": [HumanMessage("who?")]})
    assert "jane.doe@example.com" not in result["messages"][-1].content
```

In each of `tests/unit/test_multi_agent_{email,portfolio,memory,filesystem}_agent.py`, replace the `SensitiveDataGuard` import and the two-line `guard = next(...)` / `assert guard.check_email is False` block with:

```python
    assert not any(
        isinstance(m, PIIMiddleware) and m.pii_type == "email" for m in kw["middleware"]
    )
```

and add `from langchain.agents.middleware import PIIMiddleware` to the imports. If `PIIMiddleware` is already imported, don't import it twice.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_middleware.py tests/unit/test_multi_agent_email_agent.py tests/unit/test_multi_agent_portfolio_agent.py tests/unit/test_multi_agent_memory_agent.py tests/unit/test_multi_agent_filesystem_agent.py -q`
Expected: FAIL. `base_middleware` takes no positional argument, and `moderation`/`tool_retry` don't exist.

- [ ] **Step 3: Implement in `app/agent/middleware.py`.**
  - Fix the module docstring's mention of `app/agent/common.py`, if any.
  - Remove `from app.agent.guardrails import SensitiveDataGuard`.
  - Add to the `langchain.agents.middleware` import: `ToolRetryMiddleware`.
  - Add the imports `from collections.abc import Sequence`, `from langchain_core.tools import BaseTool` and `from langchain_openai.middleware import OpenAIModerationMiddleware`.
  - Add `from app.agent.tools import is_read_only`. Check that this import introduces no cycle: `app.agent.tools` does not import `app.agent.middleware`.
  - Replace `mask_credit_cards`, `redact_emails` and `base_middleware` with:

```python
MODERATION_VIOLATION_MESSAGE = (
    "This request was flagged by our content-safety check, so I can't help "
    "with it. Please rephrase your question."
)


def mask_credit_cards() -> PIIMiddleware:
    """No specialist needs a card number: mask it (last 4 digits kept) in
    user input, in tool results and in the model's own answer. Defense in
    depth behind the graph-level input_guard, which blocks cards in the
    user's message before the supervisor."""
    return PIIMiddleware(
        "credit_card",
        strategy="mask",
        apply_to_input=True,
        apply_to_output=True,
        apply_to_tool_results=True,
    )


def redact_emails() -> PIIMiddleware:
    """For specialists that send queries to third parties (Tavily, Yahoo,
    web pages) and never need an address: redacted in input and output.
    NOT for email/portfolio/memory/filesystem — apply_to_output also
    rewrites tool-call arguments, which would erase send_email's recipient."""
    return PIIMiddleware("email", strategy="redact", apply_to_input=True, apply_to_output=True)


def moderation() -> OpenAIModerationMiddleware | None:
    """Model-based guardrail (OpenAI moderation) on user input and model
    output; a violation ends the run with MODERATION_VIOLATION_MESSAGE.
    `None` (omitted) when MODERATION_ENABLED is false, e.g. in unit tests."""
    if not settings.MODERATION_ENABLED:
        return None
    return OpenAIModerationMiddleware(
        model="omni-moderation-latest",
        check_input=True,
        check_output=True,
        exit_behavior="end",
        violation_message=MODERATION_VIOLATION_MESSAGE,
    )


def tool_retry(tools: Sequence[BaseTool]) -> ToolRetryMiddleware | None:
    """Retries flaky network tools (yfinance, MCP, Tavily) before the error
    reaches tool_errors_to_messages. Read-only tools only: retrying
    send_email/write_file/save_memory could repeat a side effect. `None`
    when the specialist has no read-only tool (an empty filter is avoided
    on purpose: `tools=None` would mean "retry everything")."""
    names = [t.name for t in tools if is_read_only(t.name)]
    if not names:
        return None
    return ToolRetryMiddleware(max_retries=2, tools=names, on_failure="error")


def base_middleware(tools: Sequence[BaseTool]) -> list[AgentMiddleware[Any, Any, Any]]:
    """Middleware every specialist gets. `tools` is the specialist's own tool
    list, used to scope tool_retry() to its read-only tools."""
    middleware: list[AgentMiddleware[Any, Any, Any]] = [mask_credit_cards()]
    moderation_mw = moderation()
    if moderation_mw is not None:
        # After the card mask, so the moderation API never sees a card number.
        middleware.append(moderation_mw)
    middleware += [today_prompt, summarization(), call_limit()]
    fallback = model_fallback()
    if fallback is not None:
        # Must precede model_retry() — see model_fallback()'s docstring.
        middleware.append(fallback)
    middleware.append(model_retry())
    middleware.append(tool_errors_to_messages)
    retry = tool_retry(tools)
    if retry is not None:
        # Listed after ToolErrorMiddleware = wrapped inside it: retries run
        # first, and only the final failure becomes an error ToolMessage.
        middleware.append(retry)
    return middleware
```

- [ ] **Step 4: Update the specialists.** Each one already defines `_TOOLS`. Change every call site:
  - `rag_agent.py`, `finance_agent.py`, `browser_agent.py`: `*base_middleware()` becomes `*base_middleware(_TOOLS)`. Keep `redact_emails()`.
  - `email_agent.py`, `portfolio_agent.py`, `memory_agent.py`, `filesystem_agent.py`: `*base_middleware(check_email=False)` becomes `*base_middleware(_TOOLS)`.

  Then delete `app/agent/guardrails/middleware.py`, and in `app/agent/guardrails/__init__.py` remove the `SensitiveDataGuard` import and its `__all__` entry. Add `MODERATION_ENABLED: bool = True` to `app/core/config.py`, and `os.environ.setdefault("MODERATION_ENABLED", "false")` to `tests/conftest.py`.

- [ ] **Step 5: Check that no reference is left**

Run: `grep -rn "SensitiveDataGuard\|check_email=False\|base_middleware()" app tests --include=*.py`
Expected: no output. (`tests/unit/test_stream.py` still names the old node string; Task 3 changes it.)

- [ ] **Step 6: Run the tests and watch them pass**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_middleware.py tests/unit/test_guardrails.py tests/unit/test_multi_agent_email_agent.py tests/unit/test_multi_agent_portfolio_agent.py tests/unit/test_multi_agent_memory_agent.py tests/unit/test_multi_agent_filesystem_agent.py tests/unit/test_multi_agent_graph_structure.py -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add -A app tests
git commit -m "feat(guardrails): replace SensitiveDataGuard with prebuilt PII, moderation and tool-retry middleware

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Tool-call limits + `/stream` blocking messages

**Files:**
- Modify: `app/agent/middleware.py` (add `tool_call_limit`)
- Modify: `app/agent/multi_agent/rag_agent.py`, `app/agent/multi_agent/browser_agent.py`
- Modify: `app/api/routers/stream.py` (`_GUARD_NODE` → `_STATIC_MESSAGE_NODES`)
- Test: `tests/unit/test_middleware.py`, `tests/unit/test_stream.py`, plus `tests/unit/test_multi_agent_rag_agent.py` / `test_multi_agent_browser_agent.py` if they exist

**Interfaces:**
- Consumes: `base_middleware(tools)` from Task 2.
- Produces: `tool_call_limit(tool_name: str, run_limit: int) -> ToolCallLimitMiddleware`, and `_STATIC_MESSAGE_NODES = {"input_guard", "OpenAIModerationMiddleware.before_model", "OpenAIModerationMiddleware.after_model"}`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/unit/test_middleware.py`:

```python
def test_tool_call_limits_on_rag_and_browser():
    from unittest.mock import patch
    import app.agent.multi_agent.rag_agent as rag_mod
    import app.agent.multi_agent.browser_agent as browser_mod
    for mod, tool_name, limit in ((rag_mod, "web_search", 3), (browser_mod, "browser_navigate", 5)):
        with patch.object(mod, "create_agent") as ca:
            getattr(mod, f"build_{mod.__name__.rsplit('.', 1)[1]}")()
        mw = ca.call_args.kwargs["middleware"]
        limits = [m for m in mw if isinstance(m, ToolCallLimitMiddleware)]
        assert [(m.tool_name, m.run_limit, m.exit_behavior) for m in limits] == [(tool_name, limit, "continue")]
```

In `tests/unit/test_stream.py`, rename `test_stream_emits_sensitive_data_guard_warning_as_token` to `test_stream_emits_input_guard_warning_as_token`. Change its update tuple to `((), {"input_guard": {"messages": [warning_msg]}})` and update the docstring ("input_guard, the graph node before the supervisor, adds its warning AIMessage straight to state…"). Then append:

```python
def test_stream_emits_moderation_violation_as_token():
    from app.agent.middleware import MODERATION_VIOLATION_MESSAGE
    msg = AIMessage(content=MODERATION_VIOLATION_MESSAGE)
    updates = [(("rag_agent:x",), {"OpenAIModerationMiddleware.before_model": {"messages": [msg]}})]
    app.state.agent_app = _FakeAgentApp([], updates=updates)
    response = TestClient(app).post("/stream", json={"query": "bad", "thread_id": "t-mod"})
    tokens = [d["token"] for e, d in _parse_sse(response.text) if e == "token"]
    assert tokens == [MODERATION_VIOLATION_MESSAGE]
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_middleware.py tests/unit/test_stream.py -q`
Expected: FAIL on the limits test and both stream tests (zero tokens).

- [ ] **Step 3: Implement.** In `app/agent/middleware.py`, add `ToolCallLimitMiddleware` to the import, and:

```python
def tool_call_limit(tool_name: str, run_limit: int) -> ToolCallLimitMiddleware:
    """Caps a costly/loop-prone tool per run; "continue" lets the model
    answer with what it already has instead of failing the run."""
    return ToolCallLimitMiddleware(tool_name=tool_name, run_limit=run_limit, exit_behavior="continue")
```

In `rag_agent.py`, import `tool_call_limit` and insert `tool_call_limit("web_search", 3)` right after `redact_emails()` in the middleware list. In `browser_agent.py`, insert `tool_call_limit("browser_navigate", 5)` right after `redact_emails()`.

In `app/api/routers/stream.py`, replace the `_GUARD_NODE` comment and constant with:

```python
# Nodes that add a blocking AIMessage straight to state instead of streaming
# it: the graph-level input_guard, and OpenAIModerationMiddleware's hooks
# inside a specialist subgraph.
_STATIC_MESSAGE_NODES = {
    "input_guard",
    "OpenAIModerationMiddleware.before_model",
    "OpenAIModerationMiddleware.after_model",
}
```

In `_static_message_content`, change `node_name != _GUARD_NODE` to `node_name not in _STATIC_MESSAGE_NODES` and update its docstring's first words from "SensitiveDataGuard's blocking AIMessage" to "A guardrail's blocking AIMessage".

- [ ] **Step 4: Run the tests and watch them pass**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_middleware.py tests/unit/test_stream.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/middleware.py app/agent/multi_agent/rag_agent.py app/agent/multi_agent/browser_agent.py app/api/routers/stream.py tests/unit/test_middleware.py tests/unit/test_stream.py
git commit -m "feat(guardrails): cap web_search/browser_navigate calls, stream guard and moderation messages

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Docs + live QA

**Files:**
- Modify: `CLAUDE.md`: the "Agent graph" paragraph (`SensitiveDataGuard` → `input_guard` + prebuilt middleware), the multi-agent flow line (`record_question → input_guard → supervisor`), the `base_middleware` bullet, and a new `MODERATION_ENABLED` entry (default True) in the optional `.env` list.
- Modify: `AGENTS.md`, only where it names `SensitiveDataGuard` or `check_email` (`grep -n "SensitiveDataGuard\|check_email" AGENTS.md docs/TOOLS.md`).
- Modify: the spec's output-moderation bullet, which now says the flagged answer stays in state with the violation message appended (`exit_behavior="end"`).

- [ ] **Step 1: Edit the docs** listed above. Edit only; never delete unrelated content.
- [ ] **Step 2: Restart the backend.** Stop background task `btiybvtu1` with TaskStop, then run in the background: `cd <worktree> && UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000`. Wait for "Application startup complete".
- [ ] **Step 3: Live QA through `/stream`** (fresh thread ids `qa-guard-<n>`, never real `clients_<id>` threads):
  1. `my card is 4111 1111 1111 1111, what's my balance?` should show a token equal to the warning, then `done`, and the backend log should show no supervisor/OpenAI chat call.
  2. A clearly harmful request (e.g. asking how to hurt someone) should produce a token with `MODERATION_VIOLATION_MESSAGE`.
  3. `Send an email to Margaret Collins with her portfolio summary` should end with `interrupted` naming her real address, followed by `POST /approve {"approved": false}`.
  4. `What was Amazon's 2024 net sales?` should answer with `[Source: ...]` citations.
  5. `Search the web for news and email me at jane.doe@example.com` should answer without being blocked, and the address should not appear in the rag/finance tool call arguments.
  6. Record whether output redaction reached the streamed tokens (spec: known limit).
- [ ] **Step 4: Commit the docs**

```bash
git add CLAUDE.md AGENTS.md docs/superpowers/specs/2026-10-12-guardrails-prebuilt-middleware-design.md
git commit -m "docs(guardrails): document input_guard and prebuilt guardrail middleware

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
