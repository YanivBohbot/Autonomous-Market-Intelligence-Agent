"""Pieces shared by every multi-agent specialist.

Each specialist file calls `create_agent(...)` itself (one file per agent);
this module only holds what would otherwise be copied 7 times: the model
factory and the middleware every specialist gets.
"""

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRequest,
    dynamic_prompt,
    wrap_tool_call,
)
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI

from app.agent.nodes.tool_utils import strip_image_content
from app.agent.prompts import with_today
from app.core.config import settings

MODEL_CALL_LIMIT = 10


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


@wrap_tool_call
async def tool_errors_to_messages(request, handler):
    """A failing tool becomes an error ToolMessage the model can read and
    recover from, instead of aborting the run (the thread-poisoning fix the
    single-agent graph gets from ToolNode(handle_tool_errors=True)).
    Async: the MCP tools are async-only."""
    try:
        return await handler(request)
    except Exception as exc:  # noqa: BLE001 — every tool failure goes back to the model
        return ToolMessage(
            content=f"Tool error: {exc}",
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
            status="error",
        )


@wrap_tool_call
async def strip_tool_images(request, handler):
    """OpenAI rejects image parts in tool messages; drop them (browser
    screenshots) and keep the text."""
    result = await handler(request)
    if isinstance(result, ToolMessage):
        result.content = strip_image_content(result.content)
    return result


def base_middleware() -> list:
    return [today_prompt, call_limit(), tool_errors_to_messages]
