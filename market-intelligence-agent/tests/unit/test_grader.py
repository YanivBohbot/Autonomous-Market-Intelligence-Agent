from unittest.mock import patch, MagicMock
from app.agent.nodes import grader as grader_mod
from app.agent.nodes.grader import grade_documents, GradeDocument


def test_keeps_relevant_document():
    with patch.object(grader_mod, "_grader") as mock:
        mock.invoke.return_value = GradeDocument(binary_score="yes")
        state = {"question": "What is revenue?", "documents": ["Revenue was $100M"], "messages": []}
        result = grade_documents(state)
    assert result["documents"] == ["Revenue was $100M"]


def test_drops_irrelevant_document():
    with patch.object(grader_mod, "_grader") as mock:
        mock.invoke.return_value = GradeDocument(binary_score="no")
        state = {"question": "What is revenue?", "documents": ["The sky is blue"], "messages": []}
        result = grade_documents(state)
    assert result["documents"] == []


def test_filters_mixed_documents():
    with patch.object(grader_mod, "_grader") as mock:
        mock.invoke.side_effect = [
            GradeDocument(binary_score="yes"),
            GradeDocument(binary_score="no"),
            GradeDocument(binary_score="yes"),
        ]
        state = {
            "question": "What is revenue?",
            "documents": ["Revenue doc", "Irrelevant doc", "Another revenue doc"],
            "messages": [],
        }
        result = grade_documents(state)
    assert result["documents"] == ["Revenue doc", "Another revenue doc"]


def test_handles_empty_documents():
    with patch.object(grader_mod, "_grader") as mock:
        state = {"question": "What is revenue?", "documents": [], "messages": []}
        result = grade_documents(state)
    assert result["documents"] == []
    mock.invoke.assert_not_called()
