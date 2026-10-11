import logging
from functools import lru_cache
from typing import Sequence

from langchain_core.callbacks import CallbackManagerForRetrieverRun, Callbacks
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.retrievers import BaseRetriever
from langchain_pinecone import PineconeRerank

from app.core.config import settings
from app.rag.vectorstore import get_vectorstore

logger = logging.getLogger(__name__)

# Cosine-similarity floor below which a chunk is treated as noise rather than
# a real match. Calibrated empirically against this project's real index
# (text-embedding-3-small): on-topic queries against their matching document
# scored 0.53-0.66, off-topic queries scored 0.13-0.14 -- 0.35 sits with wide
# margin in the gap between the two clusters.
RELEVANCE_THRESHOLD_COSINE = 0.35
# as_retriever(search_type="similarity_score_threshold") filters on RELEVANCE
# scores, and PineconeVectorStore maps cosine -> relevance as (cos + 1) / 2
# (_cosine_relevance_score_fn) -- translating keeps exactly the same chunks.
# Never pass the cosine value here directly: 0.35 as a relevance score would
# admit chunks down to cosine -0.3, i.e. almost everything.
RELEVANCE_SCORE_THRESHOLD = (RELEVANCE_THRESHOLD_COSINE + 1) / 2

# Vector similarity ranks number-dense chunks (financial tables) poorly: the
# Tesla "Total revenues ... 22,387 28,236" table ranked #8-9 for revenue
# queries, outside the top 4 the agent sees. Fetch a wider candidate pool and
# rerank it with a cross-encoder -- measured live, bge-reranker-v2-m3 moved
# that table to #1 (pinecone-rerank-v0 did slightly worse on Amazon).
RERANK_CANDIDATES = 20
RERANK_MODEL = "bge-reranker-v2-m3"
# The user wants an answer with its page, not a wall of excerpts: return at
# most MAX_SOURCES sources, each from a different page. The reranker keeps a
# few more (RERANK_TOP_N) so that collapsing same-page chunks still leaves
# MAX_SOURCES distinct pages. No absolute rerank-score floor: measured live,
# the correct passage can score 0.05 on one query and 0.99 on another, so a
# fixed cut-off would drop good answers.
MAX_SOURCES = 2
RERANK_TOP_N = 4


def _drop_duplicate_chunks(docs: list[Document]) -> list[Document]:
    """Keep the first (best-scored) copy of each chunk text. The index can hold
    the same chunk more than once: a PDF ingested by both the bulk CLI (old
    source 'data/x.pdf') and the upload path (source 'x.pdf') gets different
    chunk IDs, and a re-uploaded copy under another filename duplicates it
    again -- without this, results show the same text 2-4 times."""
    seen: set[str] = set()
    unique = []
    for doc in docs:
        key = " ".join(doc.page_content.split())
        if key not in seen:
            seen.add(key)
            unique.append(doc)
    return unique


def _one_per_page(docs: list[Document]) -> list[Document]:
    """Keep the first (best-ranked) chunk of each (filename, page)."""
    seen: set[tuple] = set()
    kept = []
    for doc in docs:
        key = (doc.metadata.get("filename"), doc.metadata.get("page"))
        if key not in seen:
            seen.add(key)
            kept.append(doc)
    return kept


class RerankingRetriever(BaseRetriever):
    """Retriever = candidate retriever (vector store) + document reranker.

    Falls back to candidate order on any reranker failure (quota, network),
    so search never breaks because of the reranker."""

    base_retriever: BaseRetriever
    reranker: BaseDocumentCompressor
    top_n: int

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        docs = _drop_duplicate_chunks(
            self.base_retriever.invoke(query, config={"callbacks": run_manager.get_child()})
        )
        if not docs:
            return []
        try:
            ranked = list(self.reranker.compress_documents(docs, query))
        except Exception as exc:
            logger.warning("KB_SEARCH: rerank failed, using vector order (%s)", exc)
            return _one_per_page(docs)[: self.top_n]
        if not ranked:
            # Non-empty candidates can't legitimately rerank to nothing --
            # treat it as a reranker failure, not as "no relevant results".
            logger.warning("KB_SEARCH: rerank returned nothing, using vector order")
            return _one_per_page(docs)[: self.top_n]
        return _one_per_page(ranked)[: self.top_n]


class CappedPineconeRerank(PineconeRerank):
    """PineconeRerank with two fixes for this retriever:

    - caps top_n at the number of candidates (the pre-refactor code sent
      min(top_n, len(docs)); PineconeRerank always sends its own top_n);
    - surfaces failures: PineconeRerank.rerank() catches every API error,
      logs it and returns [] -- raise instead, so RerankingRetriever falls
      back to vector order rather than reporting "no relevant results".
    """

    def compress_documents(
        self, documents: Sequence[Document], query: str, callbacks: Callbacks = None
    ) -> Sequence[Document]:
        if not documents:
            return []
        results = self.rerank(documents=documents, query=query, top_n=min(self.top_n, len(documents)))
        if not results:
            raise RuntimeError("Pinecone rerank returned no results (see 'Rerank error' log)")
        ranked = []
        for res in results:
            index = res.get("index")
            if index is not None and 0 <= index < len(documents):
                doc = documents[index]
                ranked.append(
                    Document(page_content=doc.page_content, metadata={**doc.metadata, "relevance_score": res["score"]})
                )
        return ranked


class _VectorOrder(BaseDocumentCompressor):
    """Stand-in reranker when PineconeRerank cannot be built: keeps the
    vector store's order, like the rerank-failure fallback."""

    top_n: int

    def compress_documents(
        self, documents: Sequence[Document], query: str, callbacks: Callbacks = None
    ) -> Sequence[Document]:
        return list(documents)[: self.top_n]


@lru_cache(maxsize=1)
def _reranker_for() -> BaseDocumentCompressor:
    # CappedPineconeRerank (a PineconeRerank) validates the model with a network call at construction
    # -- build it once, not on every search.
    return CappedPineconeRerank(model=RERANK_MODEL, top_n=RERANK_TOP_N, pinecone_api_key=settings.PINECONE_API_KEY)


def build_kb_retriever(k: int, metadata_filter: dict | None) -> RerankingRetriever:
    """Knowledge-base retriever for one tool call (k and filter vary per call;
    construction is cheap: the vector store and rerankers are cached)."""
    search_kwargs: dict = {"k": RERANK_CANDIDATES, "score_threshold": RELEVANCE_SCORE_THRESHOLD}
    if metadata_filter is not None:
        search_kwargs["filter"] = metadata_filter
    base = get_vectorstore().as_retriever(
        search_type="similarity_score_threshold", search_kwargs=search_kwargs
    )
    try:
        reranker = _reranker_for()
    except Exception as exc:
        logger.warning("KB_SEARCH: reranker unavailable, using vector order (%s)", exc)
        reranker = _VectorOrder(top_n=RERANK_TOP_N)
    return RerankingRetriever(base_retriever=base, reranker=reranker, top_n=min(k, MAX_SOURCES))
