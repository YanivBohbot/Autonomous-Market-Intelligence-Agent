import logging

from fastapi import APIRouter, Request
from langgraph.types import Command

from app.api.models.models import ApproveRequest, ChatResponse
from app.api.routers._helpers import (
    boolean_decisions,
    get_action_description,
    pending_interrupt_from_snapshot,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _safe_content(state: dict) -> str:
    if "messages" not in state or not state["messages"]:
        return "Aucune réponse générée."
    content = state["messages"][-1].content
    if content is None:
        return ""
    if isinstance(content, list):
        return " ".join(
            c.get("text", "") for c in content if isinstance(c, dict) and "text" in c
        )
    return str(content)


@router.post("/approve", response_model=ChatResponse)
async def approve_endpoint(request: Request, payload: ApproveRequest):
    agent_app = request.app.state.agent_app
    config = {
        "configurable": {
            "thread_id": payload.thread_id,
            "actor_id": "mia-agent",
        }
    }
    snapshot = await agent_app.aget_state(config, subgraphs=True)
    pending = pending_interrupt_from_snapshot(snapshot)
    if pending is None:
        return {
            "response": "⚠️ Session expirée ou terminée. Veuillez relancer votre demande.",
            "status": "completed",
            "next_step": None,
        }

    decision_name = "approve" if payload.approved else "reject"
    logger.info("HITL decision=%s for thread %s", decision_name, payload.thread_id)
    final_state = await agent_app.ainvoke(
        Command(resume=boolean_decisions(pending, payload.approved)),
        config,
    )

    snapshot = await agent_app.aget_state(config, subgraphs=True)
    next_pending = pending_interrupt_from_snapshot(snapshot)
    if next_pending is not None:
        requests = next_pending.value.get("action_requests")
        action_request = requests[0] if isinstance(requests, list) and requests else None
        return {
            "response": (
                "⏸️ NOUVELLE ACTION REQUISE : "
                f"{get_action_description(next_pending.last_message, action_request)}"
            ),
            "status": "interrupted",
            "next_step": str(snapshot.next),
        }
    return {
        "response": _safe_content(final_state),
        "status": "completed",
        "next_step": None,
    }
