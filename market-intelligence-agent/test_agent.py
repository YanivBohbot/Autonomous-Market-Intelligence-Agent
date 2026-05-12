"""Smoke-test the agent end-to-end against a real checkpointer + real tools.

Run with: `uv run python test_agent.py`. Mirrors how the FastAPI lifespan
builds the graph — opens an `AsyncSqliteSaver`, compiles, drives a couple of
queries, then exits.
"""

import asyncio

from app.agent.graph import build_agent_app
from app.agent.memory.checkpointer import create_checkpointer


async def run_test():
    async with create_checkpointer() as checkpointer:
        agent_app = build_agent_app(checkpointer)
        config = {"configurable": {"thread_id": "test_thread"}}

        q1 = "Quel est le revenu net d'Amazon en 2024 ?"
        print(f"\n--- TEST 1: {q1} ---")
        res = await agent_app.ainvoke({"question": q1}, config)
        print("🤖 REPONSE:", res["messages"][-1].content)

        q2 = "Quel est le prix de l'action Tesla aujourd'hui ?"
        print(f"\n--- TEST 2: {q2} ---")
        res = await agent_app.ainvoke({"question": q2}, config)
        print("🤖 REPONSE:", res["messages"][-1].content)

        q3 = (
            "Résume les performances d'AWS en 2024 et envoie ce résumé par email "
            "à yanivbohbot5@gmail.com"
        )
        print(f"\n--- TEST 3: Action ({q3}) ---")
        async for output in agent_app.astream({"question": q3}, config):
            for node_name, node_content in output.items():
                print(f"👉 Étape terminée : {node_name}")
                if node_name == "tools":
                    print(f"   🛠️ Résultat Outil : {node_content['messages'][0].content}")

        final_state = await agent_app.ainvoke(None, config)
        print("\n🤖 RÉPONSE FINALE :")
        print(final_state["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(run_test())
