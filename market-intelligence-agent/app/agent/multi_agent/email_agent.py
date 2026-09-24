from collections.abc import Awaitable, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, HumanInTheLoopMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from app.agent.multi_agent.common import ToolResult, base_middleware, specialist_model
from app.agent.prompts.specialist_agent_prompts import EMAIL_SYSTEM_PROMPT
from app.agent.tools import crm_tool, send_email_tool
from app.agent.tools.concentration import parse_tool_payload

_TOOLS = [send_email_tool]


async def _is_client_email(address: str) -> bool:
    """True when `address` belongs to a client in the wealth DB (read through
    the same read_query MCP tool the agent uses, so it works locally and over
    the AgentCore Gateway)."""
    escaped = address.strip().lower().replace("'", "''")
    rows = parse_tool_payload(await crm_tool.ainvoke(
        {"query": f"SELECT 1 AS n FROM clients WHERE lower(email) = lower('{escaped}')"}
    ))
    return bool(rows)


class EmailRecipientGuard(AgentMiddleware):
    """send_email may only target a client's address from the database.

    Runs at tool execution, i.e. after the HITL approval: even a mistaken
    approval of an unknown address sends nothing. Fails closed on the sync
    path, since the DB lookup is async-only.
    """

    def __init__(self, is_known_recipient: Callable[[str], Awaitable[bool]]):
        super().__init__()
        self._is_known_recipient = is_known_recipient

    @staticmethod
    def _blocked(request: ToolCallRequest, reason: str) -> ToolMessage:
        return ToolMessage(
            content=f"Email blocked: {reason}",
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
            status="error",
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolResult],
    ) -> ToolResult:
        if request.tool_call["name"] != "send_email":
            return handler(request)
        return self._blocked(request, "recipient check requires async execution.")

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolResult]],
    ) -> ToolResult:
        if request.tool_call["name"] != "send_email":
            return await handler(request)
        recipient = str(request.tool_call["args"].get("recipient", ""))
        if not await self._is_known_recipient(recipient):
            return self._blocked(request, f"{recipient!r} is not a client address in the database.")
        return await handler(request)


def build_email_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=EMAIL_SYSTEM_PROMPT,
        middleware=[
            *base_middleware(),
            HumanInTheLoopMiddleware(interrupt_on={"send_email": True}),
            EmailRecipientGuard(is_known_recipient=_is_client_email),
        ],
        name="email_agent",
    )
