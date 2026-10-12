import re
import sqlite3

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from app.agent.multi_agent.browser_agent import build_browser_agent
from app.agent.multi_agent.email_agent import build_email_agent
from app.agent.multi_agent.filesystem_agent import build_filesystem_agent
from app.agent.multi_agent.finance_agent import build_finance_agent
from app.agent.multi_agent.memory_agent import build_memory_agent
from app.agent.multi_agent.portfolio_agent import build_portfolio_agent
from app.agent.multi_agent.rag_agent import build_rag_agent
from app.agent.multi_agent.state import SupervisorState
from app.agent.multi_agent.supervisor import supervisor_node
from app.data_import.db import DB_PATH, get_client_with_holdings

_CLIENT_THREAD_RE = re.compile(r"^clients_(\d+)$")


def record_multi_agent_question(
    state: SupervisorState, config: RunnableConfig
) -> dict:
    """Persist a turn with its transport source for presentation filtering."""
    question = state.get("question")
    if not question:
        return {}
    configured_source = (config.get("metadata") or {}).get("input_source")
    source = "voice" if configured_source == "voice" else "text"
    return {
        "messages": [
            HumanMessage(content=question, additional_kwargs={"source": source})
        ],
        "turn_source": source,
    }


def finalize_turn(state: SupervisorState) -> dict:
    """Tag voice-generated AI messages while preserving their message ids."""
    if state.get("turn_source") != "voice":
        return {}

    messages = state.get("messages", [])
    latest_human_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
        ),
        None,
    )
    if latest_human_index is None:
        return {}

    replacements = []
    for message in messages[latest_human_index + 1 :]:
        if not isinstance(message, AIMessage):
            continue
        additional_kwargs = dict(message.additional_kwargs)
        additional_kwargs["source"] = "voice"
        replacements.append(
            message.model_copy(update={"additional_kwargs": additional_kwargs})
        )
    return {"messages": replacements} if replacements else {}


def load_client_context(state: SupervisorState, config: RunnableConfig) -> dict:
    """Derive which client this thread is scoped to straight from the
    thread id (clients_<id>) rather than anything the frontend pushes --
    see docs/superpowers/specs/2026-10-04-clients-workspace-design.md
    decision 4. Runs every turn (cheap single-row read), not only the
    first, so an edit via /data/import mid-conversation is reflected on
    the very next turn instead of staying stale from an earlier
    checkpoint."""
    thread_id = (config.get("configurable") or {}).get("thread_id", "")
    match = _CLIENT_THREAD_RE.match(thread_id)
    if not match:
        return {"client_context": None}
    conn = sqlite3.connect(DB_PATH)
    try:
        client = get_client_with_holdings(conn, int(match.group(1)))
    finally:
        conn.close()
    if client is None:
        return {"client_context": None}
    return {"client_context": (
        f"Active client: {client['name']}, segment {client['segment']}, "
        f"risk {client['risk_profile']}, advisor {client['advisor']}."
    )}


SPECIALISTS = {
    "rag_agent": lambda: build_rag_agent(),
    "finance_agent": lambda: build_finance_agent(),
    "portfolio_agent": lambda: build_portfolio_agent(),
    "browser_agent": lambda: build_browser_agent(),
    "memory_agent": lambda: build_memory_agent(),
    "filesystem_agent": lambda: build_filesystem_agent(),
    "email_agent": lambda: build_email_agent(),
}


def _build_workflow() -> StateGraph:
    workflow = StateGraph(SupervisorState)
    workflow.add_node("load_client_context", load_client_context)
    workflow.add_node("record_question", record_multi_agent_question)
    # The routing call is a create_agent (supervisor.router_agent): its
    # middleware covers the card guard (block_credit_cards) and transient
    # OpenAI errors (ModelRetryMiddleware), so no guard node or RetryPolicy.
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("finalize_turn", finalize_turn)
    for name, agent_specialist in SPECIALISTS.items():
        workflow.add_node(name, agent_specialist())
        workflow.add_edge(name, "supervisor")
    workflow.add_edge(START, "load_client_context")
    workflow.add_edge("load_client_context", "record_question")
    workflow.add_edge("record_question", "supervisor")
    workflow.add_edge("finalize_turn", END)
    return workflow


def build_multi_agent_app(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
):
    """Build and compile the multi-agent workflow. Specialists are built per
    call (not at import) so tests can patch each module's `specialist_model`.
    FastAPI builds this graph once during lifespan and shares it across the
    text, AgentCore, and Market Desk transports."""
    return _build_workflow().compile(checkpointer=checkpointer, store=store)
