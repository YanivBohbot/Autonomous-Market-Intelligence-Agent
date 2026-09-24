"""Pieces shared by every multi-agent specialist.

Each specialist file calls `create_agent(...)` itself (one file per agent);
this module only holds what would otherwise be copied 7 times: the model
factory and the middleware every specialist gets.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    PIIMiddleware,
    SummarizationMiddleware,
    ToolErrorMiddleware,
    dynamic_prompt,
)
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from app.agent.nodes.tool_utils import strip_image_content
from app.agent.prompts import with_today
from app.core.config import settings

MODEL_CALL_LIMIT = 10
SUMMARY_TRIGGER_TOKENS = 6000
SUMMARY_KEEP_MESSAGES = 10

ToolResult = ToolMessage | Command[Any]


def specialist_model() -> ChatOpenAI:
    return ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True)


@dynamic_prompt
def today_prompt(request: ModelRequest) -> str:
    """Static system_prompt + today's date, computed per call so a
    long-running process never serves a stale date."""
    return with_today(request.system_prompt or "")


def call_limit() -> ModelCallLimitMiddleware:
    """Cap model calls per specialist run so a looping agent can't run up
    OpenAI cost; "end" finishes the run instead of raising."""
    return ModelCallLimitMiddleware(run_limit=MODEL_CALL_LIMIT, exit_behavior="end")


def summarization() -> SummarizationMiddleware:
    """Once the conversation passes SUMMARY_TRIGGER_TOKENS, older messages are
    replaced by a summary (the last SUMMARY_KEEP_MESSAGES stay verbatim) so
    cost per turn stays bounded. The specialist shares `messages` with the
    supervisor, so this compacts the whole conversation — intended."""
    return SummarizationMiddleware(
        model=ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0),
        trigger=("tokens", SUMMARY_TRIGGER_TOKENS),
        keep=("messages", SUMMARY_KEEP_MESSAGES),
    )


def mask_credit_cards() -> PIIMiddleware:
    """No specialist needs a card number: mask it (last 4 digits kept)
    before it reaches OpenAI."""
    return PIIMiddleware("credit_card", strategy="mask")


def redact_emails() -> PIIMiddleware:
    """For specialists that send queries to third parties (Tavily, Yahoo,
    web pages) and never need an address. NOT for email/portfolio/memory/
    filesystem, which need real addresses to work."""
    return PIIMiddleware("email", strategy="redact")


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


def base_middleware() -> list[AgentMiddleware[Any, Any, Any]]:
    return [
        today_prompt,
        summarization(),
        mask_credit_cards(),
        call_limit(),
        tool_errors_to_messages,
    ]
