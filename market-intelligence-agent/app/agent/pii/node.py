"""Single-agent guard node: stops the run before `generate` if the user's
message contains sensitive data.

Only credit cards are checked here (`check_email=False`): unlike the
multi-agent graph, which can scope email-blocking per specialist, this one
graph bundles `send_email` alongside everything else, so it needs real
addresses to work — same reason `email_agent` is exempt in
`app/agent/common.py`."""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END

from app.agent.pii.detection import SENSITIVE_DATA_WARNING, contains_sensitive_data
from app.agent.state import AgentState


def pii_guard_node(state: AgentState) -> dict:
    messages = state.get("messages") or []
    if not messages:
        return {}
    last = messages[-1]
    if isinstance(last, HumanMessage) and contains_sensitive_data(last.content, check_email=False):
        return {"messages": [AIMessage(content=SENSITIVE_DATA_WARNING)]}
    return {}


def route_after_pii_guard(state: AgentState):
    last = state["messages"][-1]
    if isinstance(last, AIMessage):
        return END
    return "generate"
