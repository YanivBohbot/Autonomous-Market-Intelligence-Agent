import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END

from app.agent.pii import (
    SENSITIVE_DATA_WARNING,
    SensitiveDataGuard,
    contains_sensitive_data,
    pii_guard_node,
    route_after_pii_guard,
)
from tests.unit.fake_chat import FakeToolModel


def test_contains_sensitive_data_detects_credit_card():
    assert contains_sensitive_data("my card is 4111 1111 1111 1111") is True


def test_contains_sensitive_data_detects_email():
    assert contains_sensitive_data("contact jane.doe@example.com please") is True


def test_contains_sensitive_data_false_for_clean_text():
    assert contains_sensitive_data("what is my portfolio value?") is False


def test_contains_sensitive_data_false_for_empty_or_none():
    assert contains_sensitive_data("") is False
    assert contains_sensitive_data(None) is False


# --- single-agent node ---


def test_pii_guard_node_blocks_on_credit_card():
    state = {"messages": [HumanMessage("my card is 4111 1111 1111 1111")], "question": "q"}
    result = pii_guard_node(state)
    assert len(result["messages"]) == 1
    warning = result["messages"][0]
    assert isinstance(warning, AIMessage)
    assert warning.content == SENSITIVE_DATA_WARNING


def test_pii_guard_node_passes_through_clean_message():
    state = {"messages": [HumanMessage("what is my portfolio value?")], "question": "q"}
    assert pii_guard_node(state) == {}


def test_route_after_pii_guard_ends_when_blocked():
    state = {"messages": [HumanMessage("x"), AIMessage(SENSITIVE_DATA_WARNING)], "question": "q"}
    assert route_after_pii_guard(state) == END


def test_route_after_pii_guard_continues_to_generate_when_clean():
    state = {"messages": [HumanMessage("what is my portfolio value?")], "question": "q"}
    assert route_after_pii_guard(state) == "generate"


# --- multi-agent middleware ---


@pytest.mark.anyio
async def test_sensitive_data_guard_blocks_before_the_model_is_ever_called():
    model = FakeToolModel([AIMessage(content="should never be reached")])
    agent = create_agent(
        model=model, tools=[], system_prompt="S", middleware=[SensitiveDataGuard()]
    )
    result = await agent.ainvoke(
        {"messages": [HumanMessage("contact jane.doe@example.com please")]}
    )
    assert model.seen == []
    assert result["messages"][-1].content == SENSITIVE_DATA_WARNING


@pytest.mark.anyio
async def test_sensitive_data_guard_lets_clean_messages_through():
    model = FakeToolModel([AIMessage(content="42")])
    agent = create_agent(
        model=model, tools=[], system_prompt="S", middleware=[SensitiveDataGuard()]
    )
    result = await agent.ainvoke({"messages": [HumanMessage("what is my portfolio value?")]})
    assert len(model.seen) == 1
    assert result["messages"][-1].content == "42"
