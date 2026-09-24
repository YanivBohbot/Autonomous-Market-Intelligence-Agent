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


# Class-based middleware rather than @wrap_tool_call: in langchain 1.2.x the
# decorator's type only describes sync functions, and the MCP tools are
# async-only, so an `async def` under @wrap_tool_call runs fine but fails type
# checking. AgentMiddleware types both hooks (wrap_tool_call / awrap_tool_call).


class ToolErrorsToMessages(AgentMiddleware):
    """A failing tool becomes an error ToolMessage the model can read and
    recover from, instead of aborting the run (the thread-poisoning fix the
    single-agent graph gets from ToolNode(handle_tool_errors=True))."""

    @staticmethod
    def _error_message(request: ToolCallRequest, exc: Exception) -> ToolMessage:
        return ToolMessage(
            content=f"Tool error: {exc}",
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
            status="error",
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolResult],
    ) -> ToolResult:
        try:
            return handler(request)
        except Exception as exc:  # noqa: BLE001 — every tool failure goes back to the model
            return self._error_message(request, exc)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolResult]],
    ) -> ToolResult:
        try:
            return await handler(request)
        except Exception as exc:  # noqa: BLE001
            return self._error_message(request, exc)


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


tool_errors_to_messages = ToolErrorsToMessages()
strip_tool_images = StripToolImages()


def base_middleware() -> list[AgentMiddleware[Any, Any, Any]]:
    return [today_prompt, call_limit(), tool_errors_to_messages]
