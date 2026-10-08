import re
import sqlite3

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import RetryPolicy
from app.agent.graph import record_question
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
    workflow.add_node("record_question", record_question)
    # supervisor_node's _router.invoke() is a raw ChatOpenAI call outside any
    # create_agent middleware stack -- ModelRetryMiddleware can't attach to
    # it, so a transient OpenAI error here has nothing else retrying it.
    # RetryPolicy is safe at this specific node: no tool/side-effect runs
    # inside supervisor_node, so re-executing it on retry can't double a
    # side effect (unlike a specialist node, where retrying the whole
    # subgraph could re-run a tool that already succeeded).
    workflow.add_node("supervisor", supervisor_node, retry_policy=RetryPolicy())
    for name, agent_specialist in SPECIALISTS.items():
        workflow.add_node(name, agent_specialist())
        workflow.add_edge(name, "supervisor")
    workflow.add_edge(START, "load_client_context")
    workflow.add_edge("load_client_context", "record_question")
    workflow.add_edge("record_question", "supervisor")
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
