# app/data_import/pdf_ingest.py
"""Single-file PDF -> Pinecone ingestion for the Data section's upload
flow. Shares its chunk/embed/upsert mechanics with app/ingest.py's bulk CLI
path via embed_and_upsert_pdf_documents(); unlike the bulk path, this
function ADDS to the existing manifest instead of overwriting it, since one
upload is never "the whole corpus"."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader

from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.ingest import _write_manifest, embed_and_upsert_pdf_documents


def ingest_single_pdf(file_bytes: bytes, filename: str) -> int:
    # delete=False + explicit close before PyPDFLoader opens the path: on
    # Windows, NamedTemporaryFile's own handle is held exclusively, so a
    # second open of the same path (PyPDFLoader -> pypdf) from within the
    # `with` block raises PermissionError. POSIX allows this (multiple opens
    # of the same inode), which is why this only surfaces on Windows. Close
    # our handle first, then clean up the file ourselves in `finally` so it's
    # removed even if PyPDFLoader raises.
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp.write(file_bytes)
        tmp.close()
        documents = PyPDFLoader(tmp.name).load()
    finally:
        os.unlink(tmp.name)

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
