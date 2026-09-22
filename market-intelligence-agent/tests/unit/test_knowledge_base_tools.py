import os
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.agent.tools import knowledge_base as kb_mod
from app.agent.tools.knowledge_base import search_knowledge_base_tool, web_search_tool


def _mock_retriever(docs):
    retriever = MagicMock()
    retriever.invoke.return_value = docs
    vectorstore = MagicMock()
    vectorstore.as_retriever.return_value = retriever
    return vectorstore


def test_search_returns_formatted_chunks_with_source_and_page():
    docs = [
        Document(page_content="Revenue was $100M", metadata={"source": "data/Amazon-2024-Annual-Report.pdf", "page": 12}),
    ]
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_retriever(docs)):
        result = search_knowledge_base_tool.invoke({"query": "revenue"})
    assert "[Source: Amazon-2024-Annual-Report.pdf, page 12]" in result
    assert "Revenue was $100M" in result


def test_search_returns_explicit_message_on_empty_results():
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_retriever([])):
        result = search_knowledge_base_tool.invoke({"query": "nonexistent topic"})
    assert result == "No relevant results found in the knowledge base for this query."


def test_search_returns_explicit_message_on_vectorstore_error():
    vectorstore = MagicMock()
    vectorstore.as_retriever.side_effect = RuntimeError("Pinecone unreachable")
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
    docs = [Document(page_content="Tesla delivered 500k vehicles", metadata={"source": "data/TSLA-Q2-2026-Update.pdf", "page": 3})]
    vectorstore = _mock_retriever(docs)
    expected_path = os.path.join("data", "TSLA-Q2-2026-Update.pdf")
    with patch.object(kb_mod, "_get_vectorstore", return_value=vectorstore), \
         patch.object(kb_mod, "_list_ingested_pdfs", return_value=["Amazon-2024-Annual-Report.pdf", "TSLA-Q2-2026-Update.pdf"]):
        result = search_knowledge_base_tool.invoke({"query": "deliveries", "source_filter": "TSLA"})
    vectorstore.as_retriever.assert_called_once_with(
        search_kwargs={"k": 4, "filter": {"source": {"$in": [expected_path]}}}
    )
    assert "Tesla delivered 500k vehicles" in result


def test_web_search_formats_results_with_source_url():
    fake_response = {"results": [{"url": "https://example.com/news", "content": "Market news content"}]}
    with patch.object(kb_mod, "_tavily") as mock_tavily:
        mock_tavily.search.return_value = fake_response
        result = web_search_tool.invoke({"query": "market news"})
    assert "[SOURCE WEB: https://example.com/news]" in result
    assert "Market news content" in result
