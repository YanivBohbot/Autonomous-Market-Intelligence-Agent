from unittest.mock import patch, MagicMock
from app.agent.nodes.grader import grade_documents, GradeDocument


@patch("app.agent.nodes.grader.ChatOpenAI")
def test_keeps_relevant_document(mock_llm_class):
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = GradeDocument(binary_score="yes")
    mock_llm_class.return_value.with_structured_output.return_value = mock_structured

    state = {"question": "What is revenue?", "documents": ["Revenue was $100M"], "messages": []}
    result = grade_documents(state)

    assert result["documents"] == ["Revenue was $100M"]


@patch("app.agent.nodes.grader.ChatOpenAI")
def test_drops_irrelevant_document(mock_llm_class):
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = GradeDocument(binary_score="no")
    mock_llm_class.return_value.with_structured_output.return_value = mock_structured

    state = {"question": "What is revenue?", "documents": ["The sky is blue"], "messages": []}
    result = grade_documents(state)

    assert result["documents"] == []


@patch("app.agent.nodes.grader.ChatOpenAI")
def test_filters_mixed_documents(mock_llm_class):
    mock_structured = MagicMock()
    mock_structured.invoke.side_effect = [
        GradeDocument(binary_score="yes"),
        GradeDocument(binary_score="no"),
        GradeDocument(binary_score="yes"),
    ]
    mock_llm_class.return_value.with_structured_output.return_value = mock_structured

    state = {
        "question": "What is revenue?",
        "documents": ["Revenue doc", "Irrelevant doc", "Another revenue doc"],
        "messages": [],
    }
    result = grade_documents(state)

    assert result["documents"] == ["Revenue doc", "Another revenue doc"]


@patch("app.agent.nodes.grader.ChatOpenAI")
def test_handles_empty_documents(mock_llm_class):
    mock_structured = MagicMock()
    mock_llm_class.return_value.with_structured_output.return_value = mock_structured

    state = {"question": "What is revenue?", "documents": [], "messages": []}
    result = grade_documents(state)

    assert result["documents"] == []
    mock_structured.invoke.assert_not_called()
