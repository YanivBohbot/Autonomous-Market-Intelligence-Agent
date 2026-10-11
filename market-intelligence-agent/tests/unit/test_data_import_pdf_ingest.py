import io
import json
import os
import tempfile

from langchain_core.documents import Document
from pypdf import PdfWriter

from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.data_import.pdf_ingest import ingest_single_pdf

_FAKE_PAGES = [{"page_content": "Some extracted text about Acme Corp.", "metadata": {"page": 0}}]


def _fake_loader(_path):
    class _Loader:
        def load(self):
            return [Document(page_content=p["page_content"], metadata=dict(p["metadata"])) for p in _FAKE_PAGES]
    return _Loader()


class _FakeStore:
    """Stands in for the single PineconeVectorStore (app.rag.vectorstore)."""
    def __init__(self):
        self.calls = []

    def add_documents(self, documents, ids=None):
        self.calls.append({"documents": documents, "ids": ids})
        return ids


def test_ingest_single_pdf_upserts_chunks_and_returns_their_count(tmp_path, monkeypatch):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text(json.dumps(["existing-report.pdf"]))
    monkeypatch.setattr("app.data_import.pdf_ingest.KB_MANIFEST_PATH", manifest)
    monkeypatch.setattr("app.rag.loaders.PyPDFLoader", _fake_loader)
    store = _FakeStore()
    monkeypatch.setattr("app.rag.ingestion.get_vectorstore", lambda: store)

    chunk_count = ingest_single_pdf(b"%PDF-1.4 fake bytes", "new-report.pdf")

    assert chunk_count >= 1
    assert store.calls, "Pinecone upsert was not called"


def test_ingest_single_pdf_adds_to_the_manifest_without_removing_existing_entries(tmp_path, monkeypatch):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text(json.dumps(["existing-report.pdf"]))
    monkeypatch.setattr("app.data_import.pdf_ingest.KB_MANIFEST_PATH", manifest)
    monkeypatch.setattr("app.rag.loaders.PyPDFLoader", _fake_loader)
    store = _FakeStore()
    monkeypatch.setattr("app.rag.ingestion.get_vectorstore", lambda: store)

    ingest_single_pdf(b"%PDF-1.4 fake bytes", "new-report.pdf")

    assert set(json.loads(manifest.read_text())) == {"existing-report.pdf", "new-report.pdf"}


def test_ingesting_the_same_pdf_twice_does_not_duplicate_the_manifest_entry(tmp_path, monkeypatch):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text(json.dumps([]))
    monkeypatch.setattr("app.data_import.pdf_ingest.KB_MANIFEST_PATH", manifest)
    monkeypatch.setattr("app.rag.loaders.PyPDFLoader", _fake_loader)
    store = _FakeStore()
    monkeypatch.setattr("app.rag.ingestion.get_vectorstore", lambda: store)

    ingest_single_pdf(b"%PDF-1.4 fake bytes", "same-report.pdf")
    ingest_single_pdf(b"%PDF-1.4 fake bytes", "same-report.pdf")

    assert json.loads(manifest.read_text()) == ["same-report.pdf"]


def test_ingesting_the_same_pdf_twice_upserts_with_identical_chunk_ids(tmp_path, monkeypatch):
    """Re-uploading the same PDF must overwrite its Pinecone vectors (same
    chunk IDs both times), not create duplicates. PyPDFLoader stamps
    metadata["source"] with a randomized tempfile path on every call, and
    _assign_chunk_ids derives IDs from that field, so this guards against
    the single-file path losing idempotency if the stable-source fix
    regresses."""
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text(json.dumps([]))
    monkeypatch.setattr("app.data_import.pdf_ingest.KB_MANIFEST_PATH", manifest)
    monkeypatch.setattr("app.rag.loaders.PyPDFLoader", _fake_loader)
    store = _FakeStore()
    monkeypatch.setattr("app.rag.ingestion.get_vectorstore", lambda: store)

    ingest_single_pdf(b"%PDF-1.4 fake bytes", "same-report.pdf")
    ingest_single_pdf(b"%PDF-1.4 fake bytes", "same-report.pdf")

    assert len(store.calls) == 2
    assert store.calls[0]["ids"] == store.calls[1]["ids"]


def test_ingest_single_pdf_handles_a_real_temp_file_and_real_pypdf_loader(tmp_path, monkeypatch):
    """Regression test for a Windows-only bug: ingest_single_pdf wrote to its
    NamedTemporaryFile and then, while still holding that file open (the
    `with tempfile.NamedTemporaryFile(...) as tmp:` block), handed the same
    path to PyPDFLoader to open AGAIN for reading. POSIX allows two open
    handles to the same inode from one process; Windows does not, so
    PyPDFLoader().load() raised `PermissionError: [Errno 13] Permission
    denied` on every real upload on Windows. All the other tests in this
    file monkeypatch PyPDFLoader entirely, so none of them ever actually
    wrote bytes to disk and re-opened them -- this test deliberately leaves
    PyPDFLoader real so that exact file-handle-contention bug is exercised
    for real, on whatever OS the test runs on (including Windows CI
    runners), rather than mocked away.

    There's no PDF fixture file in this repo tiny enough to vendor, so a
    minimal single-page PDF is generated on the fly with pypdf (the same
    library PyPDFLoader uses under the hood) -- real, parseable %PDF bytes,
    not a monkeypatched loader and not a hand-typed fake header."""
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text(json.dumps([]))
    monkeypatch.setattr("app.data_import.pdf_ingest.KB_MANIFEST_PATH", manifest)
    store = _FakeStore()
    monkeypatch.setattr("app.rag.ingestion.get_vectorstore", lambda: store)

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    real_pdf_bytes = buf.getvalue()
    assert real_pdf_bytes.startswith(b"%PDF")

    # Spy on the real tempfile.NamedTemporaryFile (not mocked away) so we can
    # assert the temp file is cleaned up afterwards, proving the fix's
    # try/finally os.unlink actually ran rather than leaking the file.
    captured = {}
    real_named_temporary_file = tempfile.NamedTemporaryFile

    def _spy(*args, **kwargs):
        handle = real_named_temporary_file(*args, **kwargs)
        captured["path"] = handle.name
        return handle

    monkeypatch.setattr("app.data_import.pdf_ingest.tempfile.NamedTemporaryFile", _spy)

    # This call must not raise PermissionError (the bug) -- a blank page
    # yields zero extracted text / zero chunks, which is fine; the point of
    # this test is the real open-write-close-reopen sequence succeeding.
    chunk_count = ingest_single_pdf(real_pdf_bytes, "real-report.pdf")

    assert chunk_count == 0
    assert "path" in captured, "ingest_single_pdf did not create a temp file via tempfile.NamedTemporaryFile"
    assert not os.path.exists(captured["path"]), "ingest_single_pdf must delete its temp file after use"
    assert json.loads(manifest.read_text()) == ["real-report.pdf"]
