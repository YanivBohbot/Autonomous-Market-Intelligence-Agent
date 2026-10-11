import hashlib
from collections import defaultdict

from langchain_core.documents import Document

from app.rag.splitters import build_text_splitter
from app.rag.vectorstore import get_vectorstore


def chunk_id(source: str, page: int, chunk_index: int) -> str:
    return hashlib.sha256(f"{source}:{page}:{chunk_index}".encode()).hexdigest()


def assign_chunk_ids(splits) -> list[str]:
    """Deterministic per-chunk IDs so re-running ingestion is idempotent:
    a Pinecone upsert with the same ID overwrites rather than duplicates."""
    counts: dict[tuple[str, int], int] = defaultdict(int)
    ids = []
    for doc in splits:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", 0)
        index = counts[(source, page)]
        counts[(source, page)] += 1
        ids.append(chunk_id(source, page, index))
    return ids


def index_documents(documents: list[Document], filename: str) -> list[str]:
    """Indexing pipeline: split -> tag filename -> deterministic IDs ->
    vector store upsert. Shared by the bulk CLI and the upload path."""
    splits = build_text_splitter().split_documents(documents)
    for doc in splits:
        doc.metadata["filename"] = filename
    ids = assign_chunk_ids(splits)
    get_vectorstore().add_documents(splits, ids=ids)
    return ids
