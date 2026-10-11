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
        docs = self.base_retriever.invoke(query, config={"callbacks": run_manager.get_child()})
        if not docs:
            return []
        try:
            return list(self.reranker.compress_documents(docs, query))
        except Exception as exc:
            logger.warning("KB_SEARCH: rerank failed, using vector order (%s)", exc)
            return docs[: self.top_n]


class _VectorOrder(BaseDocumentCompressor):
    """Stand-in reranker when PineconeRerank cannot be built: keeps the
    vector store's order, like the rerank-failure fallback."""

    top_n: int

    def compress_documents(
        self, documents: Sequence[Document], query: str, callbacks: Callbacks = None
    ) -> Sequence[Document]:
        return list(documents)[: self.top_n]


@lru_cache(maxsize=16)
def _reranker_for(top_n: int) -> BaseDocumentCompressor:
    # PineconeRerank validates the model with a network call at construction
    # -- build it once per top_n (k is 1..10), not on every search.
    return PineconeRerank(model=RERANK_MODEL, top_n=top_n, pinecone_api_key=settings.PINECONE_API_KEY)


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
        reranker = _reranker_for(k)
    except Exception as exc:
        logger.warning("KB_SEARCH: reranker unavailable, using vector order (%s)", exc)
        reranker = _VectorOrder(top_n=k)
    return RerankingRetriever(base_retriever=base, reranker=reranker, top_n=k)
