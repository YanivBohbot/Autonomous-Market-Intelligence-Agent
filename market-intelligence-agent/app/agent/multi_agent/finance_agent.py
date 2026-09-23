from langgraph.types import Command
from langgraph.graph import StateGraph, START
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage

from app.core.config import settings
from app.agent.multi_agent.state import SupervisorState
from app.agent.prompts import with_today
from app.agent.prompts.specialist_agent_prompts import FINANCE_SYSTEM_PROMPT
from app.agent.tools import yf_quote_tool, yf_history_tool, yf_news_tool
from app.agent.graph import approval_node, route_after_approval
from app.agent.nodes.tool_utils import make_tool_runner

_FINANCE_TOOLS = [yf_quote_tool, yf_history_tool, yf_news_tool]
_llm_with_tools = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True).bind_tools(_FINANCE_TOOLS)


def finance_agent_node(state: SupervisorState) -> Command:
    # NOTE: return type is bare `Command` (no Literal[...] generic) because
    # LangGraph statically validates a Command[Literal[...]] annotation
    # against the LOCAL graph's node set; "supervisor" lives in the PARENT
    # graph (reached via graph=Command.PARENT below) and would fail
    # compile-time validation ("Found edge ending at unknown node
    # `supervisor`") if declared here.
    response = _llm_with_tools.invoke([SystemMessage(content=with_today(FINANCE_SYSTEM_PROMPT)), *state["messages"]])
    if getattr(response, "tool_calls", None):
        return Command(goto="approval", update={"messages": [response]})
    return Command(goto="supervisor", graph=Command.PARENT, update={"messages": [response]})


workflow = StateGraph(SupervisorState)
workflow.add_node("agent", finance_agent_node)
workflow.add_node("approval", approval_node)
workflow.add_node("tools", make_tool_runner(_FINANCE_TOOLS))
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("approval", route_after_approval, {"tools": "tools", "generate": "agent"})
workflow.add_edge("tools", "agent")


def build_finance_agent():
    return workflow.compile()
