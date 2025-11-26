from fastapi import FastAPI
from app.agent.graph import agent_app
from app.api.models.Models import ChatRequest, ChatResponse, ApproveRequest

app = FastAPI(title="Market Intelligence Agent API")


# --- Fonction utilitaire de sécurité ---
def _get_safe_content(state: dict) -> str:
    """Extrait le texte du dernier message de façon robuste."""
    if "messages" not in state or not state["messages"]:
        return "Aucune réponse générée."

    last_msg = state["messages"][-1]
    content = last_msg.content

    # Cas 1 : Contenu vide (peut arriver après un tool call)
    if content is None:
        return ""

    # Cas 2 : Contenu sous forme de liste (format multimodal OpenAI parfois)
    if isinstance(content, list):
        text_parts = [
            c.get("text", "") for c in content if isinstance(c, dict) and "text" in c
        ]
        return " ".join(text_parts)

    # Cas 3 : Chaine standard
    return str(content)


# --- Endpoint 1 : Chat ---
@app.post("/chat", response_model=ChatResponse)
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
        # Affichage propre de l'action demandée
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


# --- Endpoint 2 : Approve ---
@app.post("/approve", response_model=ChatResponse)
async def approve_endpoint(request: ApproveRequest):
    config = {"configurable": {"thread_id": request.thread_id}}

    snapshot = agent_app.get_state(config)
    if not snapshot.next:
        # Si la mémoire est vide (redémarrage serveur), on le signale gentiment
        return {
            "response": "⚠️ Session expirée ou terminée. Veuillez relancer votre demande.",
            "status": "completed",
            "next_step": None,
        }

    if request.approved:
        print(f"✅ Action approuvée ({request.thread_id})")
        final_state = agent_app.invoke(None, config)
    else:
        print(f"❌ Action refusée ({request.thread_id})")
        return {
            "response": "Action annulée par l'utilisateur.",
            "status": "completed",
            "next_step": None,
        }

    # Vérification post-exécution
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
