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
from app.ingest import embed_and_upsert_pdf_documents


def ingest_single_pdf(file_bytes: bytes, filename: str) -> int:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(file_bytes)
        tmp.flush()
        documents = PyPDFLoader(tmp.name).load()

    chunk_ids = embed_and_upsert_pdf_documents(documents, filename)

    existing = json.loads(KB_MANIFEST_PATH.read_text()) if KB_MANIFEST_PATH.exists() else []
    KB_MANIFEST_PATH.write_text(json.dumps(sorted(set(existing) | {filename}), indent=2) + "\n")

    return len(chunk_ids)
