import json
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

# --- Voice mode (LiveKit-backed) ---
from app.ui.voice_panel import render_voice_panel

with st.sidebar:
    st.markdown("### 🎤 Voice mode")
    voice_on = st.toggle(
        "Enable voice",
        value=False,
        help="Speak to the agent via your mic. Requires the LiveKit worker running.",
    )
    if voice_on:
        st.caption(
            "Click **Connect** in the panel below, allow mic access, then speak. "
            "Voice runs on a separate `thread_id` from the text chat."
        )
        render_voice_panel(height=280)

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

    # 2. Appeler l'API (/stream) en SSE
    with st.chat_message("assistant"):
        placeholder = st.empty()
        accumulated = ""
        try:
            with requests.post(
                f"{API_URL}/stream",
                json={"query": prompt, "thread_id": st.session_state.thread_id},
                stream=True,
                timeout=120,
            ) as response:
                response.raise_for_status()
                current_event = None
                for raw_line in response.iter_lines(decode_unicode=True):
                    if raw_line is None:
                        continue
                    if raw_line.startswith("event: "):
                        current_event = raw_line[len("event: "):].strip()
                    elif raw_line.startswith("data: "):
                        payload = json.loads(raw_line[len("data: "):])
                        if current_event == "token":
                            accumulated += payload.get("token", "")
                            placeholder.markdown(accumulated + "▌")
                        elif current_event == "interrupted":
                            st.session_state.awaiting_approval = True
                            st.session_state.last_action = payload.get("action", "")
                            placeholder.warning(f"🛑 {st.session_state.last_action}")
                            st.rerun()
                        elif current_event == "done":
                            placeholder.markdown(accumulated)
                            st.session_state.messages.append(
                                {"role": "assistant", "content": accumulated}
                            )
                        elif current_event == "error":
                            st.error(f"❌ {payload.get('error', 'Erreur inconnue')}")

        except requests.exceptions.ConnectionError as e:
            st.error(f"❌ Impossible de se connecter à l'API ({API_URL}): {e}")
        except requests.exceptions.HTTPError as e:
            st.error(f"❌ Erreur API (HTTP {e.response.status_code}): {e.response.text}")
        except Exception as e:
            st.error(f"❌ Erreur inattendue: {type(e).__name__}: {e}")

# --- Zone d'Approbation (Human-in-the-loop) ---
if st.session_state.awaiting_approval:
    st.info("🔒 L'agent demande une autorisation pour continuer.")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("✅ APPROUVER", type="primary", use_container_width=True):
            with st.spinner("Action en cours d'exécution..."):
                try:
                    res = requests.post(
                        f"{API_URL}/approve",
                        json={"thread_id": st.session_state.thread_id, "approved": True},
                        timeout=120,
                    )
                    res.raise_for_status()
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

                except requests.exceptions.ConnectionError as e:
                    st.error(f"❌ Impossible de se connecter à l'API ({API_URL}): {e}")
                except requests.exceptions.HTTPError as e:
                    st.error(f"❌ Erreur API (HTTP {e.response.status_code}): {e.response.text}")
                except requests.exceptions.JSONDecodeError as e:
                    st.error(f"❌ La réponse API n'est pas du JSON valide: {e}")
                    st.text(f"Réponse brute: {res.text[:500] if res else 'Aucune réponse'}")
                except Exception as e:
                    st.error(f"❌ Erreur inattendue: {type(e).__name__}: {e}")

    with col2:
        if st.button("❌ REFUSER", type="secondary", use_container_width=True):
            with st.spinner("Annulation..."):
                try:
                    res = requests.post(
                        f"{API_URL}/approve",
                        json={"thread_id": st.session_state.thread_id, "approved": False},
                        timeout=120,
                    )
                    res.raise_for_status()
                    st.session_state.awaiting_approval = False
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": res.json().get("response", "Action annulée par l'utilisateur."),
                        }
                    )
                    st.rerun()
                except requests.exceptions.ConnectionError as e:
                    st.error(f"❌ Impossible de se connecter à l'API ({API_URL}): {e}")
                except requests.exceptions.HTTPError as e:
                    st.error(f"❌ Erreur API (HTTP {e.response.status_code}): {e.response.text}")
                except requests.exceptions.JSONDecodeError as e:
                    st.error(f"❌ La réponse API n'est pas du JSON valide: {e}")
                    st.text(f"Réponse brute: {res.text[:500] if res else 'Aucune réponse'}")
                except Exception as e:
                    st.error(f"❌ Erreur inattendue: {type(e).__name__}: {e}")
