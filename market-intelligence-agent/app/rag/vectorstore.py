from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

from app.core.config import settings


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def get_vectorstore() -> PineconeVectorStore:
    """The single Vector Store instance used by ingestion and retrieval.
    Lazy: PineconeVectorStore.__init__ makes a network call to resolve the
    index host, so it is deferred past module import (offline-safe tests)."""
    return PineconeVectorStore(index_name=settings.PINECONE_INDEX_NAME, embedding=get_embeddings())
