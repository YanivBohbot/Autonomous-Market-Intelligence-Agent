"""AgentCore Runtime entrypoint for the Market Intelligence Agent.

Wraps the existing LangGraph workflow (imported from app.agent.graph) and
exposes it to AgentCore Runtime via the BedrockAgentCoreApp HTTP contract.

Phase 2 (local dev validation): uses in-memory MemorySaver for checkpointing.
This is swapped for a durable checkpointer in Phase 3.
"""
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from opentelemetry.instrumentation.langchain import LangchainInstrumentor
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from app.agent.graph import build_agent_app

LangchainInstrumentor().instrument()

app = BedrockAgentCoreApp()
log = app.logger

# Compile once at module load — graph is stateless across invocations,
# state lives in the checkpointer keyed by thread_id.
_checkpointer = MemorySaver()
_agent_app = build_agent_app(checkpointer=_checkpointer)


@app.entrypoint
async def invoke(payload, context):
    """AgentCore Runtime entrypoint.

    Payload shapes:
      - New turn:  {"prompt": "<user input>"}
      - HITL resume: {"resume": "approve" | "reject"}

    Session continuity: AgentCore Runtime provides session isolation via
    `context.session_id`. We use it directly as the LangGraph thread_id
    so checkpointer state persists across turns within the same session.
    """
    thread_id = getattr(context, "session_id", None) or "default"
    config = {"configurable": {"thread_id": thread_id}}

    log.info(f"[invoke] thread_id={thread_id} payload_keys={list(payload.keys())}")

    if "resume" in payload:
        # HITL continuation — resume the interrupted graph with the decision.
        decision = payload["resume"]
        log.info(f"[invoke] resuming thread_id={thread_id} decision={decision}")
        result = await _agent_app.ainvoke(Command(resume=decision), config=config)
    else:
        # Fresh turn — feed the user prompt into a new graph run.
        prompt = payload.get("prompt", "")
        if not prompt:
            return {"error": "payload missing 'prompt' or 'resume'"}
        result = await _agent_app.ainvoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "question": prompt,
                "documents": [],
            },
            config=config,
        )

    # Detect interrupted state (HITL pending) vs completed.
    snapshot = await _agent_app.aget_state(config)
    if snapshot.next:
        # Graph is paused at an interrupt — surface the pending tool calls.
        last = result["messages"][-1] if result.get("messages") else None
        pending = getattr(last, "tool_calls", None) or []
        return {
            "status": "interrupted",
            "next_step": snapshot.next[0] if snapshot.next else None,
            "pending_tool_calls": pending,
            "thread_id": thread_id,
        }

    # Graph reached END — return final assistant message.
    final = result["messages"][-1].content if result.get("messages") else ""
    return {
        "status": "completed",
        "response": final,
        "thread_id": thread_id,
    }


if __name__ == "__main__":
    app.run()
