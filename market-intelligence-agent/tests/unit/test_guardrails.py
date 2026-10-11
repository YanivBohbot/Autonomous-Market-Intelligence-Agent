from unittest.mock import patch

import pytest

from langgraph.checkpoint.memory import InMemorySaver

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


class _RouterReached(Exception):
    """Raised by the mocked supervisor router: proves the LLM router was
    reached without running any specialist (which would call a real model)."""


def _graph():
    from app.agent.multi_agent import build_multi_agent_app
    return build_multi_agent_app(InMemorySaver())


def _ask(graph, question: str, thread_id: str):
    return graph.invoke({"question": question}, {"configurable": {"thread_id": thread_id}})


def test_input_guard_blocks_card_before_the_supervisor_llm_is_called():
    import app.agent.multi_agent.supervisor as supervisor_mod
    with patch.object(supervisor_mod, "_router") as router_mock:
        router_mock.invoke.side_effect = _RouterReached
        result = _ask(_graph(), "my card is 4111 1111 1111 1111", "t-guard-1")
    router_mock.invoke.assert_not_called()
    assert result["messages"][-1].content == SENSITIVE_DATA_WARNING


def test_input_guard_lets_clean_questions_reach_the_supervisor():
    import app.agent.multi_agent.supervisor as supervisor_mod
    with patch.object(supervisor_mod, "_router") as router_mock:
        router_mock.invoke.side_effect = _RouterReached
        with pytest.raises(_RouterReached):
            _ask(_graph(), "what is the price of AAPL?", "t-guard-2")
    assert router_mock.invoke.called  # RetryPolicy re-runs supervisor on error


def test_clean_turn_after_blocked_turn_reaches_supervisor():
    import app.agent.multi_agent.supervisor as supervisor_mod
    with patch.object(supervisor_mod, "_router") as router_mock:
        router_mock.invoke.side_effect = _RouterReached
        graph = _graph()
        _ask(graph, "my card is 4111 1111 1111 1111", "t-guard-3")
        router_mock.invoke.assert_not_called()
        with pytest.raises(_RouterReached):
            _ask(graph, "what is the price of AAPL?", "t-guard-3")
    assert router_mock.invoke.called  # RetryPolicy re-runs supervisor on error


def test_blocked_card_never_reaches_the_router_on_the_next_turn():
    """The raw card message must not stay in history: the supervisor router
    sends the whole conversation to OpenAI on every later turn."""
    import app.agent.multi_agent.supervisor as supervisor_mod
    with patch.object(supervisor_mod, "_router") as router_mock:
        router_mock.invoke.side_effect = _RouterReached
        graph = _graph()
        _ask(graph, "my card is 4111 1111 1111 1111", "t-guard-4")
        with pytest.raises(_RouterReached):
            _ask(graph, "what is the price of AAPL?", "t-guard-4")
    sent = " ".join(str(m.content) for m in router_mock.invoke.call_args.args[0])
    assert "4111 1111 1111 1111" not in sent
    assert "4111111111111111" not in sent
