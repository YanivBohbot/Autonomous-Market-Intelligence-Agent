"""AgentCore Runtime entrypoint for the Market Intelligence Agent.

Wraps the existing LangGraph workflow (imported from app.agent.graph) and
exposes it to AgentCore Runtime via the BedrockAgentCoreApp HTTP contract.

Persistence selection is env-driven:
- DDB_CHECKPOINT_TABLE set    → DynamoDBSaver (durable per-thread state in AWS)
- unset                       → MemorySaver (in-memory, local-dev fallback)
- MEMORY_USER_FACTS_ID set    → AgentCoreMemoryStore (managed long-term store)
- unset                       → InMemoryStore (local-dev fallback)
"""
import os

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from opentelemetry.instrumentation.langchain import LangchainInstrumentor
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from app.agent.graph import build_agent_app

LangchainInstrumentor().instrument()

app = BedrockAgentCoreApp()
log = app.logger


def _build_checkpointer() -> BaseCheckpointSaver:
    """Pick DynamoDB in AWS, MemorySaver locally — single env-var switch."""
    table = os.getenv("DDB_CHECKPOINT_TABLE")
    if table:
        from langgraph_checkpoint_aws import DynamoDBSaver
        log.info(f"[checkpointer] DynamoDBSaver table={table}")
        return DynamoDBSaver(
            table_name=table,
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            ttl_seconds=86400 * 7,
            enable_checkpoint_compression=True,
        )
    log.info("[checkpointer] MemorySaver (local-dev fallback)")
    return MemorySaver()


def _build_store() -> BaseStore:
    """Pick AgentCore Memory in AWS, in-memory store locally — single env-var switch.

    The L3 `AgentCoreApplication` CDK construct provisions the Memory resource
    (declared in agentcore.json) and injects MEMORY_USER_FACTS_ID as an env var.
    When unset (local dev) we fall back to LangGraph's InMemoryStore so the
    memory tools (save/recall/list_memory) still work in the same process.
    """
    memory_id = os.getenv("MEMORY_USER_FACTS_ID")
    if memory_id:
        from langgraph_checkpoint_aws import AgentCoreMemoryStore
        log.info(f"[store] AgentCoreMemoryStore memory_id={memory_id}")
        return AgentCoreMemoryStore(
            memory_id=memory_id,
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
    log.info("[store] InMemoryStore (local-dev fallback)")
    return InMemoryStore()


# Compile once at module load — graph is stateless across invocations,
# state lives in the checkpointer keyed by thread_id and the store keyed
# by namespace.
_checkpointer = _build_checkpointer()
_store = _build_store()
_agent_app = build_agent_app(checkpointer=_checkpointer, store=_store)


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
