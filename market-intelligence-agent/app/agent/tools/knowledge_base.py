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
    """Case-insensitive substring match against ingested filenames. Returns
    the matched bare filenames (used to filter on the `filename` metadata
    field, which is OS/path independent), or None if nothing matches."""
    matches = [
        f for f in _list_ingested_pdfs()
        if source_filter.lower() in f.lower()
    ]
    if not matches:
        return None
    return matches


class KBSearchInput(BaseModel):
    query: str = Field(description="The search query against the internal knowledge base.")
    k: int = Field(default=4, ge=1, le=10, description="Number of chunks to retrieve.")
    source_filter: str | None = Field(
        default=None,
        description=(
            "Optional filename substring (e.g. 'TSLA', 'Amazon') to restrict "
            "the search to one ingested document. Use when the question names "
            "a specific company or ticker."
        ),
    )


# Cosine-similarity floor below which a chunk is treated as noise rather than
# a real match. Calibrated empirically against this project's real index
# (text-embedding-3-small): on-topic queries against their matching document
# scored 0.53-0.66, off-topic queries scored 0.13-0.14 — 0.35 sits with wide
# margin in the gap between the two clusters.
_RELEVANCE_THRESHOLD = 0.35


def _display_page(page) -> str:
    """Pinecone returns numeric metadata as floats (35.0) and PyPDFLoader
    pages are 0-based; cite the 1-based page a reader sees in the PDF."""
    if page is None:
        return "?"
    return str(int(page) + 1)


@tool("search_knowledge_base", args_schema=KBSearchInput)
def search_knowledge_base_tool(query: str, k: int = 4, source_filter: str | None = None) -> str:
    """Search the internal knowledge base of ingested company reports/documents.
    Use for questions about specific companies' financials, risk factors, or
    any content from ingested PDFs. Pass source_filter to target one document
    when the question names a specific company/ticker."""
    filter_kwarg = None
    if source_filter:
        resolved = _resolve_source_filter(source_filter)
        if resolved is None:
            available = ", ".join(_list_ingested_pdfs()) or "none"
            return (
                f"No ingested document matches source_filter={source_filter!r}. "
                f"Available documents: {available}"
            )
        filter_kwarg = {"filename": {"$in": resolved}}

    try:
        results = _get_vectorstore().similarity_search_with_score(query, k=k, filter=filter_kwarg)
    except Exception as exc:
        logger.warning("KB_SEARCH: failed (%s)", exc)
        return f"Knowledge base search failed: {exc}"

    docs = [doc for doc, score in results if score >= _RELEVANCE_THRESHOLD]

    if not docs:
        return "No relevant results found in the knowledge base for this query."

    parts = [
        f"[Source: {d.metadata.get('filename', os.path.basename(d.metadata.get('source', 'unknown')))}, "
        f"page {_display_page(d.metadata.get('page'))}] {d.page_content}"
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
