"""Single-agent guard node: stops the run before `generate` if the user's
message contains sensitive data."""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END

from app.agent.pii.detection import SENSITIVE_DATA_WARNING, contains_sensitive_data
from app.agent.state import AgentState


def pii_guard_node(state: AgentState) -> dict:
    messages = state.get("messages") or []
    if not messages:
        return {}
    last = messages[-1]
    if isinstance(last, HumanMessage) and contains_sensitive_data(last.content):
        return {"messages": [AIMessage(content=SENSITIVE_DATA_WARNING)]}
    return {}


def route_after_pii_guard(state: AgentState):
    last = state["messages"][-1]
    if isinstance(last, AIMessage):
        return END
    return "generate"
