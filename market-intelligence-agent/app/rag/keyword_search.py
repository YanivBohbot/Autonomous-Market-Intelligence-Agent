"""Keyword (BM25) side of the hybrid knowledge-base search.

Dense search misses chunks whose embedding is diluted -- a shareholder-letter
passage covering ten topics, where "$3.6 trillion in assets under supervision"
is one sentence among many. BM25 matches those exact terms. Measured on 27
questions with expected pages (2026-10-13): dense + rerank 22/27, dense + BM25
+ rerank 25/27 with source_filter, 24/27 without.

Pinecone's native hybrid search needs a dotproduct index (ours is cosine, and
the account is at its index cap), and rebuilding BM25 from Pinecone at request
time is too slow (list + fetch of ~2800 chunks: ~1.5 min). So the chunk texts
are kept in a local corpus file written by app.rag.ingestion.index_documents --
same chunks (text, filename, page) as the Pinecone upsert -- shipped in app/
like kb_documents.json. Commit it after ingesting. Candidates are merged with
the vector ones by text, not ID (RerankingRetriever's same-text dedup).
"""

import gzip
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

CORPUS_PATH = Path(__file__).with_name("kb_chunks.jsonl.gz")
KEYWORD_CANDIDATES = 20


def _tokenize(text: str) -> list[str]:
    # BM25Retriever's default preprocess is str.split: case-sensitive and
    # keeps punctuation glued to words ("revenue," != "revenue").
    return re.findall(r"\w+", text.lower())


def _read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_corpus_entries(filename: str, splits: list[Document], ids: list[str], path: Path | None = None) -> None:
    """Replace `filename`'s chunks in the corpus with `splits` (same IDs as
    the Pinecone upsert), keeping every other document's chunks."""
    path = Path(path or CORPUS_PATH)
    entries = [e for e in _read_entries(path) if e["filename"] != filename]
    entries += [
        {"id": chunk_id, "filename": filename, "page": doc.metadata.get("page"), "text": doc.page_content}
        for chunk_id, doc in zip(ids, splits)
    ]
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    invalidate()


@lru_cache(maxsize=1)
def _corpus() -> tuple[Document, ...]:
    return tuple(
        Document(page_content=e["text"], metadata={"filename": e["filename"], "page": e["page"]})
        for e in _read_entries(CORPUS_PATH)
    )


@lru_cache(maxsize=32)
def _retriever_for(filenames: frozenset[str] | None) -> BM25Retriever | None:
    docs = [d for d in _corpus() if filenames is None or d.metadata["filename"] in filenames]
    if not docs:
        return None
    return BM25Retriever.from_documents(docs, k=KEYWORD_CANDIDATES, preprocess_func=_tokenize)


def invalidate() -> None:
    """Drop the cached corpus and BM25 indexes (after an ingestion)."""
    _retriever_for.cache_clear()
    _corpus.cache_clear()


def build_keyword_retriever(metadata_filter: dict | None) -> BM25Retriever | None:
    """BM25 retriever over the corpus, restricted like the dense search.
    Only the {"filename": {"$in": [...]}} filter search_knowledge_base builds
    is supported. None when the corpus is missing or nothing matches."""
    filenames = None
    if metadata_filter is not None:
        filenames = frozenset(metadata_filter["filename"]["$in"])
    retriever = _retriever_for(filenames)
    if retriever is None:
        logger.warning("KB_SEARCH: no keyword corpus for filter %s (%s)", metadata_filter, CORPUS_PATH)
    return retriever
