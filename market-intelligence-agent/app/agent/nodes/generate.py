import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from app.core.config import settings
from app.agent.state import AgentState
from app.agent.tools import TOOLS

logger = logging.getLogger(__name__)

_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True)
_llm_with_tools = _llm.bind_tools(TOOLS)


def generate_answer(state: AgentState) -> dict:
    logger.info("GENERATE: Building response")
    question = state["question"]
    documents = state["documents"]
    messages = state.get("messages", [])
    context = "\n\n".join(documents)

    if messages:
        last_message = messages[-1]
        if isinstance(last_message, ToolMessage) and "Error" in str(last_message.content):
            logger.warning("GENERATE: Tool error detected — generating explanation")
            llm_error = _llm
            return {
                "messages": [
                    llm_error.invoke([
                        SystemMessage(content="L'outil a retourné une erreur technique. Analyse l'erreur, explique-la simplement à l'utilisateur et propose une solution si possible."),
                        HumanMessage(content=f"Erreur technique : {last_message.content}"),
                    ])
                ]
            }

    system_prompt = """Tu es un assistant expert en analyse de données et en communication.

🛠️ TES OUTILS :
1. `crm_query` : Pour interroger la base de données clients.
2. `send_email` : Pour envoyer des rapports ou des messages.

🗄️ SCHÉMA DE LA BASE DE DONNÉES (Table: 'customers') :
Tu as accès à une table SQL SQLite nommée `customers`. Voici les colonnes disponibles :
- `id` (INTEGER) : Identifiant unique.
- `name` (TEXT) : Nom complet du client.
- `email` (TEXT) : Adresse email.
- `status` (TEXT) : Statut du client (ex: 'VIP', 'Standard', 'Premium').
- `total_spend` (REAL) : Montant total dépensé.

🧠 TES INSTRUCTIONS :
- Tu es autonome pour écrire des requêtes SQL `SELECT` valides en fonction de la demande de l'utilisateur.
- Tu peux filtrer (WHERE), trier (ORDER BY), limiter (LIMIT) ou agréger (COUNT, SUM).
- Exemple générique : Si on cherche un client par nom, utilise `LIKE '%Nom%'`.
- Si on demande une action (email), vérifie d'abord si tu as toutes les infos (email destinataire) via le CRM.

Utilise le contexte fourni (RAG ou Historique) pour répondre précisément.
"""

    msgs = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Question Utilisateur: {question}\n\nContexte Documentaire (RAG):\n{context}"),
    ]
    if messages:
        msgs.extend(messages)

    response = _llm_with_tools.invoke(msgs)
    return {"messages": [response]}
