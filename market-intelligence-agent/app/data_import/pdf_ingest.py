# app/data_import/pdf_ingest.py
"""Single-file PDF -> Pinecone ingestion for the Data section's upload
flow. Shares its chunk/embed/upsert mechanics with app/ingest.py's bulk CLI
path via embed_and_upsert_pdf_documents(); unlike the bulk path, this
function ADDS to the existing manifest instead of overwriting it, since one
upload is never "the whole corpus"."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader

from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.ingest import _write_manifest, embed_and_upsert_pdf_documents


def ingest_single_pdf(file_bytes: bytes, filename: str) -> int:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(file_bytes)
        tmp.flush()
        documents = PyPDFLoader(tmp.name).load()

    # PyPDFLoader stamps metadata["source"] with the randomized tempfile path,
    # which differs on every call. _assign_chunk_ids derives each chunk's
    # deterministic ID from that field, so without pinning it to the stable
    # filename, re-uploading the same PDF would get new chunk IDs each time
    # and duplicate (rather than overwrite) vectors in Pinecone.
    for doc in documents:
        doc.metadata["source"] = filename

    chunk_ids = embed_and_upsert_pdf_documents(documents, filename)

    existing = json.loads(KB_MANIFEST_PATH.read_text(encoding="utf-8")) if KB_MANIFEST_PATH.exists() else []
    _write_manifest(sorted(set(existing) | {filename}), path=KB_MANIFEST_PATH)

    return len(chunk_ids)
