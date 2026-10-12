from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import rag_agent as rag_mod
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import build_router_agent
from tests.unit.fake_chat import FakeToolModel

from app.agent.guardrails import SENSITIVE_DATA_WARNING, contains_sensitive_data
from app.agent.guardrails.detection import contains_credit_card, contains_email


def test_contains_sensitive_data_detects_credit_card():
    assert contains_sensitive_data("my card is 4111 1111 1111 1111") is True


def test_contains_sensitive_data_detects_email():
    assert contains_sensitive_data("contact jane.doe@example.com please") is True


def test_contains_sensitive_data_false_for_clean_text():
    assert contains_sensitive_data("what is my portfolio value?") is False


def test_contains_sensitive_data_false_for_empty_or_none():
    assert contains_sensitive_data("") is False
    assert contains_sensitive_data(None) is False


def test_contains_sensitive_data_check_email_false_ignores_email_but_not_credit_card():
    assert contains_sensitive_data("contact jane.doe@example.com please", check_email=False) is False
    assert contains_sensitive_data("my card is 4111 1111 1111 1111", check_email=False) is True


def test_contains_credit_card_and_contains_email_are_independent():
    assert contains_credit_card("my card is 4111 1111 1111 1111") is True
    assert contains_credit_card("contact jane.doe@example.com please") is False
    assert contains_email("contact jane.doe@example.com please") is True
    assert contains_email("my card is 4111 1111 1111 1111") is False


def test_detection_handles_content_block_lists():
    content = [{"type": "text", "text": "my card is 4111 1111 1111 1111"}]
    assert contains_credit_card(content) is True
    assert contains_credit_card([{"type": "image_url", "image_url": {"url": "x"}}]) is False


def test_detection_does_not_call_pii_middleware_hooks():
    import inspect
    import app.agent.guardrails.detection as detection
    assert "before_model" not in inspect.getsource(detection)


def _graph():
    from app.agent.multi_agent import build_multi_agent_app
    return build_multi_agent_app(InMemorySaver())


def _ask(graph, question: str, thread_id: str):
    return graph.invoke({"question": question}, {"configurable": {"thread_id": thread_id}})


def _decides(next_agent: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "id": "rd", "name": "RoutingDecision", "args": {"next": next_agent, "reasoning": "r"}}])


def test_card_is_blocked_before_any_model_call_and_history_keeps_it_masked():
    """The real block_credit_cards guard runs inside the real router agent:
    no model call, the warning ends the turn, and the stored question is the
    masked one (same id), so no later turn sends the raw number anywhere."""
    model = FakeToolModel([])
    with patch.object(supervisor_mod, "router_agent", build_router_agent(model)):
        result = _ask(_graph(), "my card is 4111 1111 1111 1111", "t-guard-1")
    assert model.seen == []
    assert result["messages"][-1].content == SENSITIVE_DATA_WARNING
    assert "4111 1111 1111 1111" not in result["messages"][-2].content
    assert len([m for m in result["messages"] if m.type == "human"]) == 1


def test_clean_question_reaches_the_router_model():
    model = FakeToolModel([_decides("rag_agent")])
    with patch.object(supervisor_mod, "router_agent", build_router_agent(model)),          patch.object(rag_mod, "specialist_model", return_value=FakeToolModel([AIMessage(content="answer")])):
        result = _ask(_graph(), "what is in the Amazon report?", "t-guard-2")
    assert len(model.seen) == 1
    assert result["messages"][-1].content == "answer"


def test_blocked_card_never_reaches_the_router_on_the_next_turn():
    """The raw card message must not stay in history: the router sends the
    whole conversation to OpenAI on every later turn."""
    next_model = FakeToolModel([_decides("rag_agent")])
    with patch.object(rag_mod, "specialist_model", return_value=FakeToolModel([AIMessage(content="ok")])):
        graph = _graph()
        with patch.object(supervisor_mod, "router_agent", build_router_agent(FakeToolModel([]))):
            _ask(graph, "my card is 4111 1111 1111 1111", "t-guard-3")
        with patch.object(supervisor_mod, "router_agent", build_router_agent(next_model)):
            _ask(graph, "what is the price of AAPL?", "t-guard-3")
    sent = " ".join(str(m.content) for m in next_model.seen[0])
    assert "4111 1111 1111 1111" not in sent
    assert "4111111111111111" not in sent
