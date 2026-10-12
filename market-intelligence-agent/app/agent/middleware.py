"""Pieces shared by every multi-agent specialist.

Each specialist file calls `create_agent(...)` itself (one file per agent);
this module only holds what would otherwise be copied 7 times: the model
factory and the middleware every specialist gets.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from langchain.agents.middleware import (
    AgentMiddleware,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRequest,
    ModelRetryMiddleware,
    PIIMiddleware,
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
    ToolRetryMiddleware,
    dynamic_prompt,
)
from langchain.agents.middleware.context_editing import DEFAULT_TOOL_PLACEHOLDER, TokenCounter
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langchain_openai.middleware import OpenAIModerationMiddleware
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from app.agent.guardrails.detection import redact_emails_in
from app.agent.prompts import with_today
from app.agent.tools import is_read_only
from app.agent.prompts.ingested_documents_prompt import (
    INGESTED_DOCUMENTS_PLACEHOLDER,
    ingested_documents_list,
)
from app.core.config import settings

MODEL_CALL_LIMIT = 10
SUMMARY_TRIGGER_TOKENS = 6000
SUMMARY_KEEP_MESSAGES = 50
# Past this many (approximate) tokens, tool results from turns older than
# the last CONTEXT_KEEP_TURNS are cleared from what the model sees.
CONTEXT_EDIT_TRIGGER_TOKENS = 4000
CONTEXT_KEEP_TURNS = 2

ToolResult = ToolMessage | Command[Any]


def strip_image_content(content):
    """Drop image parts from an MCP tool result before it re-enters the
    conversation: OpenAI rejects image content on tool-role messages (only
    'user' may carry images), and the frontend already gets the real PNG via
    the dedicated screenshot SSE event, so the LLM never needs the raw bytes.
    """
    if not isinstance(content, list):
        return content
    return [
        part for part in content
        if not (isinstance(part, dict) and part.get("type") in ("image", "image_url"))
    ]


def specialist_model() -> ChatOpenAI:
    return ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True)


@dynamic_prompt
def today_prompt(request: ModelRequest) -> str:
    """Static system_prompt + today's date, computed per call so a
    long-running process never serves a stale date."""
    return with_today(request.system_prompt or "")


@dynamic_prompt
def client_context_prompt(request: ModelRequest) -> str:
    """Appends the active client's profile blurb (set by
    load_client_context, see app/agent/orchestration/graph.py) to the system
    prompt when this thread is scoped to a client; leaves the prompt
    untouched on every other thread."""
    client_context = request.state.get("client_context")
    base = request.system_prompt or ""
    if not client_context:
        return base
    return f"{base}\n\n{client_context}"


@dynamic_prompt
def fresh_documents_prompt(request: ModelRequest) -> str:
    """Substitute the RAG manifest's current contents into
    INGESTED_DOCUMENTS_PLACEHOLDER at call time, not once at prompt-string-
    definition time -- a PDF uploaded via /data/import/pdf while the server
    is already running must be visible to rag_agent immediately, not only
    after a restart."""
    return (request.system_prompt or "").replace(
        INGESTED_DOCUMENTS_PLACEHOLDER, ingested_documents_list()
    )


def call_limit() -> ModelCallLimitMiddleware:
    """Cap model calls per specialist run so a looping agent can't run up
    OpenAI cost; "end" finishes the run instead of raising."""
    return ModelCallLimitMiddleware(run_limit=MODEL_CALL_LIMIT, exit_behavior="end")


def model_retry(on_failure: Literal["continue", "error"] = "continue") -> ModelRetryMiddleware:
    """A transient OpenAI error (rate limit, timeout, 5xx) during the model
    call itself isn't a tool error -- ToolErrorMiddleware never sees it, and
    nothing else in this stack retries it, so the whole run used to fail
    outright. Defaults (2 retries, exponential backoff with jitter) retry
    only the model call, before any tool executes -- safe even for
    specialists with side-effect tools. The supervisor's router passes
    on_failure="error": with "continue", exhausted retries return an
    AIMessage with no structured_response, which create_agent sends straight
    back to the model -- an outage became a near-endless loop."""
    return ModelRetryMiddleware(on_failure=on_failure)


def model_fallback() -> ModelFallbackMiddleware | None:
    """Switches to Anthropic if OpenAI is still down after model_retry()'s
    own retries are exhausted (first-in-list wraps outermost for
    wrap_model_call middleware, so this must be listed before model_retry()
    in base_middleware() -- outer catches the final failure and re-invokes
    the inner retry layer against the fallback model). Opt-in: `None` (and
    therefore omitted from the middleware list) when no ANTHROPIC_API_KEY is
    configured, since this is an extra safety net, not a requirement."""
    if not settings.ANTHROPIC_API_KEY:
        return None
    return ModelFallbackMiddleware("anthropic:claude-sonnet-5-5")


@dataclass
class ClearOldTurnToolResults:
    """ContextEdit for the official ContextEditingMiddleware: replaces tool
    results from turns older than the last `keep_turns` (a turn starts at a
    HumanMessage) with a placeholder. Unlike ClearToolUsesEdit, which keeps
    the last N tool *messages*, this never touches the current turn (a RAG
    comparison can make 3+ searches) and keeps the previous turns' results:
    specialists don't restate card figures in prose, so "email her that
    summary" right after a portfolio card needs that ToolMessage. Tool-call
    arguments are kept, so a follow-up still knows which ticker was asked."""

    trigger: int = CONTEXT_EDIT_TRIGGER_TOKENS
    keep_turns: int = CONTEXT_KEEP_TURNS
    placeholder: str = DEFAULT_TOOL_PLACEHOLDER

    def apply(self, messages: list[AnyMessage], *, count_tokens: TokenCounter) -> None:
        if count_tokens(messages) <= self.trigger:
            return
        turn_starts = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
        if len(turn_starts) <= self.keep_turns:
            return
        boundary = turn_starts[-1 - self.keep_turns]
        for i, message in enumerate(messages[:boundary]):
            if isinstance(message, ToolMessage) and message.content != self.placeholder:
                messages[i] = message.model_copy(update={"content": self.placeholder, "artifact": None})


def context_editing() -> ContextEditingMiddleware:
    """Request-only: ContextEditingMiddleware edits a deep copy of the
    messages it sends to the model and never writes back to state, so the
    checkpointed conversation -- and every Market Desk card rendered from
    its ToolMessages -- stays intact. This, not summarization(), is what
    bounds cost per turn: before it, a 6-question thread sent ~23k tokens of
    stale tool output (price tables, ticker JSON) on every model call."""
    return ContextEditingMiddleware(edits=[ClearOldTurnToolResults()])


def summarization() -> SummarizationMiddleware:
    """Replaces older messages with a summary, but only once there are more
    than SUMMARY_KEEP_MESSAGES messages -- the trigger is in tokens, yet
    `keep` is in messages, so below 50 messages there is nothing to cut.
    Deliberately left that way: unlike context_editing(), summarizing
    rewrites the shared, checkpointed `messages` (RemoveMessage), which
    would drop old cards from Market Desk and from reloaded history."""
    return SummarizationMiddleware(
        # The summary is internal: Market Desk (ag-ui-langgraph) must not
        # stream it into the chat as if it were the answer.
        model=ChatOpenAI(
            model=settings.OPENAI_MODEL,
            temperature=0,
            metadata={"emit-messages": False, "emit-tool-calls": False},
        ),
        trigger=("tokens", SUMMARY_TRIGGER_TOKENS),
        keep=("messages", SUMMARY_KEEP_MESSAGES),
    )


MODERATION_VIOLATION_MESSAGE = (
    "This request was flagged by our content-safety check, so I can't help "
    "with it. Please rephrase your question."
)


def mask_credit_cards() -> PIIMiddleware:
    """No specialist needs a card number: mask it (last 4 digits kept) in
    user input, in tool results and in the model's own answer. Defense in
    depth behind block_credit_cards, the supervisor router agent's
    @before_agent guard, which blocks cards in the user's message before any
    routing model call."""
    return PIIMiddleware(
        "credit_card",
        strategy="mask",
        apply_to_input=True,
        apply_to_output=True,
        apply_to_tool_results=True,
    )


class RedactEmailsForModel(AgentMiddleware):
    """For specialists that send queries to third parties (Tavily, Yahoo,
    web pages) and never need an address: the model gets a copy of the
    conversation with addresses replaced by [REDACTED_EMAIL], so it can't
    put one in a tool call. Unlike PIIMiddleware(apply_to_input=True), which
    writes the redacted messages back to the shared `messages` channel, the
    stored conversation keeps the real address -- a later email_agent hop
    in the same thread still needs the recipient. Detection uses LangChain's
    own detect_email (app/agent/guardrails/detection.py)."""

    @staticmethod
    def _redact(message):
        content = message.content
        if isinstance(content, str):
            redacted = redact_emails_in(content)
        elif isinstance(content, list):
            redacted = [
                {**block, "text": redact_emails_in(str(block.get("text", "")))}
                if isinstance(block, dict) and block.get("type") == "text"
                else block
                for block in content
            ]
        else:
            return message
        return message if redacted == content else message.model_copy(update={"content": redacted})

    def _request(self, request: ModelRequest) -> ModelRequest:
        return request.override(messages=[self._redact(m) for m in request.messages])

    def wrap_model_call(self, request, handler):
        return handler(self._request(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._request(request))


def redact_emails() -> RedactEmailsForModel:
    """NOT for email/portfolio/memory/filesystem, which need real addresses."""
    return RedactEmailsForModel()


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
    when the specialist has no read-only tool (`tools=None` would mean
    "retry everything", so an empty filter is never passed)."""
    names: list[BaseTool | str] = [t.name for t in tools if is_read_only(t.name)]
    if not names:
        return None
    return ToolRetryMiddleware(max_retries=2, tools=names, on_failure="error")


def tool_call_limit(tool_name: str, run_limit: int) -> ToolCallLimitMiddleware:
    """Caps a costly/loop-prone tool per run; "continue" lets the model
    answer with what it already has instead of failing the run."""
    return ToolCallLimitMiddleware(tool_name=tool_name, run_limit=run_limit, exit_behavior="continue")


def _tool_error_content(exc: Exception, request: ToolCallRequest) -> str:
    """Every tool failure goes back to the model as an error ToolMessage it
    can read and recover from, instead of aborting the run (the
    thread-poisoning fix the single-agent graph gets from
    ToolNode(handle_tool_errors=True))."""
    return f"Tool error ({type(exc).__name__}): {exc}"


# Official middleware; on_error serves both the sync and the async path.
tool_errors_to_messages = ToolErrorMiddleware(on_error=_tool_error_content)


# Class-based: the @wrap_tool_call decorator only types sync functions, and the
# MCP tools are async-only; AgentMiddleware types wrap_tool_call and
# awrap_tool_call.
class StripToolImages(AgentMiddleware):
    """OpenAI rejects image parts in tool messages; drop them (browser
    screenshots) and keep the text."""

    @staticmethod
    def _strip(result: ToolResult) -> ToolResult:
        if isinstance(result, ToolMessage):
            result.content = strip_image_content(result.content)
        return result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolResult],
    ) -> ToolResult:
        return self._strip(handler(request))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolResult]],
    ) -> ToolResult:
        return self._strip(await handler(request))


strip_tool_images = StripToolImages()


def base_middleware(tools: Sequence[BaseTool]) -> list[AgentMiddleware[Any, Any, Any]]:
    """Middleware every specialist gets. `tools` is the specialist's own tool
    list, used to scope tool_retry() to its read-only tools."""
    middleware: list[AgentMiddleware[Any, Any, Any]] = [mask_credit_cards()]
    moderation_mw = moderation()
    if moderation_mw is not None:
        # After the card mask, so the moderation API never sees a card number.
        middleware.append(moderation_mw)
    middleware += [today_prompt, context_editing(), summarization(), call_limit()]
    fallback = model_fallback()
    if fallback is not None:
        # Must precede model_retry() -- see model_fallback()'s docstring.
        middleware.append(fallback)
    middleware.append(model_retry())
    middleware.append(tool_errors_to_messages)
    retry = tool_retry(tools)
    if retry is not None:
        # Listed after ToolErrorMiddleware = wrapped inside it: retries run
        # first, and only the final failure becomes an error ToolMessage.
        middleware.append(retry)
    return middleware
