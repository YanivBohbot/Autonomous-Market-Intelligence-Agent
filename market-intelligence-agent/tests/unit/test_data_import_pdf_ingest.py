import json

from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.data_import.pdf_ingest import ingest_single_pdf

_FAKE_PAGES = [{"page_content": "Some extracted text about Acme Corp.", "metadata": {"page": 0}}]


class _FakeDoc:
    def __init__(self, page_content, metadata):
        self.page_content = page_content
        self.metadata = metadata


def _fake_loader(_path):
    class _Loader:
        def load(self):
            return [_FakeDoc(p["page_content"], dict(p["metadata"])) for p in _FAKE_PAGES]
    return _Loader()


def _fake_vectorstore_from_documents(**kwargs):
    _fake_vectorstore_from_documents.calls.append(kwargs)


_fake_vectorstore_from_documents.calls = []


def test_ingest_single_pdf_upserts_chunks_and_returns_their_count(tmp_path, monkeypatch):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text(json.dumps(["existing-report.pdf"]))
    monkeypatch.setattr("app.data_import.pdf_ingest.KB_MANIFEST_PATH", manifest)
    monkeypatch.setattr("app.data_import.pdf_ingest.PyPDFLoader", _fake_loader)
    monkeypatch.setattr("app.ingest.OpenAIEmbeddings", lambda **kw: object())
    monkeypatch.setattr(
        "app.ingest.PineconeVectorStore.from_documents",
        staticmethod(lambda **kw: _fake_vectorstore_from_documents(**kw)),
    )

    chunk_count = ingest_single_pdf(b"%PDF-1.4 fake bytes", "new-report.pdf")

    assert chunk_count >= 1
    assert _fake_vectorstore_from_documents.calls, "Pinecone upsert was not called"


def test_ingest_single_pdf_adds_to_the_manifest_without_removing_existing_entries(tmp_path, monkeypatch):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text(json.dumps(["existing-report.pdf"]))
    monkeypatch.setattr("app.data_import.pdf_ingest.KB_MANIFEST_PATH", manifest)
    monkeypatch.setattr("app.data_import.pdf_ingest.PyPDFLoader", _fake_loader)
    monkeypatch.setattr("app.ingest.OpenAIEmbeddings", lambda **kw: object())
    monkeypatch.setattr(
        "app.ingest.PineconeVectorStore.from_documents",
        staticmethod(lambda **kw: None),
    )

    ingest_single_pdf(b"%PDF-1.4 fake bytes", "new-report.pdf")

    assert set(json.loads(manifest.read_text())) == {"existing-report.pdf", "new-report.pdf"}


def test_ingesting_the_same_pdf_twice_does_not_duplicate_the_manifest_entry(tmp_path, monkeypatch):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text(json.dumps([]))
    monkeypatch.setattr("app.data_import.pdf_ingest.KB_MANIFEST_PATH", manifest)
    monkeypatch.setattr("app.data_import.pdf_ingest.PyPDFLoader", _fake_loader)
    monkeypatch.setattr("app.ingest.OpenAIEmbeddings", lambda **kw: object())
    monkeypatch.setattr(
        "app.ingest.PineconeVectorStore.from_documents",
        staticmethod(lambda **kw: None),
    )

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
    monkeypatch.setattr("app.data_import.pdf_ingest.PyPDFLoader", _fake_loader)
    monkeypatch.setattr("app.ingest.OpenAIEmbeddings", lambda **kw: object())

    calls = []
    monkeypatch.setattr(
        "app.ingest.PineconeVectorStore.from_documents",
        staticmethod(lambda **kw: calls.append(kw)),
    )

    ingest_single_pdf(b"%PDF-1.4 fake bytes", "same-report.pdf")
    ingest_single_pdf(b"%PDF-1.4 fake bytes", "same-report.pdf")

    assert len(calls) == 2
    assert calls[0]["ids"] == calls[1]["ids"]
