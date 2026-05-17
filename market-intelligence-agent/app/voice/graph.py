"""Voice-mode LangGraph.

A simplified copy of `app.agent.graph` that skips the slow `rag` → `grader`
nodes. Voice questions are typically conversational ("What's Apple's price?",
"Send an email...") and rarely need the Pinecone vector store, so paying the
~2–3 s latency on every turn isn't worth it. Document-style questions stay
on the full text-mode graph in `app.agent.graph`.

The remaining flow (`generate` → `approval` → `tools` → ...) is reused
unchanged so RAG-free turns still get the same MCP tools, HITL approval,
and SQLite checkpointing.
"""
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore

from app.agent.graph import approval_node, route_after_approval, route_after_generate
from app.agent.nodes.generate import generate_answer
from app.agent.state import AgentState
from app.agent.tools import TOOLS


def _init_voice_state(state: AgentState) -> dict:
    """Pre-populate `documents=[]` so `generate_answer` (which reads
    `state["documents"]`) doesn't raise KeyError. Voice questions skip RAG."""
    return {"documents": []}


voice_workflow = StateGraph(AgentState)
voice_workflow.add_node("init", _init_voice_state)
voice_workflow.add_node("generate", generate_answer)
voice_workflow.add_node("approval", approval_node)
voice_workflow.add_node("tools", ToolNode(TOOLS))

voice_workflow.add_edge(START, "init")
voice_workflow.add_edge("init", "generate")
voice_workflow.add_conditional_edges(
    "generate",
    route_after_generate,
    {"approval": "approval", END: END},
)
voice_workflow.add_conditional_edges(
    "approval",
    route_after_approval,
    {"tools": "tools", "generate": "generate"},
)
voice_workflow.add_edge("tools", "generate")


def build_voice_agent_app(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
):
    """Compile the voice-mode graph. Same checkpointer/store as text mode so
    voice and text can share threads if desired (today they use separate
    `thread_id`s)."""
    return voice_workflow.compile(checkpointer=checkpointer, store=store)
