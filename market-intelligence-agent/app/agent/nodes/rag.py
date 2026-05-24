import logging
from functools import lru_cache
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from app.core.config import settings
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_vectorstore() -> PineconeVectorStore:
    """Lazy: PineconeVectorStore.__init__ makes a network call to resolve the
    index host, so we defer it past module import to keep tests offline-safe."""
    embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
    return PineconeVectorStore(
        index_name=settings.PINECONE_INDEX_NAME, embedding=embeddings
    )


def retrieve_internal_documentation(state: AgentState) -> dict:
    logger.info("RAG: Starting internal document search")
    try:
        docs = _get_vectorstore().similarity_search(state["question"], k=3)
    except Exception as exc:
        # Index not provisioned / Pinecone unreachable: treat as 0 hits so the
        # grader routes to web_search instead of crashing the request. Logged
        # at warning so a missing index is visible but not fatal.
        logger.warning("RAG: vectorstore query failed (%s); returning 0 docs", exc)
        return {"documents": []}
    content = [f"[INTERNAL Resource] {d.page_content}" for d in docs]
    logger.info("RAG: Retrieved %d chunks", len(content))
    return {"documents": content}
