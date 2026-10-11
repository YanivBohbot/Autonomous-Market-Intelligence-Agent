"""Smoke-test the agent end-to-end against a real checkpointer + real tools.

Run with: `uv run python test_agent.py`. Mirrors how the FastAPI lifespan
builds the graph -- opens the checkpointer, compiles the multi-agent graph
(supervisor + specialists), drives a few queries, then exits.
"""

import asyncio
import uuid

from langgraph.types import Command

from app.agent.memory.checkpointer import create_checkpointer
from app.agent.memory.store import create_store
from app.agent.multi_agent import build_multi_agent_app


async def run_test():
    async with create_checkpointer() as checkpointer:
        # save_memory/recall_memory/list_memories need an injected store, as
        # server.py's lifespan always passes one.
        agent_app = build_multi_agent_app(checkpointer, create_store())
        config = {"configurable": {"thread_id": f"smoke-{uuid.uuid4()}", "actor_id": "smoke"}}

        q1 = "What were Amazon's total net sales in 2024?"
        print(f"\n--- TEST 1 (rag): {q1} ---")
        res = await agent_app.ainvoke({"question": q1}, config)
        print("REPONSE:", res["messages"][-1].content)

        q2 = "What is Tesla's stock price today?"
        print(f"\n--- TEST 2 (finance): {q2} ---")
        res = await agent_app.ainvoke({"question": q2}, config)
        print("REPONSE:", res["messages"][-1].content)

        q3 = "Send an email to Margaret Collins with a short summary of her portfolio"
        print(f"\n--- TEST 3 (HITL): {q3} ---")
        await agent_app.ainvoke({"question": q3}, config)
        snapshot = await agent_app.aget_state(config, subgraphs=True)
        if snapshot.next:
            # send_email pauses for approval (HumanInTheLoopMiddleware). The
            # smoke test REJECTS it so no real email is sent.
            print("Approval pending -> rejecting (no email sent)")
            final = await agent_app.ainvoke(
                Command(resume={"decisions": [{"type": "reject", "message": "Smoke test"}]}), config
            )
            print("REPONSE:", final["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(run_test())
