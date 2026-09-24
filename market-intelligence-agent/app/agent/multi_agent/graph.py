from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.store.base import BaseStore

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

# create_agent specialists: added as subgraph nodes, static edge back to the
# supervisor (they share the `messages` key with SupervisorState).
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
    # record_question converts state["question"] into a HumanMessage — without
    # it the specialists (which read state["messages"]) never see the question.
    workflow.add_node("record_question", record_question)
    workflow.add_node("supervisor", supervisor_node)
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
