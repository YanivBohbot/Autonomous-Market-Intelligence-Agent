"""Smoke-test the agent end-to-end against a real checkpointer + real tools.

Run with: `uv run python test_agent.py`. Mirrors how the FastAPI lifespan
builds the graph — opens an `AsyncSqliteSaver`, compiles, drives a couple of
queries, then exits.
"""

import asyncio

from langgraph.types import Command

from app.agent.graph import build_agent_app
from app.agent.memory.checkpointer import create_checkpointer
from app.agent.memory.store import create_store


async def run_test():
    async with create_checkpointer() as checkpointer:
        # save_memory/recall_memory/list_memories need an injected store --
        # without one, any turn that calls them fails with "Cannot inject
        # store into tools with InjectedStore annotations" (server.py's
        # lifespan always passes one; this script must too).
        agent_app = build_agent_app(checkpointer, create_store())
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

        # send_email is a side-effect tool: the graph paused at approval via
        # interrupt() and needs the same Command(resume=...) shape /approve
        # uses (app/api/routers/approve.py) -- plain ainvoke(None, config)
        # never resolves the interrupt, leaving the pending tool_call
        # unanswered forever and poisoning this thread's persisted history.
        snapshot = await agent_app.aget_state(config)
        if snapshot.next:
            final_state = await agent_app.ainvoke(Command(resume="approve"), config)
            print("\n🤖 RÉPONSE FINALE :")
            print(final_state["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(run_test())
