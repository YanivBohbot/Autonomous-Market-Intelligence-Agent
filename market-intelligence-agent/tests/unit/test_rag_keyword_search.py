from langchain_core.documents import Document

from app.rag import keyword_search as ks


def _splits(filename, *texts):
    return [Document(page_content=t, metadata={"filename": filename, "page": i}) for i, t in enumerate(texts)]


def test_missing_corpus_gives_no_keyword_retriever():
    assert ks.build_keyword_retriever(None) is None


def test_write_then_search_finds_exact_terms_case_insensitively():
    # >= 3 chunks: BM25Okapi's IDF is 0 for a term found in 1 of 2 documents.
    texts = ("Our platform has $3.6 trillion in Assets Under Supervision.", "Net revenues rose.", "Headcount grew.")
    ks.write_corpus_entries("gs.pdf", _splits("gs.pdf", *texts), ["i1", "i2", "i3"])
    docs = ks.build_keyword_retriever(None).invoke("assets under supervision")
    assert docs[0].page_content.startswith("Our platform")
    assert docs[0].metadata == {"filename": "gs.pdf", "page": 0}


def test_rewriting_a_file_replaces_its_chunks_and_keeps_other_files():
    ks.write_corpus_entries("a.pdf", _splits("a.pdf", "old alpha text"), ["a1"])
    ks.write_corpus_entries("b.pdf", _splits("b.pdf", "beta text"), ["b1"])
    ks.write_corpus_entries("a.pdf", _splits("a.pdf", "new alpha text"), ["a1"])
    texts = sorted(e["text"] for e in ks._read_entries(ks.CORPUS_PATH))
    assert texts == ["beta text", "new alpha text"]


def test_filter_restricts_keyword_search_to_the_given_files():
    ks.write_corpus_entries("a.pdf", _splits("a.pdf", "free cash flow alpha"), ["a1"])
    ks.write_corpus_entries("b.pdf", _splits("b.pdf", "free cash flow beta"), ["b1"])
    docs = ks.build_keyword_retriever({"filename": {"$in": ["b.pdf"]}}).invoke("free cash flow")
    assert {d.metadata["filename"] for d in docs} == {"b.pdf"}


def test_filter_matching_no_file_gives_no_keyword_retriever():
    ks.write_corpus_entries("a.pdf", _splits("a.pdf", "text"), ["a1"])
    assert ks.build_keyword_retriever({"filename": {"$in": ["zzz.pdf"]}}) is None


def test_writing_invalidates_the_cached_index():
    ks.write_corpus_entries("a.pdf", _splits("a.pdf", "alpha"), ["a1"])
    assert len(ks.build_keyword_retriever(None).docs) == 1
    ks.write_corpus_entries("b.pdf", _splits("b.pdf", "beta"), ["b1"])
    assert len(ks.build_keyword_retriever(None).docs) == 2
