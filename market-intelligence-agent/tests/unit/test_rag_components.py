from langchain_core.documents import Document

from app.rag import ingestion, loaders
from app.rag.ingestion import assign_chunk_ids, chunk_id, index_documents
from app.rag.splitters import build_text_splitter


def test_text_splitter_uses_1000_chars_with_200_overlap():
    splitter = build_text_splitter()
    assert splitter._chunk_size == 1000
    assert splitter._chunk_overlap == 200


def test_chunk_id_matches_pre_refactor_golden_values():
    # Computed from app/ingest.py::_chunk_id before the refactor (sha256 of
    # "source:page:index"). Any drift duplicates every vector in Pinecone.
    assert chunk_id("data/Amazon-2024-Annual-Report.pdf", 0, 0) == (
        "e31628f63576e552620f22f57dc1f1c1adaee055c8f983da9e80eba77c1382f1"
    )
    assert chunk_id("Amazon-2024-Annual-Report.pdf", 6, 2) == (
        "4ccaa499fb9e4af6d93a80ca41000937617f5179a8f908ac84a96613041c9de1"
    )


def test_assign_chunk_ids_counts_per_source_and_page():
    splits = [
        Document(page_content="a", metadata={"source": "x.pdf", "page": 0}),
        Document(page_content="b", metadata={"source": "x.pdf", "page": 0}),
        Document(page_content="c", metadata={"source": "x.pdf", "page": 1}),
    ]
    assert assign_chunk_ids(splits) == [
        chunk_id("x.pdf", 0, 0), chunk_id("x.pdf", 0, 1), chunk_id("x.pdf", 1, 0)
    ]


class _FakeLoader:
    def __init__(self, path):
        self.path = path

    def load(self):
        return [Document(page_content="p1", metadata={"source": self.path, "page": 0})]


def test_load_pdf_keeps_loader_source_by_default(monkeypatch):
    monkeypatch.setattr(loaders, "PyPDFLoader", _FakeLoader)
    docs = loaders.load_pdf("data/r.pdf", filename="r.pdf")
    assert docs[0].metadata["source"] == "data/r.pdf"


def test_load_pdf_overrides_source_when_given(monkeypatch):
    monkeypatch.setattr(loaders, "PyPDFLoader", _FakeLoader)
    docs = loaders.load_pdf("C:/tmp/abc123.pdf", filename="r.pdf", source="r.pdf")
    assert docs[0].metadata["source"] == "r.pdf"


class _FakeStore:
    def __init__(self):
        self.calls = []

    def add_documents(self, documents, ids=None):
        self.calls.append((documents, ids))
        return ids


def test_index_documents_tags_filename_and_upserts_with_deterministic_ids(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(ingestion, "get_vectorstore", lambda: store)
    docs = [Document(page_content="Some text about Acme.", metadata={"source": "r.pdf", "page": 0})]

    ids = index_documents(docs, "r.pdf")

    (splits, passed_ids), = store.calls
    assert ids == passed_ids == assign_chunk_ids(splits)
    assert all(s.metadata["filename"] == "r.pdf" for s in splits)


def test_index_documents_writes_the_same_chunks_to_the_keyword_corpus(monkeypatch):
    from app.rag import keyword_search

    store = _FakeStore()
    monkeypatch.setattr(ingestion, "get_vectorstore", lambda: store)
    docs = [Document(page_content="Some text about Acme.", metadata={"source": "r.pdf", "page": 0})]

    ids = index_documents(docs, "r.pdf")

    entries = keyword_search._read_entries(keyword_search.CORPUS_PATH)
    assert [e["id"] for e in entries] == ids
    assert {e["filename"] for e in entries} == {"r.pdf"}
