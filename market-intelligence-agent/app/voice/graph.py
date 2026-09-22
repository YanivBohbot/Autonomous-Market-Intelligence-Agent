"""Voice-mode LangGraph.

A simplified copy of `app.agent.graph` that skips the HITL-irrelevant
`record_question` bookkeeping node (voice turns are driven by the
delegation worker, not the /stream API). Retrieval (`search_knowledge_base`,
`web_search`) is available the same way it is in text mode: as ordinary
tools the LLM opts into per turn, so voice pays no fixed retrieval latency
tax on every conversational turn.

The remaining flow (`generate` → `approval` → `tools` → ...) is reused
unchanged so voice turns still get the same MCP tools, HITL approval,
and SQLite checkpointing.
"""
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.store.base import BaseStore

from app.agent.graph import approval_node, route_after_approval, route_after_generate, run_tools
from app.agent.nodes.generate import generate_answer
from app.agent.state import AgentState


voice_workflow = StateGraph(AgentState)
voice_workflow.add_node("generate", generate_answer)
voice_workflow.add_node("approval", approval_node)
voice_workflow.add_node("tools", run_tools)

voice_workflow.add_edge(START, "generate")
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
