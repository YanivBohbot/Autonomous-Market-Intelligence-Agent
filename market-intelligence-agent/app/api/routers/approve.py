import asyncio
import logging
from fastapi import APIRouter
from langgraph.types import Command
from app.agent.graph import agent_app
from app.api.models.models import ChatResponse, ApproveRequest
from app.api.routers._helpers import get_action_description

logger = logging.getLogger(__name__)
router = APIRouter()


def _safe_content(state: dict) -> str:
    if "messages" not in state or not state["messages"]:
        return "Aucune réponse générée."
    content = state["messages"][-1].content
    if content is None:
        return ""
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict) and "text" in c)
    return str(content)


@router.post("/approve", response_model=ChatResponse)
async def approve_endpoint(request: ApproveRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    snapshot = agent_app.get_state(config)
    if not snapshot.next:
        return {
            "response": "⚠️ Session expirée ou terminée. Veuillez relancer votre demande.",
            "status": "completed",
            "next_step": None,
        }

    decision = "approve" if request.approved else "reject"
    logger.info("HITL decision=%s for thread %s", decision, request.thread_id)
    final_state = await asyncio.to_thread(
        agent_app.invoke, Command(resume=decision), config
    )

    snapshot = agent_app.get_state(config)
    if snapshot.next:
        last = final_state["messages"][-1]
        return {
            "response": f"⏸️ NOUVELLE ACTION REQUISE : {get_action_description(last)}",
            "status": "interrupted",
            "next_step": str(snapshot.next),
        }
    return {
        "response": _safe_content(final_state),
        "status": "completed",
        "next_step": None,
    }
