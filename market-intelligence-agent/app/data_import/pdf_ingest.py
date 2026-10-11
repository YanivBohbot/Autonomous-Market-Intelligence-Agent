# app/data_import/pdf_ingest.py
"""Single-file PDF -> Pinecone ingestion for the Data section's upload
flow. Uses the same app/rag components as app/ingest.py's bulk CLI path
(load_pdf Document Loader -> index_documents pipeline); unlike the bulk
path, this function ADDS to the existing manifest instead of overwriting
it, since one upload is never "the whole corpus"."""

from __future__ import annotations

import json
import os
import tempfile

from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.ingest import _write_manifest
from app.rag.ingestion import index_documents
from app.rag.loaders import load_pdf


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
        # PyPDFLoader stamps metadata["source"] with the randomized tempfile
        # path, which differs on every call. Chunk IDs derive from that field,
        # so without pinning it to the stable filename (source=filename),
        # re-uploading the same PDF would get new chunk IDs each time and
        # duplicate (rather than overwrite) vectors in Pinecone.
        documents = load_pdf(tmp.name, filename=filename, source=filename)
    finally:
        os.unlink(tmp.name)

    chunk_ids = index_documents(documents, filename)

    existing = json.loads(KB_MANIFEST_PATH.read_text(encoding="utf-8")) if KB_MANIFEST_PATH.exists() else []
    _write_manifest(sorted(set(existing) | {filename}), path=KB_MANIFEST_PATH)

    return len(chunk_ids)
