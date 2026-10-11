from types import SimpleNamespace
from unittest.mock import patch

import pytest

from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.retrievers import BaseRetriever

from app.agent.tools import knowledge_base as kb_mod
from app.agent.tools.knowledge_base import search_knowledge_base_tool, web_search_tool
from app.rag import retriever as rag_retriever


class _FakeStore:
    """Mimics PineconeVectorStore.as_retriever(similarity_score_threshold):
    keeps the top-k candidates whose relevance (cos + 1) / 2 passes the
    threshold, exactly as langchain_pinecone maps cosine scores."""

    def __init__(self, results_with_cosine=None, error=None):
        self.results = results_with_cosine or []
        self.error = error
        self.search_kwargs = None

    def as_retriever(self, search_type, search_kwargs):
        assert search_type == "similarity_score_threshold"
        self.search_kwargs = search_kwargs
        store = self

        class _R(BaseRetriever):
            def _get_relevant_documents(self, query, *, run_manager):
                if store.error:
                    raise store.error
                threshold = search_kwargs["score_threshold"]
                return [d for d, cos in store.results[: search_kwargs["k"]] if (cos + 1) / 2 >= threshold]

        return _R()


class _Reranker(BaseDocumentCompressor):
    top_n: int = 4
    order: list[int] | None = None
    error: object = None  # an Exception instance to raise, if set
    seen: list[str] | None = None

    def compress_documents(self, documents, query, callbacks=None):
        object.__setattr__(self, "seen", [d.page_content for d in documents])
        if self.error:
            raise self.error
        idx = self.order if self.order is not None else list(range(len(documents)))
        return [documents[i] for i in idx][: self.top_n]


@pytest.fixture(autouse=True)
def rag():
    """Offline seams on app.rag.retriever: a configurable fake vector store and
    a reranker that keeps vector order unless a test sets `order`/`error`."""
    state = SimpleNamespace(store=_FakeStore(), reranker=None, rerank_kwargs=None, order=None, error=None)

    def fake_rerank(**kw):
        state.rerank_kwargs = kw
        state.reranker = _Reranker(top_n=kw["top_n"], order=state.order, error=state.error)
        return state.reranker

    rag_retriever._reranker_for.cache_clear()
    with (
        patch.object(rag_retriever, "get_vectorstore", side_effect=lambda: state.store),
        patch.object(rag_retriever, "PineconeRerank", side_effect=fake_rerank),
    ):
        yield state
    rag_retriever._reranker_for.cache_clear()


def test_search_returns_formatted_chunks_with_source_and_page(rag):
    rag.store = _FakeStore([
        (Document(page_content="Revenue was $100M", metadata={"source": "data/Amazon-2024-Annual-Report.pdf", "page": 12}), 0.62),
    ])
    result = search_knowledge_base_tool.invoke({"query": "revenue"})
    assert "[Source: Amazon-2024-Annual-Report.pdf, page 13]" in result
    assert "Revenue was $100M" in result


def test_search_cites_float_page_metadata_as_one_based_integer(rag):
    """Pinecone returns numeric metadata as floats (35.0) and PyPDFLoader
    pages are 0-based — cite the page number a reader sees in the PDF."""
    rag.store = _FakeStore([
        (Document(page_content="Net sales $637,959M", metadata={"filename": "Amazon-2024-Annual-Report.pdf", "page": 35.0}), 0.62),
    ])
    result = search_knowledge_base_tool.invoke({"query": "net sales"})
    assert "[Source: Amazon-2024-Annual-Report.pdf, page 36]" in result


def test_search_cites_unknown_page_when_metadata_missing(rag):
    rag.store = _FakeStore([(Document(page_content="text", metadata={"filename": "annual-report.pdf"}), 0.62)])
    result = search_knowledge_base_tool.invoke({"query": "q"})
    assert "[Source: annual-report.pdf, page ?]" in result


def test_search_returns_explicit_message_on_empty_results(rag):
    rag.store = _FakeStore([])
    result = search_knowledge_base_tool.invoke({"query": "nonexistent topic"})
    assert result == "No relevant results found in the knowledge base for this query."


def test_search_returns_explicit_message_on_vectorstore_error(rag):
    rag.store = _FakeStore(error=RuntimeError("Pinecone unreachable"))
    result = search_knowledge_base_tool.invoke({"query": "revenue"})
    assert "Knowledge base search failed" in result
    assert "Pinecone unreachable" in result


def test_search_with_unmatched_source_filter_lists_available_docs():
    with patch.object(kb_mod, "_list_ingested_pdfs", return_value=["Amazon-2024-Annual-Report.pdf", "TSLA-Q2-2026-Update.pdf"]):
        result = search_knowledge_base_tool.invoke({"query": "revenue", "source_filter": "NoSuchCompany"})
    assert "No ingested document matches source_filter='NoSuchCompany'" in result
    assert "Amazon-2024-Annual-Report.pdf" in result
    assert "TSLA-Q2-2026-Update.pdf" in result


def test_search_with_matched_source_filter_builds_pinecone_filter(rag):
    rag.store = _FakeStore([(Document(page_content="Tesla delivered 500k vehicles", metadata={"source": "data/TSLA-Q2-2026-Update.pdf", "page": 3, "filename": "TSLA-Q2-2026-Update.pdf"}), 0.6)])
    with patch.object(kb_mod, "_list_ingested_pdfs", return_value=["Amazon-2024-Annual-Report.pdf", "TSLA-Q2-2026-Update.pdf"]):
        result = search_knowledge_base_tool.invoke({"query": "deliveries", "source_filter": "TSLA"})
    assert rag.store.search_kwargs == {
        "k": 20,
        "score_threshold": rag_retriever.RELEVANCE_SCORE_THRESHOLD,
        "filter": {"filename": {"$in": ["TSLA-Q2-2026-Update.pdf"]}},
    }
    assert "Tesla delivered 500k vehicles" in result


def test_search_filters_out_low_relevance_chunks(rag):
    """Calibrated empirically (see RELEVANCE_THRESHOLD_COSINE): on-topic real
    queries scored 0.53-0.66, off-topic scored 0.13-0.14 against this
    project's real index."""
    rag.store = _FakeStore([
        (Document(page_content="Amazon 2024 revenue was $638B", metadata={"filename": "Amazon-2024-Annual-Report.pdf", "page": 1}), 0.66),
        (Document(page_content="unrelated cybercab production note", metadata={"filename": "TSLA-Q2-2026-Update.pdf", "page": 16}), 0.14),
    ])
    result = search_knowledge_base_tool.invoke({"query": "Amazon revenue"})
    assert "Amazon 2024 revenue was $638B" in result
    assert "unrelated cybercab production note" not in result


def test_search_returns_no_results_message_when_all_below_threshold(rag):
    rag.store = _FakeStore([
        (Document(page_content="irrelevant chunk one", metadata={"filename": "TSLA-Q2-2026-Update.pdf", "page": 16}), 0.14),
        (Document(page_content="irrelevant chunk two", metadata={"filename": "annual-report.pdf", "page": 44}), 0.13),
    ])
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


def test_search_returns_top_k_in_reranker_order(rag):
    """Regression: the Tesla revenue table ("Total revenues ... 22,387 28,236")
    ranked #8-9 by vector similarity, outside the top 4, so the agent never
    saw it. bge-reranker-v2-m3 moved it to #1 in live measurements."""
    rag.store = _FakeStore([_doc(f"narrative chunk {i}", 0.60 - i * 0.01, page=i) for i in range(7)] + [_doc("Total revenues 22,387 28,236", 0.55, page=27)])
    rag.order = [7, 0, 1, 2]
    result = search_knowledge_base_tool.invoke({"query": "Tesla total revenue Q1 2026", "k": 4})
    chunks = result.split("\n\n")
    assert len(chunks) == 4
    assert "Total revenues 22,387 28,236" in chunks[0]
    assert "page 28" in chunks[0]
    assert rag.rerank_kwargs["model"] == "bge-reranker-v2-m3"
    assert rag.rerank_kwargs["top_n"] == 4


def test_search_falls_back_to_vector_order_when_rerank_fails(rag):
    rag.store = _FakeStore([_doc("first by vector", 0.6), _doc("second by vector", 0.5)])
    rag.error = RuntimeError("rerank quota exceeded")
    result = search_knowledge_base_tool.invoke({"query": "q", "k": 1})
    assert "first by vector" in result
    assert "second by vector" not in result


def test_rerank_only_sees_chunks_above_relevance_threshold(rag):
    rag.store = _FakeStore([_doc("on topic", 0.6), _doc("off topic noise", 0.14)])
    result = search_knowledge_base_tool.invoke({"query": "q"})
    assert rag.reranker.seen == ["on topic"]
    assert "off topic noise" not in result


def test_rerank_skipped_when_nothing_passes_threshold(rag):
    rag.store = _FakeStore([_doc("noise", 0.1)])
    result = search_knowledge_base_tool.invoke({"query": "q"})
    assert rag.reranker is None or rag.reranker.seen is None
    assert result == "No relevant results found in the knowledge base for this query."
