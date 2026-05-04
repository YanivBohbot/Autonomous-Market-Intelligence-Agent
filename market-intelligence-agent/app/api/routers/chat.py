import logging
from fastapi import APIRouter
from app.agent.graph import agent_app
from app.api.models.models import ChatRequest, ChatResponse, ApproveRequest

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_safe_content(state: dict) -> str:
    if "messages" not in state or not state["messages"]:
        return "Aucune réponse générée."
    last_msg = state["messages"][-1]
    content = last_msg.content
    if content is None:
        return ""
    if isinstance(content, list):
        return " ".join(
            c.get("text", "") for c in content if isinstance(c, dict) and "text" in c
        )
    return str(content)


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    snapshot = agent_app.get_state(config)
    if snapshot.next:
        return {
            "response": "⚠️ Une action est en attente. Utilisez /approve.",
            "status": "interrupted",
            "next_step": str(snapshot.next),
        }
    inputs = {"question": request.query}
    final_state = agent_app.invoke(inputs, config)
    snapshot = agent_app.get_state(config)
    if snapshot.next:
        last_msg = final_state["messages"][-1]
        action_desc = last_msg.content
        if not action_desc and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            tc = last_msg.tool_calls[0]
            action_desc = f"Exécuter : {tc['name']} ({tc['args']})"
        return {
            "response": f"⏸️ ACTION REQUISE : {action_desc}",
            "status": "interrupted",
            "next_step": str(snapshot.next),
        }
    return {
        "response": _get_safe_content(final_state),
        "status": "completed",
        "next_step": None,
    }


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
    if request.approved:
        logger.info("Action approved for thread %s", request.thread_id)
        final_state = agent_app.invoke(None, config)
    else:
        logger.info("Action refused for thread %s", request.thread_id)
        return {
            "response": "Action annulée par l'utilisateur.",
            "status": "completed",
            "next_step": None,
        }
    snapshot = agent_app.get_state(config)
    if snapshot.next:
        last_msg = final_state["messages"][-1]
        action_desc = last_msg.content
        if not action_desc and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            tc = last_msg.tool_calls[0]
            action_desc = f"Exécuter : {tc['name']} ({tc['args']})"
        return {
            "response": f"⏸️ NOUVELLE ACTION REQUISE : {action_desc}",
            "status": "interrupted",
            "next_step": str(snapshot.next),
        }
    return {
        "response": _get_safe_content(final_state),
        "status": "completed",
        "next_step": None,
    }
