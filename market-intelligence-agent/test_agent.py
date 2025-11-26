from app.agent.graph import agent_app
from app.agent.graph import agent_app


def run_test():
    # Test 1 : Info Interne (Amazon)
    q1 = "Quel est le revenu net d'Amazon en 2024 ?"
    print(f"\n--- TEST 1: {q1} ---")
    inputs = {"question": q1}
    res = agent_app.invoke(inputs)
    print("🤖 REPONSE:", res["messages"][-1].content)

    # Test 2 : Info Externe (Tesla)
    q2 = "Quel est le prix de l'action Tesla aujourd'hui ?"
    print(f"\n--- TEST 2: {q2} ---")
    inputs = {"question": q2}
    res = agent_app.invoke(inputs)
    print("🤖 REPONSE:", res["messages"][-1].content)

    # Ici, on donne une instruction explicite d'envoi
    q3 = "Résume les performances d'AWS en 2024 et envoie ce résumé par email à yanivbohbot5@gmail.com"
    print(f"\n--- TEST 3: Action ({q3}) ---")

    inputs = {"question": q3}

    # On utilise .stream() pour voir les étapes s'afficher
    for output in agent_app.stream(inputs):
        for node_name, node_content in output.items():
            print(f"👉 Étape terminée : {node_name}")
            # Si on est dans l'étape 'tools', on affiche le résultat de l'envoi
            if node_name == "tools":
                print(f"   🛠️ Résultat Outil : {node_content['messages'][0].content}")

    # Récupération de la réponse finale
    final_state = agent_app.invoke(inputs)
    print("\n🤖 RÉPONSE FINALE :")
    print(final_state["messages"][-1].content)


if __name__ == "__main__":
    run_test()
