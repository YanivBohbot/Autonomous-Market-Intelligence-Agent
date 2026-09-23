from unittest.mock import patch

from langchain_core.messages import AIMessage

from app.agent.nodes import generate as generate_mod
from app.agent.nodes.generate import generate_answer


def test_generate_answer_does_not_require_documents_key():
    state = {"question": "What is Amazon's revenue?", "messages": []}
    with patch.object(generate_mod, "_llm_with_tools") as mock_llm:
        mock_llm.invoke.return_value = AIMessage(content="Answer")
        result = generate_answer(state)
    assert result["messages"][0].content == "Answer"


def test_generate_answer_does_not_inject_documents_context():
    state = {"question": "What is Amazon's revenue?", "messages": []}
    with patch.object(generate_mod, "_llm_with_tools") as mock_llm:
        mock_llm.invoke.return_value = AIMessage(content="Answer")
        generate_answer(state)
    sent_messages = mock_llm.invoke.call_args[0][0]
    assert not any(
        "Reference material retrieved for this turn" in getattr(m, "content", "")
        for m in sent_messages
    )


def test_generate_answer_system_prompt_includes_todays_date():
    """Regression: without the current date the LLM injected its training-era
    year into web_search queries ("most recent FIFA World Cup final winner
    2023") and answered time-sensitive questions with stale results."""
    from datetime import date

    state = {"question": "latest news?", "messages": []}
    with patch.object(generate_mod, "_llm_with_tools") as mock_llm:
        mock_llm.invoke.return_value = AIMessage(content="Answer")
        generate_answer(state)
    system_prompt = mock_llm.invoke.call_args[0][0][0].content
    assert f"Today's date is {date.today().isoformat()}" in system_prompt
