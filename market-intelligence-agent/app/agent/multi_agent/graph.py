from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START
from langgraph.store.base import BaseStore

from app.agent.multi_agent.state import SupervisorState
from app.agent.multi_agent.supervisor import supervisor_node
from app.agent.multi_agent.rag_agent import build_rag_agent
from app.agent.multi_agent.finance_agent import build_finance_agent
from app.agent.multi_agent.portfolio_agent import build_portfolio_agent
from app.agent.multi_agent.memory_agent import build_memory_agent
from app.agent.multi_agent.filesystem_agent import build_filesystem_agent
from app.agent.multi_agent.browser_agent import build_browser_agent
from app.agent.multi_agent.email_agent import build_email_agent
from app.agent.graph import record_question

workflow = StateGraph(SupervisorState)
workflow.add_node("record_question", record_question)  # reused verbatim: converts
# state["question"] into a HumanMessage in state["messages"] — without this,
# finance_agent/portfolio_agent (which build their prompt from state["messages"])
# never see what the user actually asked.
workflow.add_node("supervisor", supervisor_node)
workflow.add_node("rag_agent", build_rag_agent())
workflow.add_node("finance_agent", build_finance_agent())
workflow.add_node("portfolio_agent", build_portfolio_agent())
workflow.add_node("memory_agent", build_memory_agent())
workflow.add_node("filesystem_agent", build_filesystem_agent())
workflow.add_node("browser_agent", build_browser_agent())
workflow.add_node("email_agent", build_email_agent())
workflow.add_edge(START, "record_question")
workflow.add_edge("record_question", "supervisor")
# No other static edges: supervisor_node and each specialist's terminal node
# route dynamically via Command(goto=...); specialists hand back to
# "supervisor" via Command(goto="supervisor", graph=Command.PARENT).


def build_multi_agent_app(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
):
    """Compile the multi-agent workflow with the supplied checkpointer and
    optional store. Same signature convention as
    app.agent.graph.build_agent_app / app.voice.graph.build_voice_agent_app.
    NOT wired into the FastAPI lifespan or any router yet — build and invoke
    directly (ainvoke/astream) in tests or scratch scripts."""
    return workflow.compile(checkpointer=checkpointer, store=store)
