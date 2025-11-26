import operator
from typing import Annotated, List, TypedDict
from langchain_core.messages import AnyMessage


class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], operator.add]
    question: str
    documents: List[str]
