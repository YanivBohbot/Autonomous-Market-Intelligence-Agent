import logging
import os
from functools import lru_cache

from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pydantic import BaseModel, Field
from tavily import TavilyClient

from app.core.config import settings

logger = logging.getLogger(__name__)

_tavily = TavilyClient(api_key=settings.TAVILY_API_KEY)


@lru_cache(maxsize=1)
def _get_vectorstore() -> PineconeVectorStore:
    """Lazy: PineconeVectorStore.__init__ makes a network call to resolve the
    index host, so we defer it past module import to keep tests offline-safe."""
    embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
    return PineconeVectorStore(
        index_name=settings.PINECONE_INDEX_NAME, embedding=embeddings
    )


def _list_ingested_pdfs(data_dir: str = "data") -> list[str]:
    if not os.path.isdir(data_dir):
        return []
    return sorted(f for f in os.listdir(data_dir) if f.lower().endswith(".pdf"))


def _resolve_source_filter(source_filter: str) -> list[str] | None:
    """Case-insensitive substring match against ingested filenames, resolved
    to the exact `source` metadata values app/ingest.py wrote (data dir +
    filename). Returns None if nothing matches."""
    matches = [
        f for f in _list_ingested_pdfs()
        if source_filter.lower() in f.lower()
    ]
    if not matches:
        return None
    return [os.path.join("data", f) for f in matches]


class KBSearchInput(BaseModel):
    query: str = Field(description="The search query against the internal knowledge base.")
    k: int = Field(default=4, description="Number of chunks to retrieve.")
    source_filter: str | None = Field(
        default=None,
        description=(
            "Optional filename substring (e.g. 'TSLA', 'Amazon') to restrict "
            "the search to one ingested document. Use when the question names "
            "a specific company or ticker."
        ),
    )


@tool("search_knowledge_base", args_schema=KBSearchInput)
def search_knowledge_base_tool(query: str, k: int = 4, source_filter: str | None = None) -> str:
    """Search the internal knowledge base of ingested company reports/documents.
    Use for questions about specific companies' financials, risk factors, or
    any content from ingested PDFs. Pass source_filter to target one document
    when the question names a specific company/ticker."""
    search_kwargs: dict = {"k": k}
    if source_filter:
        resolved = _resolve_source_filter(source_filter)
        if resolved is None:
            available = ", ".join(_list_ingested_pdfs()) or "none"
            return (
                f"No ingested document matches source_filter={source_filter!r}. "
                f"Available documents: {available}"
            )
        search_kwargs["filter"] = {"source": {"$in": resolved}}

    try:
        retriever = _get_vectorstore().as_retriever(search_kwargs=search_kwargs)
        docs = retriever.invoke(query)
    except Exception as exc:
        logger.warning("KB_SEARCH: failed (%s)", exc)
        return f"Knowledge base search failed: {exc}"

    if not docs:
        return "No relevant results found in the knowledge base for this query."

    parts = [
        f"[Source: {os.path.basename(d.metadata.get('source', 'unknown'))}, "
        f"page {d.metadata.get('page', '?')}] {d.page_content}"
        for d in docs
    ]
    return "\n\n".join(parts)


class WebSearchInput(BaseModel):
    query: str = Field(description="The web search query.")


@tool("web_search", args_schema=WebSearchInput)
def web_search_tool(query: str) -> str:
    """Search the live web. Use when the knowledge base has no relevant
    information, or the question needs current/external information."""
    try:
        response = _tavily.search(query=query, max_results=3, search_depth="advanced")
    except Exception as exc:
        logger.warning("WEB_SEARCH: failed (%s)", exc)
        return f"Web search failed: {exc}"

    results = response.get("results", [])
    if not results:
        return "No web results found for this query."

    parts = [f"[SOURCE WEB: {r['url']}] {r['content']}" for r in results]
    return "\n\n".join(parts)
