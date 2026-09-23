from langgraph.types import Command
from langgraph.graph import StateGraph, START
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage

from app.core.config import settings
from app.agent.multi_agent.state import SupervisorState
from app.agent.prompts import with_today
from app.agent.prompts.specialist_agent_prompts import BROWSER_SYSTEM_PROMPT
from app.agent.tools import browser_navigate_tool, browser_snapshot_tool, browser_screenshot_tool
from app.agent.graph import approval_node, route_after_approval
from app.agent.nodes.tool_utils import make_tool_runner

_BROWSER_TOOLS = [browser_navigate_tool, browser_snapshot_tool, browser_screenshot_tool]
_llm_with_tools = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True).bind_tools(_BROWSER_TOOLS)


def browser_agent_node(state: SupervisorState) -> Command:
    # See finance_agent.py for why this returns bare `Command` (no Literal
    # generic) instead of Command[Literal["approval", "supervisor"]].
    response = _llm_with_tools.invoke([SystemMessage(content=with_today(BROWSER_SYSTEM_PROMPT)), *state["messages"]])
    if getattr(response, "tool_calls", None):
        return Command(goto="approval", update={"messages": [response]})
    return Command(goto="supervisor", graph=Command.PARENT, update={"messages": [response]})


workflow = StateGraph(SupervisorState)
workflow.add_node("agent", browser_agent_node)
workflow.add_node("approval", approval_node)
workflow.add_node("tools", make_tool_runner(_BROWSER_TOOLS))
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("approval", route_after_approval, {"tools": "tools", "generate": "agent"})
workflow.add_edge("tools", "agent")


def build_browser_agent():
    return workflow.compile()
