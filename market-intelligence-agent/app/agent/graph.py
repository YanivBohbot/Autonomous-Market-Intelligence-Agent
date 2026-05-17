from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore
from langgraph.types import interrupt
from langchain_core.messages import ToolMessage
from app.agent.state import AgentState
from app.agent.nodes.rag import retrieve_internal_documentation
from app.agent.nodes.research import web_search
from app.agent.nodes.grader import grade_documents
from app.agent.nodes.generate import generate_answer
from app.agent.tools import TOOLS, READ_ONLY_TOOLS


def decide_next_step(state: AgentState):
    if len(state["documents"]) > 0:
        return "generate"
    return "web_search"


def route_after_generate(state: AgentState):
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "approval"
    return END


def approval_node(state: AgentState) -> dict:
    """Pause graph execution and surface pending side-effect tool calls for human review.

    Read-only tool calls (per READ_ONLY_TOOLS allowlist) bypass the interrupt and execute
    immediately. Mixed batches follow the interrupt-if-any rule: if any call is a side
    effect, the node interrupts and surfaces the side-effect call(s) to the human.
    Resumer passes 'approve' to proceed or 'reject' to cancel; on reject, every tool
    call in the batch (read-only or not) is cancelled with a ToolMessage."""
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []

    side_effect_calls = [tc for tc in tool_calls if tc["name"] not in READ_ONLY_TOOLS]
    if not side_effect_calls:
        # All read-only — no human approval needed.
        return {}

    requests = [
        {
            "action_request": {"action": tc["name"], "args": tc["args"]},
            "config": {
                "allow_ignore": False,
                "allow_respond": False,
                "allow_edit": False,
                "allow_accept": True,
            },
            "description": f"Approve or reject {tc['name']} with args {tc['args']}",
        }
        for tc in side_effect_calls
    ]
    decisions = interrupt(requests)
    # Resume payload shape varies by caller:
    #   - /approve router sends a bare string ("approve" | "reject")
    #   - tests patch interrupt() to return a list of strings or dicts
    # Normalize to a list of length len(side_effect_calls): broadcast a single
    # global decision across all pending calls; treat anything else element-wise.
    if isinstance(decisions, str):
        raw = [decisions] * len(side_effect_calls)
    elif isinstance(decisions, list) and decisions:
        raw = decisions * len(side_effect_calls) if len(decisions) == 1 else decisions
    else:
        raw = ["reject"] * len(side_effect_calls)
    normalized = [
        d.get("type", "reject") if isinstance(d, dict) else d
        for d in raw
    ]
    if normalized and all(d == "approve" for d in normalized):
        return {}
    cancel_msgs = [
        ToolMessage(content="Action cancelled by user.", tool_call_id=t["id"], name=t["name"])
        for t in tool_calls
    ]
    return {"messages": cancel_msgs}


def route_after_approval(state: AgentState):
    last = state["messages"][-1]
    if isinstance(last, ToolMessage):
        return "generate"
    return "tools"


workflow = StateGraph(AgentState)
workflow.add_node("rag", retrieve_internal_documentation)
workflow.add_node("grader", grade_documents)
workflow.add_node("web_search", web_search)
workflow.add_node("generate", generate_answer)
workflow.add_node("approval", approval_node)
workflow.add_node("tools", ToolNode(TOOLS))

workflow.add_edge(START, "rag")
workflow.add_edge("rag", "grader")
workflow.add_conditional_edges(
    "grader",
    decide_next_step,
    {"generate": "generate", "web_search": "web_search"},
)
workflow.add_edge("web_search", "generate")
workflow.add_conditional_edges(
    "generate",
    route_after_generate,
    {"approval": "approval", END: END},
)
workflow.add_conditional_edges(
    "approval",
    route_after_approval,
    {"tools": "tools", "generate": "generate"},
)
workflow.add_edge("tools", "generate")

def build_agent_app(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
):
    """Compile the workflow with the supplied checkpointer and optional store.

    Compilation is deferred from module load so the FastAPI lifespan can open an
    `AsyncSqliteSaver` (which requires a running event loop) and pass it in.
    The `store` is the cross-thread long-term memory (LangGraph's BaseStore API).
    Tests that only inspect graph structure can omit the store.
    """
    return workflow.compile(checkpointer=checkpointer, store=store)
