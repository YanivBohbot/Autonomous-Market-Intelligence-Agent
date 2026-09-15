from langgraph.types import Command
from langgraph.graph import StateGraph, START
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage

from app.core.config import settings
from app.agent.multi_agent.state import SupervisorState
from app.agent.prompts.specialist_agent_prompts import RAG_SYNTHESIS_PROMPT
from app.agent.nodes.rag import retrieve_internal_documentation
from app.agent.nodes.grader import grade_documents
from app.agent.nodes.research import web_search

_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True)  # NOT tool-bound


def synthesize_node(state: SupervisorState) -> Command:
    # See finance_agent.py for why this returns bare `Command` (no Literal
    # generic) instead of Command[Literal["supervisor"]].
    context = "\n\n".join(state["documents"])
    msgs = [SystemMessage(content=RAG_SYNTHESIS_PROMPT), *state["messages"]]
    if context:
        msgs.append(SystemMessage(content="Reference material retrieved for this turn:\n" + context))
    response = _llm.invoke(msgs)
    return Command(goto="supervisor", graph=Command.PARENT, update={"messages": [response]})


def decide_next_step(state: SupervisorState):
    # Local re-implementation: app.agent.graph's version of this branch is a
    # private module-level function there, not exported for reuse.
    return "synthesize" if len(state["documents"]) > 0 else "web_search"


workflow = StateGraph(SupervisorState)
workflow.add_node("retrieve", retrieve_internal_documentation)
workflow.add_node("grade", grade_documents)
workflow.add_node("web_search", web_search)
workflow.add_node("synthesize", synthesize_node)
workflow.add_edge(START, "retrieve")
workflow.add_edge("retrieve", "grade")
workflow.add_conditional_edges("grade", decide_next_step, {"synthesize": "synthesize", "web_search": "web_search"})
workflow.add_edge("web_search", "synthesize")


def build_rag_agent():
    return workflow.compile()
