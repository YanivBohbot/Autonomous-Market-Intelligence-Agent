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
    docs = _get_vectorstore().similarity_search(state["question"], k=3)
    content = [f"[INTERNAL Resource] {d.page_content}" for d in docs]
    logger.info("RAG: Retrieved %d chunks", len(content))
    return {"documents": content}
