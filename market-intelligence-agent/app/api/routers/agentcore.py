"""AgentCore Runtime contract: GET /ping + POST /invocations on :8080.

Thin adapter over the existing LangGraph agent. Same behavior as /stream and
/approve, but exposed in the JSON shape AgentCore Runtime expects.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel

from app.api.routers._helpers import (
    PendingGraphInterrupt,
    boolean_decisions,
    get_action_description,
    pending_interrupt_from_snapshot,
)
from app.agent.turn_coordinator import TurnLease

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


def _pending_tool_calls(
    pending: PendingGraphInterrupt,
) -> Optional[list[dict[str, Any]]]:
    action_requests = pending.value.get("action_requests")
    if not isinstance(action_requests, list) or not action_requests:
        return None
    return [
        {"name": action.get("name"), "args": action.get("args", {})}
        for action in action_requests
        if isinstance(action, dict)
    ] or None


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
    # AgentCoreMemorySaver requires both thread_id and actor_id. We use a
    # fixed actor_id for v1 — every session shares the same actor namespace.
    # A multi-tenant version would derive actor_id from the authenticated
    # user once Cognito sign-in is wired into the runtime contract.
    config = {
        "configurable": {
            "thread_id": session_id,
            "actor_id": "mia-agent",
        }
    }
    coordinator = request.app.state.turn_coordinator
    lease: TurnLease | None = None
    if payload.resume is None:
        lease = await coordinator.try_acquire(
            session_id, f"text:agentcore:{session_id}"
        )
        if lease is None:
            owner = await coordinator.owner(session_id)
            detail = (
                "Voice mode is active for this thread."
                if owner and owner.startswith("voice:")
                else "Another turn is active for this thread."
            )
            raise HTTPException(status_code=409, detail=detail)

    try:
        if payload.resume is not None:
            decision = payload.resume.strip().lower()
            if decision not in {"approve", "reject"}:
                logger.warning("invalid resume value=%s; defaulting to reject", decision)
                decision = "reject"
            snapshot = await agent_app.aget_state(config, subgraphs=True)
            pending = pending_interrupt_from_snapshot(snapshot)
            if pending is None:
                return InvocationResponse(
                    response="Session expired or completed. Start a new request.",
                    status="completed",
                    session_id=session_id,
                )
            final_state = await agent_app.ainvoke(
                Command(resume=boolean_decisions(pending, decision == "approve")),
                config,
            )
        else:
            final_state = await agent_app.ainvoke({"question": payload.prompt}, config)

        snapshot = await agent_app.aget_state(config, subgraphs=True)
        pending = pending_interrupt_from_snapshot(snapshot)
        if pending is not None:
            action_requests = pending.value.get("action_requests")
            action_request = (
                action_requests[0]
                if isinstance(action_requests, list) and action_requests
                else None
            )
            return InvocationResponse(
                response=get_action_description(pending.last_message, action_request),
                status="interrupted",
                next_step=str(snapshot.next),
                pending_tool_calls=_pending_tool_calls(pending),
                session_id=session_id,
            )

        return InvocationResponse(
            response=_safe_content(final_state),
            status="completed",
            session_id=session_id,
        )
    finally:
        if lease is not None:
            await coordinator.release(lease)
