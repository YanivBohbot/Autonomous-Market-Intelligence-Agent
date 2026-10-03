import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

from app.core.config import settings
from app.agent.tools.knowledge_base import KB_MANIFEST_PATH


def _chunk_id(source: str, page: int, chunk_index: int) -> str:
    return hashlib.sha256(f"{source}:{page}:{chunk_index}".encode()).hexdigest()


def _assign_chunk_ids(splits) -> list[str]:
    """Deterministic per-chunk IDs so re-running ingestion is idempotent:
    Pinecone upsert with the same ID overwrites rather than duplicates."""
    counts: dict[tuple[str, int], int] = defaultdict(int)
    ids = []
    for doc in splits:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", 0)
        chunk_index = counts[(source, page)]
        counts[(source, page)] += 1
        ids.append(_chunk_id(source, page, chunk_index))
    return ids


def _write_manifest(filenames: list[str], path: Path = KB_MANIFEST_PATH) -> None:
    """Record which documents are in the index, for search_knowledge_base's
    source_filter. Commit the file after ingesting so deploys ship it."""
    path.write_text(json.dumps(sorted(set(filenames)), indent=2) + "\n", encoding="utf-8")


def embed_and_upsert_pdf_documents(documents, filename: str) -> list[str]:
    """Split, embed, and upsert one PDF's already-loaded pages into
    Pinecone. Shared by the bulk CLI ingest below and
    app/data_import/pdf_ingest.py's single-file path, so both go through
    the exact same chunking/ID/embedding logic."""
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents(documents)
    for doc in splits:
        doc.metadata["filename"] = filename
    ids = _assign_chunk_ids(splits)
    embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
    PineconeVectorStore.from_documents(
        documents=splits, embedding=embeddings, index_name=settings.PINECONE_INDEX_NAME, ids=ids
    )
    return ids


def ingest_document():
    """Read PDF from data folder et index in pinecone"""
    print(" Starting to ingest to pinecone....")

    data_folder = "data"
    if not os.path.exists(data_folder):
        os.makedirs(data_folder)
        print(f"⚠️ Folder '{data_folder}' created. Put some PDFs and restar.")
        return

    pdf_files = [f for f in os.listdir(data_folder) if f.endswith(".pdf")]
    if not pdf_files:
        print("❌ No document PDF found.")
        return

    print("cw Stockage dans Pinecone (cela peut prendre quelques secondes)...")
    for file in pdf_files:
        pdf_path = os.path.join(data_folder, file)
        print(f" Charging the {file}..")
        documents = PyPDFLoader(pdf_path).load()
        embed_and_upsert_pdf_documents(documents, file)

    _write_manifest(pdf_files)
    print("✅ Ingestion  finish ! Base Knowledge ready .")


if __name__ == "__main__":
    ingest_document()
