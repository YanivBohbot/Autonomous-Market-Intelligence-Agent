from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes.rag import retrieve_internal_documentation
from app.agent.nodes.research import web_search
from app.agent.nodes.grader import grade_documents
from app.agent.nodes.generate import generate_answer
from langgraph.prebuilt import ToolNode, tools_condition
from app.agent.tools.emails import send_email_tool
from app.agent.tools.mcp_clients.mcp_client import crm_tool
from langgraph.checkpoint.memory import MemorySaver


def decide_next_step(state: AgentState):
    if len(state["documents"]) > 0:
        return "generate"
    return "web_search"


workflow = StateGraph(AgentState)
workflow.add_node("rag", retrieve_internal_documentation)
workflow.add_node("grader", grade_documents)
workflow.add_node("web_search", web_search)
workflow.add_node("generate", generate_answer)

tools_list = [send_email_tool, crm_tool]

workflow.add_node("tools", ToolNode(tools_list))

workflow.set_entry_point("rag")
workflow.add_edge("rag", "grader")


workflow.add_conditional_edges(
    "grader",
    decide_next_step,
    {"generate": "generate", "web_search": "web_search"},
)
workflow.add_edge("web_search", "generate")

workflow.add_conditional_edges(
    "generate",
    tools_condition,  # Fonction native de LangGraph qui détecte les appels d'outils
    {
        "tools": "tools",
        END: END,
    },
)
workflow.add_edge("tools", "generate")
memory = MemorySaver()
agent_app = workflow.compile(
    checkpointer=memory,
    # On dit à LangGraph : "Arrête-toi JUSTE AVANT d'entrer dans le noeud 'tools'"
    # Cela permet de valider l'action.
    interrupt_before=["tools"],
)
