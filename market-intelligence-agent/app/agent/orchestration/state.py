from typing import Annotated, List, Literal, Optional, TypedDict
from langchain.agents import AgentState
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class SupervisorState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    question: str
    documents: List[str]
    next_agent: Optional[str]
    agent_hops: int
    last_agent: Optional[str]
    client_context: Optional[str]
    turn_source: Literal["text", "voice"]


class ClientContextState(AgentState):
    """create_agent's own state schema, extended with the one field
    specialists need from the parent graph's SupervisorState. Passed as
    state_schema= on portfolio_agent/finance_agent/rag_agent's
    create_agent(...) calls -- without it, the matching key on the parent
    graph's state is never forwarded into the specialist subgraph, and
    request.state.get("client_context") inside client_context_prompt would
    always be None. Key name must match SupervisorState.client_context."""

    client_context: Optional[str]
