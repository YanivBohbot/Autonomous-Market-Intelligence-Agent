from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.agent.tools import knowledge_base as kb_mod
from app.agent.tools.knowledge_base import search_knowledge_base_tool, web_search_tool


def _mock_vectorstore(results_with_scores):
    vectorstore = MagicMock()
    vectorstore.similarity_search_with_score.return_value = results_with_scores
    return vectorstore


def test_search_returns_formatted_chunks_with_source_and_page():
    docs = [
        (Document(page_content="Revenue was $100M", metadata={"source": "data/Amazon-2024-Annual-Report.pdf", "page": 12}), 0.62),
    ]
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_vectorstore(docs)):
        result = search_knowledge_base_tool.invoke({"query": "revenue"})
    assert "[Source: Amazon-2024-Annual-Report.pdf, page 12]" in result
    assert "Revenue was $100M" in result


def test_search_returns_explicit_message_on_empty_results():
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_vectorstore([])):
        result = search_knowledge_base_tool.invoke({"query": "nonexistent topic"})
    assert result == "No relevant results found in the knowledge base for this query."


def test_search_returns_explicit_message_on_vectorstore_error():
    vectorstore = MagicMock()
    vectorstore.similarity_search_with_score.side_effect = RuntimeError("Pinecone unreachable")
    with patch.object(kb_mod, "_get_vectorstore", return_value=vectorstore):
        result = search_knowledge_base_tool.invoke({"query": "revenue"})
    assert "Knowledge base search failed" in result
    assert "Pinecone unreachable" in result


def test_search_with_unmatched_source_filter_lists_available_docs():
    with patch.object(kb_mod, "_list_ingested_pdfs", return_value=["Amazon-2024-Annual-Report.pdf", "TSLA-Q2-2026-Update.pdf"]):
        result = search_knowledge_base_tool.invoke({"query": "revenue", "source_filter": "NoSuchCompany"})
    assert "No ingested document matches source_filter='NoSuchCompany'" in result
    assert "Amazon-2024-Annual-Report.pdf" in result
    assert "TSLA-Q2-2026-Update.pdf" in result


def test_search_with_matched_source_filter_builds_pinecone_filter():
    docs = [(Document(page_content="Tesla delivered 500k vehicles", metadata={"source": "data/TSLA-Q2-2026-Update.pdf", "page": 3, "filename": "TSLA-Q2-2026-Update.pdf"}), 0.6)]
    vectorstore = _mock_vectorstore(docs)
    with patch.object(kb_mod, "_get_vectorstore", return_value=vectorstore), \
         patch.object(kb_mod, "_list_ingested_pdfs", return_value=["Amazon-2024-Annual-Report.pdf", "TSLA-Q2-2026-Update.pdf"]):
        result = search_knowledge_base_tool.invoke({"query": "deliveries", "source_filter": "TSLA"})
    vectorstore.similarity_search_with_score.assert_called_once_with(
        "deliveries", k=4, filter={"filename": {"$in": ["TSLA-Q2-2026-Update.pdf"]}}
    )
    assert "Tesla delivered 500k vehicles" in result


def test_search_filters_out_low_relevance_chunks():
    """Calibrated empirically (see _RELEVANCE_THRESHOLD docstring): on-topic
    real queries scored 0.53-0.66, off-topic scored 0.13-0.14 against this
    project's real index."""
    docs = [
        (Document(page_content="Amazon 2024 revenue was $638B", metadata={"filename": "Amazon-2024-Annual-Report.pdf", "page": 1}), 0.66),
        (Document(page_content="unrelated cybercab production note", metadata={"filename": "TSLA-Q2-2026-Update.pdf", "page": 16}), 0.14),
    ]
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_vectorstore(docs)):
        result = search_knowledge_base_tool.invoke({"query": "Amazon revenue"})
    assert "Amazon 2024 revenue was $638B" in result
    assert "unrelated cybercab production note" not in result


def test_search_returns_no_results_message_when_all_below_threshold():
    docs = [
        (Document(page_content="irrelevant chunk one", metadata={"filename": "TSLA-Q2-2026-Update.pdf", "page": 16}), 0.14),
        (Document(page_content="irrelevant chunk two", metadata={"filename": "annual-report.pdf", "page": 44}), 0.13),
    ]
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_vectorstore(docs)):
        result = search_knowledge_base_tool.invoke({"query": "best chocolate cake recipe"})
    assert result == "No relevant results found in the knowledge base for this query."


def test_web_search_formats_results_with_source_url():
    fake_response = {"results": [{"url": "https://example.com/news", "content": "Market news content"}]}
    with patch.object(kb_mod, "_tavily") as mock_tavily:
        mock_tavily.search.return_value = fake_response
        result = web_search_tool.invoke({"query": "market news"})
    assert "[SOURCE WEB: https://example.com/news]" in result
    assert "Market news content" in result
