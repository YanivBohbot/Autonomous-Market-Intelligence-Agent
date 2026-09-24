from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from langchain_core.documents import Document

from app.agent.tools import knowledge_base as kb_mod
from app.agent.tools.knowledge_base import search_knowledge_base_tool, web_search_tool


@pytest.fixture(autouse=True)
def _identity_reranker():
    """Keep tests offline: the reranker returns candidates in vector order
    unless a test installs its own ordering."""
    pc = MagicMock()
    pc.inference.rerank.side_effect = lambda **kw: SimpleNamespace(
        data=[SimpleNamespace(index=i) for i in range(min(kw["top_n"], len(kw["documents"])))]
    )
    with patch.object(kb_mod, "_get_pinecone", return_value=pc):
        yield pc


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
    assert "[Source: Amazon-2024-Annual-Report.pdf, page 13]" in result
    assert "Revenue was $100M" in result


def test_search_cites_float_page_metadata_as_one_based_integer():
    """Pinecone returns numeric metadata as floats (35.0) and PyPDFLoader
    pages are 0-based — cite the page number a reader sees in the PDF."""
    docs = [
        (Document(page_content="Net sales $637,959M", metadata={"filename": "Amazon-2024-Annual-Report.pdf", "page": 35.0}), 0.62),
    ]
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_vectorstore(docs)):
        result = search_knowledge_base_tool.invoke({"query": "net sales"})
    assert "[Source: Amazon-2024-Annual-Report.pdf, page 36]" in result


def test_search_cites_unknown_page_when_metadata_missing():
    docs = [(Document(page_content="text", metadata={"filename": "annual-report.pdf"}), 0.62)]
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_vectorstore(docs)):
        result = search_knowledge_base_tool.invoke({"query": "q"})
    assert "[Source: annual-report.pdf, page ?]" in result


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
        "deliveries", k=kb_mod._RERANK_CANDIDATES, filter={"filename": {"$in": ["TSLA-Q2-2026-Update.pdf"]}}
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


def test_ingested_documents_come_from_manifest_not_data_dir(tmp_path):
    """Regression: source_filter used to list ./data/*.pdf at query time, but
    the AgentCore image only ships app/ — no PDFs — so every source_filter
    returned "no match" in prod. The list now comes from a manifest written
    by ingest.py and shipped inside app/."""
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text('["TSLA-Q2-2026-Update.pdf", "Amazon-2024-Annual-Report.pdf"]', encoding="utf-8")
    assert kb_mod._list_ingested_pdfs(manifest) == ["Amazon-2024-Annual-Report.pdf", "TSLA-Q2-2026-Update.pdf"]


def test_ingested_documents_empty_when_manifest_missing(tmp_path):
    assert kb_mod._list_ingested_pdfs(tmp_path / "missing.json") == []


def test_default_manifest_ships_inside_app_package():
    from pathlib import Path

    app_dir = Path(kb_mod.__file__).resolve().parents[2]
    assert app_dir.name == "app"
    assert app_dir in kb_mod.KB_MANIFEST_PATH.resolve().parents


def _doc(text, score, page=1):
    return (Document(page_content=text, metadata={"filename": "Tesla-TSLA-Q2-2026-Update.pdf", "page": page}), score)


def test_search_returns_top_k_in_reranker_order(_identity_reranker):
    """Regression: the Tesla revenue table ("Total revenues ... 22,387 28,236")
    ranked #8-9 by vector similarity, outside the top 4, so the agent never
    saw it. bge-reranker-v2-m3 moved it to #1 in live measurements."""
    docs = [_doc(f"narrative chunk {i}", 0.60 - i * 0.01, page=i) for i in range(7)] + [_doc("Total revenues 22,387 28,236", 0.55, page=27)]
    _identity_reranker.inference.rerank.side_effect = lambda **kw: SimpleNamespace(
        data=[SimpleNamespace(index=7), SimpleNamespace(index=0), SimpleNamespace(index=1), SimpleNamespace(index=2)]
    )
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_vectorstore(docs)):
        result = search_knowledge_base_tool.invoke({"query": "Tesla total revenue Q1 2026", "k": 4})
    chunks = result.split("\n\n")
    assert len(chunks) == 4
    assert "Total revenues 22,387 28,236" in chunks[0]
    assert "page 28" in chunks[0]
    kwargs = _identity_reranker.inference.rerank.call_args.kwargs
    assert kwargs["model"] == "bge-reranker-v2-m3"
    assert kwargs["top_n"] == 4


def test_search_falls_back_to_vector_order_when_rerank_fails(_identity_reranker):
    docs = [_doc("first by vector", 0.6), _doc("second by vector", 0.5)]
    _identity_reranker.inference.rerank.side_effect = RuntimeError("rerank quota exceeded")
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_vectorstore(docs)):
        result = search_knowledge_base_tool.invoke({"query": "q", "k": 1})
    assert "first by vector" in result
    assert "second by vector" not in result


def test_rerank_only_sees_chunks_above_relevance_threshold(_identity_reranker):
    docs = [_doc("on topic", 0.6), _doc("off topic noise", 0.14)]
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_vectorstore(docs)):
        result = search_knowledge_base_tool.invoke({"query": "q"})
    assert _identity_reranker.inference.rerank.call_args.kwargs["documents"] == ["on topic"]
    assert "off topic noise" not in result


def test_rerank_skipped_when_nothing_passes_threshold(_identity_reranker):
    docs = [_doc("noise", 0.1)]
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_vectorstore(docs)):
        result = search_knowledge_base_tool.invoke({"query": "q"})
    _identity_reranker.inference.rerank.assert_not_called()
    assert result == "No relevant results found in the knowledge base for this query."
