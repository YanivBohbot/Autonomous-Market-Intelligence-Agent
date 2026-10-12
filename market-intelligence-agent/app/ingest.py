import json
import os
import sys
from pathlib import Path

from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.rag.ingestion import assign_chunk_ids as _assign_chunk_ids  # noqa: F401  (re-export)
from app.rag.ingestion import chunk_id as _chunk_id  # noqa: F401  (re-export)
from app.rag.ingestion import index_documents, split_documents
from app.rag.keyword_search import write_corpus_entries
from app.rag.loaders import load_pdf


def _write_manifest(filenames: list[str], path: Path = KB_MANIFEST_PATH) -> None:
    """Record which documents are in the index, for search_knowledge_base's
    source_filter. Commit the file after ingesting so deploys ship it."""
    path.write_text(json.dumps(sorted(set(filenames)), indent=2) + "\n", encoding="utf-8")


def embed_and_upsert_pdf_documents(documents, filename: str) -> list[str]:
    """Backward-compatible alias of app.rag.ingestion.index_documents."""
    return index_documents(documents, filename)


def ingest_document(corpus_only: bool = False):
    """Bulk CLI: load every PDF in ./data with the Document Loader and index
    it through the shared pipeline (Text Splitter -> Vector Store + keyword
    corpus). corpus_only (`--corpus-only`) rebuilds just the keyword corpus
    -- same chunks and IDs as Pinecone -- without re-embedding."""
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
        print(f" Charging the {file}..")
        # source=file (not the path): same source -- hence same chunk IDs --
        # as the upload path, so a PDF ingested by both is overwritten in
        # Pinecone instead of stored twice.
        documents = load_pdf(os.path.join(data_folder, file), filename=file, source=file)
        if corpus_only:
            write_corpus_entries(file, *split_documents(documents, file))
        else:
            index_documents(documents, file)

    _write_manifest(pdf_files)
    print("✅ Ingestion  finish ! Base Knowledge ready .")


if __name__ == "__main__":
    ingest_document(corpus_only="--corpus-only" in sys.argv)
