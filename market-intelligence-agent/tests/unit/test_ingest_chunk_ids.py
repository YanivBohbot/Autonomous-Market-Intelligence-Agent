from langchain_core.documents import Document

from app.ingest import _assign_chunk_ids, _chunk_id


def test_chunk_id_is_deterministic():
    assert _chunk_id("data/a.pdf", 0, 0) == _chunk_id("data/a.pdf", 0, 0)


def test_chunk_id_differs_by_page_or_index():
    base = _chunk_id("data/a.pdf", 0, 0)
    assert _chunk_id("data/a.pdf", 1, 0) != base
    assert _chunk_id("data/a.pdf", 0, 1) != base


def test_assign_chunk_ids_disambiguates_same_page_chunks():
    splits = [
        Document(page_content="chunk 1", metadata={"source": "data/a.pdf", "page": 0}),
        Document(page_content="chunk 2", metadata={"source": "data/a.pdf", "page": 0}),
        Document(page_content="chunk 3", metadata={"source": "data/b.pdf", "page": 0}),
    ]
    ids = _assign_chunk_ids(splits)
    assert len(ids) == 3
    assert len(set(ids)) == 3  # all unique


def test_assign_chunk_ids_is_stable_across_runs():
    splits = [
        Document(page_content="chunk 1", metadata={"source": "data/a.pdf", "page": 0}),
        Document(page_content="chunk 2", metadata={"source": "data/a.pdf", "page": 0}),
    ]
    assert _assign_chunk_ids(splits) == _assign_chunk_ids(splits)
