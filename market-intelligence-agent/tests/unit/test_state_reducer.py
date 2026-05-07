from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages
from app.agent.state import AgentState


def test_state_uses_add_messages_reducer():
    """AgentState.messages must use add_messages, not operator.add."""
    annotation = AgentState.__annotations__["messages"]
    assert add_messages in annotation.__metadata__, (
        "messages reducer must be add_messages from langgraph.graph.message"
    )


def test_add_messages_replaces_message_with_same_id():
    """add_messages dedupes by ID — this is the behavior we want."""
    base = [HumanMessage(content="hi", id="1")]
    update = [HumanMessage(content="hi again", id="1")]
    merged = add_messages(base, update)
    assert len(merged) == 1
    assert merged[0].content == "hi again"
