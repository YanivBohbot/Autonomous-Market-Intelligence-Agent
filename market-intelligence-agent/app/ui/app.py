import os
import streamlit as st
import requests
import uuid

# Configuration de la page
st.set_page_config(page_title="Agent Autonome IA", page_icon="🕵️‍♂️")
st.title("🕵️‍♂️ Market Intelligence Agent")

# URL de l'API FastAPI (assure-toi que uvicorn tourne sur le port 8000)
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")

# --- Gestion de la Session ---
if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"web_session_{uuid.uuid4().hex[:8]}"

if "messages" not in st.session_state:
    st.session_state.messages = []

if "awaiting_approval" not in st.session_state:
    st.session_state.awaiting_approval = False

if "last_action" not in st.session_state:
    st.session_state.last_action = ""

# --- Affichage de l'historique ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Zone de Chat ---
# On désactive le chat si on attend une approbation
if prompt := st.chat_input(
    "Posez votre question...", disabled=st.session_state.awaiting_approval
):
    # 1. Afficher le message utilisateur
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Appeler l'API (/chat)
    with st.chat_message("assistant"):
        with st.spinner("L'agent réfléchit..."):
            try:
                response = requests.post(
                    f"{API_URL}/chat",
                    json={"query": prompt, "thread_id": st.session_state.thread_id},
                )
                data = response.json()

                # Analyse de la réponse
                if data["status"] == "interrupted":
                    st.session_state.awaiting_approval = True
                    st.session_state.last_action = data["response"]
                    st.warning(f"🛑 {data['response']}")  # Afficher la demande d'action
                    st.rerun()  # Recharger pour afficher les boutons
                else:
                    # Réponse finale
                    st.markdown(data["response"])
                    st.session_state.messages.append(
                        {"role": "assistant", "content": data["response"]}
                    )

            except Exception as e:
                st.error(f"Erreur de connexion API : {e}")

# --- Zone d'Approbation (Human-in-the-loop) ---
if st.session_state.awaiting_approval:
    st.info("🔒 L'agent demande une autorisation pour continuer.")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("✅ APPROUVER", type="primary", use_container_width=True):
            with st.spinner("Action en cours d'exécution..."):
                res = requests.post(
                    f"{API_URL}/approve",
                    json={"thread_id": st.session_state.thread_id, "approved": True},
                )
                data = res.json()

                if data["status"] == "interrupted":
                    # Nouvelle interruption (enchaînement d'actions)
                    st.session_state.last_action = data["response"]
                    st.rerun()
                else:
                    # C'est fini
                    st.session_state.awaiting_approval = False
                    st.session_state.messages.append(
                        {"role": "assistant", "content": data["response"]}
                    )
                    st.rerun()

    with col2:
        if st.button("❌ REFUSER", type="secondary", use_container_width=True):
            with st.spinner("Annulation..."):
                res = requests.post(
                    f"{API_URL}/approve",
                    json={"thread_id": st.session_state.thread_id, "approved": False},
                )
                st.session_state.awaiting_approval = False
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": "Action annulée par l'utilisateur.",
                    }
                )
                st.rerun()
