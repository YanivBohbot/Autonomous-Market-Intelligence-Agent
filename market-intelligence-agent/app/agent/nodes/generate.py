from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from app.core.config import settings
from app.agent.state import AgentState

# Imports des outils
from app.agent.tools.emails import send_email_tool
from app.agent.tools.mcp_clients.mcp_client import crm_tool


def generate_answer(state: AgentState):
    print("📝 [NODE] GENERATE: Analyse de la situation...")

    question = state["question"]
    documents = state["documents"]
    messages = state.get("messages", [])
    context = "\n\n".join(documents)

    # --- 1. COUPE-CIRCUIT (Gestion des erreurs d'outils) ---
    if len(messages) > 0:
        last_message = messages[-1]
        # Si le dernier message est une erreur d'outil, on arrête les frais
        if isinstance(last_message, ToolMessage) and "Error" in str(
            last_message.content
        ):
            print("🛑 [SAFETY] Erreur outil détectée.")
            llm_error = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
            msg = [
                SystemMessage(
                    content="L'outil a retourné une erreur technique. Analyse l'erreur, explique-la simplement à l'utilisateur et propose une solution si possible."
                ),
                HumanMessage(content=f"Erreur technique : {last_message.content}"),
            ]
            return {"messages": [llm_error.invoke(msg)]}

    # --- 2. FLUX NORMAL ---
    llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)

    # On donne les outils au LLM
    llm_with_tools = llm.bind_tools([send_email_tool, crm_tool])

    # --- 3. PROMPT GÉNÉRIQUE (DATA ANALYST) ---
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
        HumanMessage(
            content=f"Question Utilisateur: {question}\n\nContexte Documentaire (RAG):\n{context}"
        ),
    ]

    # Injection de l'historique pour la mémoire de travail
    if len(messages) > 0:
        msgs.extend(messages)

    response = llm_with_tools.invoke(msgs)
    return {"messages": [response]}
