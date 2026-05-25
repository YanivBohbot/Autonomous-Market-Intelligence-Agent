"""AgentCore Runtime contract: GET /ping + POST /invocations on :8080.

Thin adapter over the existing LangGraph agent. Same behavior as /stream and
/approve, but exposed in the JSON shape AgentCore Runtime expects.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, Request
from langgraph.types import Command
from pydantic import BaseModel

from app.api.routers._helpers import get_action_description

logger = logging.getLogger(__name__)
router = APIRouter()


class InvocationRequest(BaseModel):
    """AgentCore invocation payload.

    `prompt` is a new turn from the caller. `resume` carries an HITL verdict
    ("approve" / "reject") when continuing an interrupted run; mutually
    exclusive with `prompt`.
    """

    prompt: Optional[str] = None
    resume: Optional[str] = None
    session_id: Optional[str] = None


class InvocationResponse(BaseModel):
    response: str
    status: str  # "completed" | "interrupted"
    next_step: Optional[str] = None
    pending_tool_calls: Optional[list[dict[str, Any]]] = None
    session_id: str


def _session_id(payload: InvocationRequest, header_value: Optional[str]) -> str:
    return payload.session_id or header_value or "default_thread"


def _safe_content(state: dict) -> str:
    if "messages" not in state or not state["messages"]:
        return ""
    content = state["messages"][-1].content
    if content is None:
        return ""
    if isinstance(content, list):
        return " ".join(
            c.get("text", "") for c in content if isinstance(c, dict) and "text" in c
        )
    return str(content)


def _pending_tool_calls(state: dict) -> Optional[list[dict[str, Any]]]:
    msgs = state.get("messages") or []
    if not msgs:
        return None
    last = msgs[-1]
    tool_calls = getattr(last, "tool_calls", None)
    if not tool_calls:
        return None
    return [{"name": tc["name"], "args": tc["args"]} for tc in tool_calls]


@router.get("/ping")
async def ping() -> dict[str, str]:
    """AgentCore Runtime health probe. Must return 200."""
    return {"status": "Healthy"}


@router.post("/invocations", response_model=InvocationResponse)
async def invocations(
    request: Request,
    payload: InvocationRequest,
    x_amzn_bedrock_agentcore_runtime_session_id: Optional[str] = Header(default=None),
) -> InvocationResponse:
    session_id = _session_id(payload, x_amzn_bedrock_agentcore_runtime_session_id)
    if payload.resume is None and payload.prompt is None:
        return InvocationResponse(
            response="prompt or resume is required",
            status="completed",
            session_id=session_id,
        )

    agent_app = request.app.state.agent_app
    config = {"configurable": {"thread_id": session_id}}

    if payload.resume is not None:
        decision = payload.resume.strip().lower()
        if decision not in {"approve", "reject"}:
            logger.warning("invalid resume value=%s; defaulting to reject", decision)
            decision = "reject"
        final_state = await agent_app.ainvoke(Command(resume=decision), config)
    else:
        final_state = await agent_app.ainvoke({"question": payload.prompt}, config)

    snapshot = await agent_app.aget_state(config)
    if snapshot.next:
        last = final_state["messages"][-1]
        return InvocationResponse(
            response=get_action_description(last),
            status="interrupted",
            next_step=str(snapshot.next),
            pending_tool_calls=_pending_tool_calls(final_state),
            session_id=session_id,
        )

    return InvocationResponse(
        response=_safe_content(final_state),
        status="completed",
        session_id=session_id,
    )
