"""block_credit_cards: the documented @before_agent guardrail
(docs.langchain.com/oss/python/langchain/guardrails), decorator syntax."""
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.guardrails.card_guard import block_credit_cards
from app.agent.guardrails.detection import SENSITIVE_DATA_WARNING
from tests.unit.fake_chat import FakeToolModel


def _agent(model):
    return create_agent(model=model, tools=[], middleware=[block_credit_cards])


def test_a_card_ends_the_run_before_any_model_call_with_a_masked_question():
    model = FakeToolModel([AIMessage(content="should not run")])
    question = HumanMessage(content="My card is 4111 1111 1111 1111, NVDA price?", id="h1")
    result = _agent(model).invoke({"messages": [question]})
    assert model.seen == []
    masked, warning = result["messages"]
    assert masked.id == "h1"
    assert "4111 1111 1111 1111" not in masked.content
    assert masked.content.endswith("NVDA price?")
    assert warning.content == SENSITIVE_DATA_WARNING


def test_a_card_inside_content_blocks_is_also_blocked():
    model = FakeToolModel([AIMessage(content="should not run")])
    question = HumanMessage(content=[{"type": "text", "text": "card 4111 1111 1111 1111"}], id="h1")
    result = _agent(model).invoke({"messages": [question]})
    assert model.seen == []
    assert result["messages"][-1].content == SENSITIVE_DATA_WARNING


def test_clean_questions_and_email_addresses_pass_through():
    model = FakeToolModel([AIMessage(content="ok")])
    result = _agent(model).invoke({"messages": [HumanMessage("Email margaret@example.com her NVDA weight")]})
    assert len(model.seen) == 1
    assert result["messages"][-1].content == "ok"
