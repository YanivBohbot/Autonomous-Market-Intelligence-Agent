from app.agent.graph import agent_app

# Configuration de session pour la mémoire
config = {"configurable": {"thread_id": "session_infinite_loop"}}


def run_full_interactive():
    # Question complexe qui demande 2 actions (CRM + Email)
    q = "Cherche 'Yaniv Bohbot' dans le CRM. Si tu trouves son email, envoie-lui un message de bienvenue."
    print(f"\n👤 User: {q}")

    # Initialisation avec la question
    current_input = {"question": q}

    # BOUCLE PRINCIPALE
    while True:
        try:
            # On lance le stream. Il s'arrêtera soit à la FIN, soit à une INTERRUPTION.
            # Si c'est une reprise (après interruption), current_input doit être None.
            for event in agent_app.stream(current_input, config, stream_mode="values"):
                if "messages" in event and event["messages"]:
                    last_msg = event["messages"][-1]

                    # Affichage intelligent
                    if hasattr(last_msg, "content") and last_msg.content:
                        print(f"   🧠 Agent: {last_msg.content[:100]}...")

                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        tool_name = last_msg.tool_calls[0]["name"]
                        tool_args = last_msg.tool_calls[0]["args"]
                        print(
                            f"   🔨 L'agent VEUT utiliser : {tool_name} avec {tool_args}"
                        )

            # Après la fin du stream, on regarde l'état pour voir pourquoi on s'est arrêté
            snapshot = agent_app.get_state(config)

            if snapshot.next:
                # CAS 1 : INTERRUPTION (L'agent veut faire une action)
                print(f"\n🛑 INTERRUPTION DÉTECTÉE ! Prochaine étape : {snapshot.next}")
                print("👉 L'agent demande la permission d'exécuter l'action ci-dessus.")

                user_approval = input("   Autoriser ? (oui/non/q pour quitter) > ")

                if user_approval.lower() in ["q", "quit", "exit"]:
                    break

                if user_approval.lower() == "oui":
                    print("✅ Action approuvée. L'agent continue...")
                    current_input = (
                        None  # Important : None signale "Continue là où tu t'es arrêté"
                    )
                else:
                    print("❌ Action refusée. On arrête l'agent ici.")
                    break
            else:
                # CAS 2 : FIN DU TRAITEMENT (Plus rien à faire)
                print("\n🏁 Tâche terminée !")
                break

        except Exception as e:
            print(f"🔥 Erreur critique : {e}")
            break


if __name__ == "__main__":
    run_full_interactive()
