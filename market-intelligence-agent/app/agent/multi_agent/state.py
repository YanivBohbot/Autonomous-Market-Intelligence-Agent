from typing import Annotated, List, Optional, TypedDict
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
