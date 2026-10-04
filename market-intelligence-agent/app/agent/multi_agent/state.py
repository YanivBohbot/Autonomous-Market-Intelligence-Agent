from typing import Annotated, List, Optional, TypedDict
from langchain.agents import AgentState
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class SupervisorState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    question: str
    documents: List[str]
    next_agent: Optional[str]
    agent_hops: int
    # Unlike next_agent (cleared to None whenever a turn finishes), this
    # never resets -- it's the specialist the supervisor last routed to
    # (set at routing time, not verified to have actually answered), used
    # by the supervisor's deterministic sticky-routing rule.
    last_agent: Optional[str]
    # Set every turn by load_client_context, from the thread id -- see that
    # function's docstring. None on every thread except a client workspace's.
    client_context: Optional[str]


class ClientContextState(AgentState):
    """create_agent's own state schema, extended with the one field
    specialists need from the parent graph's SupervisorState. Passed as
    state_schema= on portfolio_agent/finance_agent/rag_agent's
    create_agent(...) calls -- without it, the matching key on the parent
    graph's state is never forwarded into the specialist subgraph, and
    request.state.get("client_context") inside client_context_prompt would
    always be None. Key name must match SupervisorState.client_context."""
    client_context: Optional[str]
