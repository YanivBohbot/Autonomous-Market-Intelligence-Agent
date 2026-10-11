from typing import Sequence

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.retrievers import BaseRetriever

from app.rag import retriever as r


class _ListRetriever(BaseRetriever):
    docs: list[Document]

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun):
        return list(self.docs)


class _ReverseReranker(BaseDocumentCompressor):
    top_n: int = 2
    calls: int = 0

    def compress_documents(self, documents: Sequence[Document], query: str, callbacks=None):
        object.__setattr__(self, "calls", self.calls + 1)
        return list(reversed(documents))[: self.top_n]


class _FailingReranker(BaseDocumentCompressor):
    def compress_documents(self, documents, query, callbacks=None):
        raise RuntimeError("rerank quota exceeded")


@pytest.fixture(autouse=True)
def _fresh_reranker_cache():
    r._reranker_for.cache_clear()
    yield
    r._reranker_for.cache_clear()


def _docs(*texts):
    return [Document(page_content=t, metadata={"filename": "x.pdf", "page": i}) for i, t in enumerate(texts)]


def test_score_threshold_is_the_relevance_translation_of_cosine_035():
    assert r.RELEVANCE_THRESHOLD_COSINE == 0.35
    assert r.RELEVANCE_SCORE_THRESHOLD == pytest.approx((0.35 + 1) / 2)


def test_reranking_retriever_returns_reranked_docs():
    rr = r.RerankingRetriever(base_retriever=_ListRetriever(docs=_docs("a", "b", "c")), reranker=_ReverseReranker(top_n=2), top_n=2)
    assert [d.page_content for d in rr.invoke("q")] == ["c", "b"]


def test_reranking_retriever_falls_back_to_vector_order_when_reranker_fails():
    rr = r.RerankingRetriever(base_retriever=_ListRetriever(docs=_docs("a", "b", "c")), reranker=_FailingReranker(), top_n=2)
    assert [d.page_content for d in rr.invoke("q")] == ["a", "b"]


def test_reranking_retriever_skips_reranker_when_no_candidates():
    reranker = _ReverseReranker()
    rr = r.RerankingRetriever(base_retriever=_ListRetriever(docs=[]), reranker=reranker, top_n=2)
    assert rr.invoke("q") == []
    assert reranker.calls == 0


class _FakeStore:
    def __init__(self):
        self.kwargs = None

    def as_retriever(self, **kwargs):
        self.kwargs = kwargs
        return _ListRetriever(docs=[])


def test_build_kb_retriever_configures_threshold_candidates_filter_and_rerank(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(r, "get_vectorstore", lambda: store)
    built = {}

    def fake_rerank(**kw):
        built["kw"] = kw
        return _ReverseReranker(top_n=kw["top_n"])

    monkeypatch.setattr(r, "PineconeRerank", fake_rerank)

    rr = r.build_kb_retriever(4, {"filename": {"$in": ["a.pdf"]}})

    assert store.kwargs == {
        "search_type": "similarity_score_threshold",
        "search_kwargs": {"k": 20, "score_threshold": r.RELEVANCE_SCORE_THRESHOLD, "filter": {"filename": {"$in": ["a.pdf"]}}},
    }
    assert built["kw"]["model"] == "bge-reranker-v2-m3"
    assert built["kw"]["top_n"] == 4
    assert rr.top_n == 4


def test_build_kb_retriever_omits_filter_when_none(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(r, "get_vectorstore", lambda: store)
    monkeypatch.setattr(r, "PineconeRerank", lambda **kw: _ReverseReranker(top_n=kw["top_n"]))
    r.build_kb_retriever(4, None)
    assert "filter" not in store.kwargs["search_kwargs"]


def test_build_kb_retriever_falls_back_to_vector_order_when_reranker_cannot_be_built(monkeypatch):
    """PineconeRerank validates its model with a network call at construction;
    if that fails, search must still work (vector order), as when the rerank
    call itself fails."""
    monkeypatch.setattr(r, "get_vectorstore", lambda: _FakeStoreWith(_docs("a", "b", "c")))

    def broken(**kw):
        raise RuntimeError("pinecone unreachable")

    monkeypatch.setattr(r, "PineconeRerank", broken)
    assert [d.page_content for d in r.build_kb_retriever(2, None).invoke("q")] == ["a", "b"]


def test_reranker_is_built_once_per_top_n(monkeypatch):
    monkeypatch.setattr(r, "get_vectorstore", lambda: _FakeStore())
    built = []
    monkeypatch.setattr(r, "PineconeRerank", lambda **kw: built.append(kw) or _ReverseReranker(top_n=kw["top_n"]))
    r.build_kb_retriever(4, None)
    r.build_kb_retriever(4, None)
    r.build_kb_retriever(2, None)
    assert [kw["top_n"] for kw in built] == [4, 2]


class _FakeStoreWith:
    def __init__(self, docs):
        self.docs = docs

    def as_retriever(self, **kwargs):
        return _ListRetriever(docs=self.docs)
