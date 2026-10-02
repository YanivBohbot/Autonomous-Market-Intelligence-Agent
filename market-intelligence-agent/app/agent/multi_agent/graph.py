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
    workflow.add_edge(START, "record_question")
    workflow.add_edge("record_question", "supervisor")
    return workflow


def build_multi_agent_app(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
):
    """Build and compile the multi-agent workflow. Specialists are built per
    call (not at import) so tests can patch each module's `specialist_model`.
    NOT wired into the FastAPI lifespan or any router — build and invoke
    directly (ainvoke/astream) in tests or scripts."""
    return _build_workflow().compile(checkpointer=checkpointer, store=store)
