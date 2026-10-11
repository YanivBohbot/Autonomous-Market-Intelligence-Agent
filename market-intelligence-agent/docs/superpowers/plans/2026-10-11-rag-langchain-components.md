# RAG on Standard LangChain Components — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move PDF ingestion and knowledge-base retrieval onto explicit standard LangChain components (Document Loader, Text Splitter, Embeddings, Vector Store, Retriever) in a new `app/rag/` package, with identical behavior.

**Architecture:** One module per component in `app/rag/`. `app/ingest.py`, `app/data_import/pdf_ingest.py` and `search_knowledge_base` become thin clients of it. Reranking goes through a custom `RerankingRetriever(BaseRetriever)` that composes `vectorstore.as_retriever(...)` with `PineconeRerank`. No `langchain-classic`.

**Tech Stack:** langchain-core 1.6, langchain-text-splitters 1.1, langchain-openai, langchain-pinecone 0.2.13, langchain-community 0.4 (PyPDFLoader), pytest.

**Spec:** `docs/superpowers/specs/2026-10-11-rag-langchain-components-design.md`

## Global Constraints

- Work from `F:\langchain-langgraph-mcp\mia-rag\market-intelligence-agent` (worktree, branch `feat/rag-langchain-components`). Never touch the other worktrees.
- Every Python command is prefixed with `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui`, for example `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_rag_components.py -v`.
- **Never run the full suite** (user instruction). Run only the test files named in each task.
- No import from `langchain_classic` or `langchain.retrievers` anywhere.
- Constants keep their exact values:
  - chunk_size 1000 and chunk_overlap 200;
  - rerank candidates 20 and rerank model `bge-reranker-v2-m3`;
  - cosine threshold 0.35, which becomes relevance threshold `(0.35 + 1) / 2 = 0.675`.
- Tool output strings stay byte-identical:
  - `No relevant results found in the knowledge base for this query.`
  - `Knowledge base search failed: {exc}`
  - `No ingested document matches source_filter=...`
  - `[Source: <filename>, page <n>] <content>`
- Commit trailer: `Co-Authored-By` for the model that ran. Never use a bare `git stash`.
- Do not start or stop servers on ports 8000 or 5173: the user is testing the other branch there.

## Review Focus

1. **Cosine vs relevance threshold.** A future maintainer who passes 0.35 straight to `score_threshold` would silently let through chunks with cosine ≥ −0.3, which is almost everything. Pinned in Task 2 ("score_threshold is the relevance translation of 0.35"), plus a comment on the constant.
2. **Reranker exception path.** `PineconeRerank.compress_documents` raises on quota or network errors. Search must fall back to vector order and never return "search failed" just because of the reranker. Pinned in Task 2 and Task 4.
3. **Chunk-ID drift.** Any change to the source, page or index inputs duplicates every vector in Pinecone. Pinned in Task 1 with golden hashes computed from the pre-refactor implementation.
4. **Upload-path source override.** If `load_pdf(..., source=filename)` is lost, every re-upload creates new IDs. This is pinned by the existing `test_ingesting_the_same_pdf_twice_upserts_with_identical_chunk_ids`, which is kept in Task 3.
5. **Empty candidate set.** The reranker must not be called with zero documents. Pinned in Task 2 ("returns [] without calling the reranker").

---

### Task 0: Record a retrieval baseline (pre-refactor)

**Files:**
- Create: `scripts/rag_equivalence_check.py`
- Create: `docs/superpowers/qa/2026-10-11-rag-baseline.json` (generated)

- [ ] **Step 1: Write the script**

```python
"""Print search_knowledge_base output for fixed queries as JSON, to compare
retrieval before and after the app/rag/ refactor. Calls the tool directly
(deterministic: vector search + Pinecone rerank, no LLM)."""
import json
import sys

from app.agent.tools.knowledge_base import search_knowledge_base_tool

QUERIES = [
    {"query": "What does Amazon say about AI in its 2024 annual report?", "k": 4},
    {"query": "Amazon total net sales 2024", "k": 4, "source_filter": "Amazon"},
    {"query": "best chocolate cake recipe", "k": 4},
    {"query": "revenue", "k": 3, "source_filter": "NoSuchCompany"},
]

if __name__ == "__main__":
    out = {q["query"]: search_knowledge_base_tool.invoke(q) for q in QUERIES}
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
```

- [ ] **Step 2: Run it on the unchanged code and save the output**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run python -m scripts.rag_equivalence_check > docs/superpowers/qa/2026-10-11-rag-baseline.json`
If `scripts/` has no `__init__.py`, run `uv run python scripts/rag_equivalence_check.py` with `PYTHONPATH=.` instead.
Expected: the JSON has 4 keys. The Amazon queries contain `[Source: Amazon-2024-Annual-Report.pdf, page`. The cake query maps to `No relevant results found in the knowledge base for this query.` The NoSuchCompany query maps to `No ingested document matches source_filter='NoSuchCompany'...`.

- [ ] **Step 3: Commit**

```bash
git add scripts/rag_equivalence_check.py docs/superpowers/qa/2026-10-11-rag-baseline.json
git commit -m "test(rag): record pre-refactor retrieval baseline"
```

---

### Task 1: Loader, splitter, vector store and ingestion components

**Files:**
- Create: `app/rag/__init__.py` (empty docstring module)
- Create: `app/rag/loaders.py`, `app/rag/splitters.py`, `app/rag/vectorstore.py`, `app/rag/ingestion.py`
- Test: `tests/unit/test_rag_components.py` (new)

**Interfaces:**
- Produces:
  - `load_pdf(path: str, *, filename: str, source: str | None = None) -> list[Document]`
  - `build_text_splitter() -> RecursiveCharacterTextSplitter`
  - `get_embeddings() -> OpenAIEmbeddings`
  - `get_vectorstore() -> PineconeVectorStore` (lru_cache)
  - `chunk_id(source: str, page: int, chunk_index: int) -> str`
  - `assign_chunk_ids(splits) -> list[str]`
  - `index_documents(documents, filename: str) -> list[str]`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_rag_components.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_rag_components.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.rag'`.

- [ ] **Step 3: Implement**

`app/rag/__init__.py`:

```python
"""RAG built from standard LangChain components: loaders (Document Loader),
splitters (Text Splitter), vectorstore (Embeddings + Vector Store),
ingestion (indexing pipeline) and retriever (Retriever)."""
```

`app/rag/loaders.py`:

```python
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document


def load_pdf(path: str, *, filename: str, source: str | None = None) -> list[Document]:
    """Document Loader: one Document per PDF page (0-based `page` metadata).

    `source` overrides metadata["source"] when the loader's own value is not
    stable, e.g. the upload path's randomized tempfile name. Chunk IDs derive
    from it, so an unstable source would duplicate vectors on re-upload.
    `filename` is accepted for the caller's readability; ingestion stamps
    metadata["filename"] on each split."""
    documents = PyPDFLoader(path).load()
    if source is not None:
        for doc in documents:
            doc.metadata["source"] = source
    return documents
```

`app/rag/splitters.py`:

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


def build_text_splitter() -> RecursiveCharacterTextSplitter:
    """Text Splitter shared by every ingestion path."""
    return RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
```

`app/rag/vectorstore.py`:

```python
from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

from app.core.config import settings


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def get_vectorstore() -> PineconeVectorStore:
    """The single Vector Store instance used by ingestion and retrieval.
    Lazy: PineconeVectorStore.__init__ makes a network call to resolve the
    index host, so it is deferred past module import (offline-safe tests)."""
    return PineconeVectorStore(index_name=settings.PINECONE_INDEX_NAME, embedding=get_embeddings())
```

`app/rag/ingestion.py`:

```python
import hashlib
from collections import defaultdict

from langchain_core.documents import Document

from app.rag.splitters import build_text_splitter
from app.rag.vectorstore import get_vectorstore


def chunk_id(source: str, page: int, chunk_index: int) -> str:
    return hashlib.sha256(f"{source}:{page}:{chunk_index}".encode()).hexdigest()


def assign_chunk_ids(splits) -> list[str]:
    """Deterministic per-chunk IDs so re-running ingestion is idempotent:
    a Pinecone upsert with the same ID overwrites rather than duplicates."""
    counts: dict[tuple[str, int], int] = defaultdict(int)
    ids = []
    for doc in splits:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", 0)
        index = counts[(source, page)]
        counts[(source, page)] += 1
        ids.append(chunk_id(source, page, index))
    return ids


def index_documents(documents: list[Document], filename: str) -> list[str]:
    """Indexing pipeline: split -> tag filename -> deterministic IDs ->
    vector store upsert. Shared by the bulk CLI and the upload path."""
    splits = build_text_splitter().split_documents(documents)
    for doc in splits:
        doc.metadata["filename"] = filename
    ids = assign_chunk_ids(splits)
    get_vectorstore().add_documents(splits, ids=ids)
    return ids
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_rag_components.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/rag tests/unit/test_rag_components.py
git commit -m "feat(rag): add loader, splitter, vector store and ingestion components"
```

---

### Task 2: Retriever component

**Files:**
- Create: `app/rag/retriever.py`
- Test: `tests/unit/test_rag_retriever.py` (new)

**Interfaces:**
- Consumes: `get_vectorstore()` from Task 1.
- Produces:
  - `RELEVANCE_THRESHOLD_COSINE = 0.35`, `RELEVANCE_SCORE_THRESHOLD = 0.675`, `RERANK_CANDIDATES = 20`, `RERANK_MODEL = "bge-reranker-v2-m3"`
  - `class RerankingRetriever(BaseRetriever)` with fields `base_retriever`, `reranker` and `top_n`
  - `build_kb_retriever(k: int, metadata_filter: dict | None) -> RerankingRetriever`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_rag_retriever.py`:

```python
from typing import Sequence

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.retrievers import BaseRetriever

from app.rag import retriever as r


class _ListRetriever(BaseRetriever):
    docs: list[Document]

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun):
        return list(self.docs)


class _ReverseReranker(BaseDocumentCompressor):
    top_n: int = 2
    calls: int = 0

    def compress_documents(self, documents: Sequence[Document], query: str, callbacks=None):
        object.__setattr__(self, "calls", self.calls + 1)
        return list(reversed(documents))[: self.top_n]


class _FailingReranker(BaseDocumentCompressor):
    def compress_documents(self, documents, query, callbacks=None):
        raise RuntimeError("rerank quota exceeded")


def _docs(*texts):
    return [Document(page_content=t, metadata={"filename": "x.pdf", "page": i}) for i, t in enumerate(texts)]


def test_score_threshold_is_the_relevance_translation_of_cosine_035():
    assert r.RELEVANCE_THRESHOLD_COSINE == 0.35
    assert r.RELEVANCE_SCORE_THRESHOLD == pytest.approx((0.35 + 1) / 2)


def test_reranking_retriever_returns_reranked_docs():
    rr = r.RerankingRetriever(base_retriever=_ListRetriever(docs=_docs("a", "b", "c")), reranker=_ReverseReranker(top_n=2), top_n=2)
    assert [d.page_content for d in rr.invoke("q")] == ["c", "b"]


def test_reranking_retriever_falls_back_to_vector_order_when_reranker_fails():
    rr = r.RerankingRetriever(base_retriever=_ListRetriever(docs=_docs("a", "b", "c")), reranker=_FailingReranker(), top_n=2)
    assert [d.page_content for d in rr.invoke("q")] == ["a", "b"]


def test_reranking_retriever_skips_reranker_when_no_candidates():
    reranker = _ReverseReranker()
    rr = r.RerankingRetriever(base_retriever=_ListRetriever(docs=[]), reranker=reranker, top_n=2)
    assert rr.invoke("q") == []
    assert reranker.calls == 0


class _FakeStore:
    def __init__(self):
        self.kwargs = None

    def as_retriever(self, **kwargs):
        self.kwargs = kwargs
        return _ListRetriever(docs=[])


def test_build_kb_retriever_configures_threshold_candidates_filter_and_rerank(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(r, "get_vectorstore", lambda: store)
    built = {}
    monkeypatch.setattr(r, "PineconeRerank", lambda **kw: built.setdefault("kw", kw) and _ReverseReranker(top_n=kw["top_n"]))

    rr = r.build_kb_retriever(4, {"filename": {"$in": ["a.pdf"]}})

    assert store.kwargs == {
        "search_type": "similarity_score_threshold",
        "search_kwargs": {"k": 20, "score_threshold": r.RELEVANCE_SCORE_THRESHOLD, "filter": {"filename": {"$in": ["a.pdf"]}}},
    }
    assert built["kw"]["model"] == "bge-reranker-v2-m3"
    assert built["kw"]["top_n"] == 4
    assert rr.top_n == 4


def test_build_kb_retriever_omits_filter_when_none(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(r, "get_vectorstore", lambda: store)
    monkeypatch.setattr(r, "PineconeRerank", lambda **kw: _ReverseReranker(top_n=kw["top_n"]))
    r.build_kb_retriever(4, None)
    assert "filter" not in store.kwargs["search_kwargs"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_rag_retriever.py -v`
Expected: FAIL with `ImportError` (module missing).

- [ ] **Step 3: Implement**

`app/rag/retriever.py`:

```python
import logging

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.retrievers import BaseRetriever
from langchain_pinecone import PineconeRerank

from app.core.config import settings
from app.rag.vectorstore import get_vectorstore

logger = logging.getLogger(__name__)

# Cosine-similarity floor below which a chunk is treated as noise rather than
# a real match. Calibrated empirically against this project's real index
# (text-embedding-3-small): on-topic queries against their matching document
# scored 0.53-0.66, off-topic queries scored 0.13-0.14; 0.35 sits with wide
# margin in the gap between the two clusters.
RELEVANCE_THRESHOLD_COSINE = 0.35
# as_retriever(search_type="similarity_score_threshold") filters on RELEVANCE
# scores, and PineconeVectorStore maps cosine -> relevance as (cos + 1) / 2
# (_cosine_relevance_score_fn). Translating keeps exactly the same chunks.
# Never pass the cosine value here directly: 0.35 as a relevance score would
# admit chunks down to cosine -0.3, i.e. almost everything.
RELEVANCE_SCORE_THRESHOLD = (RELEVANCE_THRESHOLD_COSINE + 1) / 2

# Vector similarity ranks number-dense chunks (financial tables) poorly: the
# Tesla "Total revenues ... 22,387 28,236" table ranked #8-9 for revenue
# queries, outside the top 4 the agent sees. Fetch a wider candidate pool and
# rerank it with a cross-encoder. Measured live, bge-reranker-v2-m3 moved
# that table to #1 (pinecone-rerank-v0 did slightly worse on Amazon).
RERANK_CANDIDATES = 20
RERANK_MODEL = "bge-reranker-v2-m3"


class RerankingRetriever(BaseRetriever):
    """Retriever = candidate retriever (vector store) + document reranker.

    Falls back to candidate order on any reranker failure (quota, network),
    so search never breaks because of the reranker."""

    base_retriever: BaseRetriever
    reranker: BaseDocumentCompressor
    top_n: int

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        docs = self.base_retriever.invoke(query, config={"callbacks": run_manager.get_child()})
        if not docs:
            return []
        try:
            return list(self.reranker.compress_documents(docs, query))
        except Exception as exc:
            logger.warning("KB_SEARCH: rerank failed, using vector order (%s)", exc)
            return docs[: self.top_n]


def build_kb_retriever(k: int, metadata_filter: dict | None) -> RerankingRetriever:
    """Knowledge-base retriever for one tool call (k and filter vary per call;
    construction is cheap because the vector store is cached)."""
    search_kwargs: dict = {"k": RERANK_CANDIDATES, "score_threshold": RELEVANCE_SCORE_THRESHOLD}
    if metadata_filter is not None:
        search_kwargs["filter"] = metadata_filter
    base = get_vectorstore().as_retriever(
        search_type="similarity_score_threshold", search_kwargs=search_kwargs
    )
    reranker = PineconeRerank(model=RERANK_MODEL, top_n=k, pinecone_api_key=settings.PINECONE_API_KEY)
    return RerankingRetriever(base_retriever=base, reranker=reranker, top_n=k)
```

If `PineconeRerank` rejects `pinecone_api_key` as a plain `str` (check its validator in `langchain_pinecone/rerank.py`), pass it the way the class expects (for example `SecretStr`) and note it in the report.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_rag_retriever.py tests/unit/test_rag_components.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/rag/retriever.py tests/unit/test_rag_retriever.py
git commit -m "feat(rag): add reranking retriever on BaseRetriever + PineconeRerank"
```

---

### Task 3: Ingestion callers use the components

**Files:**
- Modify: `app/ingest.py` (whole file)
- Modify: `app/data_import/pdf_ingest.py`
- Test: `tests/unit/test_data_import_pdf_ingest.py`, `tests/unit/test_ingest_chunk_ids.py`

**Interfaces:**
- Consumes: `load_pdf`, `index_documents`, `chunk_id`, `assign_chunk_ids`.
- Produces: `app.ingest` still exports `_chunk_id`, `_assign_chunk_ids`, `_write_manifest`, `embed_and_upsert_pdf_documents` and `ingest_document`, for backward compatibility.

- [ ] **Step 1: Update the tests to the new patch points (RED)**

In `tests/unit/test_data_import_pdf_ingest.py`, replace each test's three patches:

```python
    monkeypatch.setattr("app.data_import.pdf_ingest.PyPDFLoader", _fake_loader)
    monkeypatch.setattr("app.ingest.OpenAIEmbeddings", lambda **kw: object())
    monkeypatch.setattr(
        "app.ingest.PineconeVectorStore.from_documents",
        staticmethod(lambda **kw: ...),
    )
```

with:

```python
    monkeypatch.setattr("app.rag.loaders.PyPDFLoader", _fake_loader)
    monkeypatch.setattr("app.rag.ingestion.get_vectorstore", lambda: store)
```

`store` is a per-test fake:

```python
class _FakeStore:
    def __init__(self):
        self.calls = []

    def add_documents(self, documents, ids=None):
        self.calls.append({"documents": documents, "ids": ids})
        return ids
```

- The first test asserts `store.calls` is non-empty, instead of `_fake_vectorstore_from_documents.calls`.
- The identical-IDs test asserts `store.calls[0]["ids"] == store.calls[1]["ids"]`.
- Delete `_fake_vectorstore_from_documents`.
- `_FakeDoc` objects from `_fake_loader` must be real `Document`s now, because the splitter and the loader override use `.metadata`. Change `_fake_loader` to return `Document(page_content=..., metadata=dict(...))`.
- Check the last test (`..._real_temp_file_and_real_pypdf_loader`) and repoint its vector-store patch the same way.

`tests/unit/test_ingest_chunk_ids.py` stays as is, since it imports `_chunk_id` and `_assign_chunk_ids` from `app.ingest`, which keeps re-exporting them.

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_data_import_pdf_ingest.py -v`
Expected: FAIL (the old code still calls `PineconeVectorStore.from_documents` and imports `PyPDFLoader` in `pdf_ingest`).

- [ ] **Step 2: Rewrite `app/ingest.py`**

```python
import json
import os
from pathlib import Path

from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.rag.ingestion import assign_chunk_ids as _assign_chunk_ids  # noqa: F401  (re-export)
from app.rag.ingestion import chunk_id as _chunk_id  # noqa: F401  (re-export)
from app.rag.ingestion import index_documents
from app.rag.loaders import load_pdf


def _write_manifest(filenames: list[str], path: Path = KB_MANIFEST_PATH) -> None:
    """Record which documents are in the index, for search_knowledge_base's
    source_filter. Commit the file after ingesting so deploys ship it."""
    path.write_text(json.dumps(sorted(set(filenames)), indent=2) + "\n", encoding="utf-8")


def embed_and_upsert_pdf_documents(documents, filename: str) -> list[str]:
    """Backward-compatible alias of app.rag.ingestion.index_documents."""
    return index_documents(documents, filename)


def ingest_document():
    """Bulk CLI: load every PDF in ./data with the Document Loader and index
    it through the shared pipeline (Text Splitter -> Vector Store)."""
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
        documents = load_pdf(os.path.join(data_folder, file), filename=file)
        index_documents(documents, file)

    _write_manifest(pdf_files)
    print("✅ Ingestion  finish ! Base Knowledge ready .")


if __name__ == "__main__":
    ingest_document()
```

- [ ] **Step 3: Rewrite `app/data_import/pdf_ingest.py`**

Keep the module docstring, updated to mention `app.rag`. Keep the temp-file block exactly as is. Replace `PyPDFLoader(tmp.name).load()` with `load_pdf(tmp.name, filename=filename, source=filename)`, remove the separate `for doc in documents: doc.metadata["source"] = filename` loop (it moves into the loader call, so keep its explanatory comment above that call), and call `index_documents(documents, filename)` instead of `embed_and_upsert_pdf_documents`. Imports: `from app.rag.loaders import load_pdf`, `from app.rag.ingestion import index_documents`, `from app.ingest import _write_manifest`, plus the existing `KB_MANIFEST_PATH`. Remove the `PyPDFLoader` import.

Watch out: `load_pdf` runs inside the `try`, so the `finally: os.unlink(tmp.name)` still runs after loading, as today.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_data_import_pdf_ingest.py tests/unit/test_ingest_chunk_ids.py tests/unit/test_rag_components.py -v`
Expected: all PASS, including `test_importing_ingest_module_prints_nothing`.

- [ ] **Step 5: Commit**

```bash
git add app/ingest.py app/data_import/pdf_ingest.py tests/unit/test_data_import_pdf_ingest.py
git commit -m "refactor(rag): ingestion paths use the loader and indexing components"
```

---

### Task 4: `search_knowledge_base` uses the retriever

**Files:**
- Modify: `app/agent/tools/knowledge_base.py`
- Test: `tests/unit/test_knowledge_base_tools.py`

**Interfaces:**
- Consumes: `build_kb_retriever(k, metadata_filter)`.

- [ ] **Step 1: Rewrite the tests against the retriever seam (RED)**

In `tests/unit/test_knowledge_base_tools.py`:

- Replace the autouse `_identity_reranker` fixture and `_mock_vectorstore` with seams on `app.rag.retriever`:

```python
from app.rag import retriever as rag_retriever
from app.rag.retriever import RerankingRetriever


class _FakeStore:
    """Mimics PineconeVectorStore.as_retriever(similarity_score_threshold):
    applies the relevance translation (cos + 1) / 2 to raw cosine scores,
    as langchain_pinecone does."""
    def __init__(self, results_with_cosine=None, error=None):
        self.results = results_with_cosine or []
        self.error = error
        self.search_kwargs = None

    def as_retriever(self, search_type, search_kwargs):
        assert search_type == "similarity_score_threshold"
        self.search_kwargs = search_kwargs
        store = self

        class _R(BaseRetriever):
            def _get_relevant_documents(self, query, *, run_manager):
                if store.error:
                    raise store.error
                threshold = search_kwargs["score_threshold"]
                return [d for d, cos in store.results[: search_kwargs["k"]] if (cos + 1) / 2 >= threshold]
        return _R()


class _Reranker(BaseDocumentCompressor):
    order: list[int] | None = None
    error: Exception | None = None
    seen: list[str] = []
    top_n: int = 4
    model: str = "bge-reranker-v2-m3"

    def compress_documents(self, documents, query, callbacks=None):
        object.__setattr__(self, "seen", [d.page_content for d in documents])
        if self.error:
            raise self.error
        idx = self.order if self.order is not None else list(range(len(documents)))
        return [documents[i] for i in idx][: self.top_n]
```

- An autouse fixture `_rag` patches `rag_retriever.get_vectorstore` to return a configurable `_FakeStore` and `rag_retriever.PineconeRerank` to a factory that records kwargs and returns a configurable `_Reranker`. Expose both via the fixture (for example a `SimpleNamespace(store=..., reranker=..., rerank_kwargs=...)`).
- Port **every** existing test so it keeps the same assertion:
  - citation format, float page, unknown page;
  - the empty message;
  - vector-store error → "Knowledge base search failed" plus the message (use `_FakeStore(error=RuntimeError("Pinecone unreachable"))`);
  - the unmatched source_filter listing;
  - matched source_filter: assert `store.search_kwargs == {"k": 20, "score_threshold": rag_retriever.RELEVANCE_SCORE_THRESHOLD, "filter": {"filename": {"$in": ["TSLA-Q2-2026-Update.pdf"]}}}`;
  - low-relevance filtering at cosine 0.66 vs 0.14;
  - all below threshold → the empty message;
  - top-k in reranker order, with `order=[7, 0, 1, 2]`, plus `rerank_kwargs["model"] == "bge-reranker-v2-m3"` and `rerank_kwargs["top_n"] == 4`;
  - rerank failure → vector order;
  - reranker only sees above-threshold chunks (`reranker.seen == ["on topic"]`);
  - reranker skipped when nothing passes (`reranker.seen == []`, never called).
- The manifest tests and the web_search test are unchanged.

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_knowledge_base_tools.py -v`
Expected: FAIL (the tool still calls `_get_vectorstore().similarity_search_with_score`).

- [ ] **Step 2: Rewrite the retrieval part of `knowledge_base.py`**

- Delete `_get_vectorstore`, `_RELEVANCE_THRESHOLD`, `_RERANK_CANDIDATES`, `_RERANK_MODEL`, `_get_pinecone` and `_rerank`, plus the now-unused imports (`OpenAIEmbeddings`, `PineconeVectorStore`, `Pinecone`, `lru_cache` if unused).
- Add `from app.rag.retriever import build_kb_retriever`.
- Keep `KB_MANIFEST_PATH`, `_list_ingested_pdfs`, `_resolve_source_filter`, `KBSearchInput`, `_display_page`, the web search and `_tavily`.
- New tool body after the `filter_kwarg` resolution, which is unchanged:

```python
    try:
        docs = build_kb_retriever(k, filter_kwarg).invoke(query)
    except Exception as exc:
        logger.warning("KB_SEARCH: failed (%s)", exc)
        return f"Knowledge base search failed: {exc}"

    if not docs:
        return "No relevant results found in the knowledge base for this query."

    parts = [
        f"[Source: {d.metadata.get('filename', os.path.basename(d.metadata.get('source', 'unknown')))}, "
        f"page {_display_page(d.metadata.get('page'))}] {d.page_content}"
        for d in docs
    ]
    return "\n\n".join(parts)
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest tests/unit/test_knowledge_base_tools.py tests/unit/test_rag_retriever.py tests/unit/test_multi_agent_rag_agent.py -v`
Expected: all PASS.

- [ ] **Step 4: Run the sweep greps**

Run: `grep -rn "PineconeVectorStore(" app --include=*.py`. Expected: only `app/rag/vectorstore.py`.
Run: `grep -rn "langchain_classic\|langchain.retrievers" app tests --include=*.py`. Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools/knowledge_base.py tests/unit/test_knowledge_base_tools.py
git commit -m "refactor(rag): search_knowledge_base retrieves through the RAG retriever"
```

---

### Task 5: Live equivalence check and docs

**Files:**
- Create: `docs/superpowers/qa/2026-10-11-rag-after.json` (generated)
- Modify: `CLAUDE.md` (the "Data ingestion" section and the `search_knowledge_base` tool row), `docs/TOOLS.md` (the `search_knowledge_base` entry)

- [ ] **Step 1: Re-run the baseline script on the refactored code**

Run: `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run python -m scripts.rag_equivalence_check > docs/superpowers/qa/2026-10-11-rag-after.json`. Use the same invocation as Task 0.

- [ ] **Step 2: Compare**

Run: `diff docs/superpowers/qa/2026-10-11-rag-baseline.json docs/superpowers/qa/2026-10-11-rag-after.json`
Expected: no differences. If there is a difference, do not paper over it. Report it, find the cause (filter, threshold, rerank order or formatting), fix it, and re-run. Live Pinecone rerank is deterministic for identical inputs.

- [ ] **Step 3: Update the docs (edit, never delete)**

- In `CLAUDE.md` "Data ingestion": state that ingestion runs through `app/rag/`, with `loaders.load_pdf` (PyPDFLoader), `splitters.build_text_splitter` (Recursive 1000/200), `ingestion.index_documents` (deterministic IDs, then `PineconeVectorStore.add_documents`) and `vectorstore.get_vectorstore` (the single instance). Both `app/ingest.py` (bulk) and `app/data_import/pdf_ingest.py` (upload) use it.
- In the `search_knowledge_base` tool row: it retrieves through `app/rag/retriever.build_kb_retriever`, a `RerankingRetriever(BaseRetriever)` over `as_retriever(similarity_score_threshold, k=20, relevance ≥ 0.675 ≡ cosine 0.35)` plus `PineconeRerank(bge-reranker-v2-m3)`. No langchain-classic.
- In `docs/TOOLS.md`, update the same entry the same way.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/qa/2026-10-11-rag-after.json CLAUDE.md docs/TOOLS.md
git commit -m "docs(rag): describe component layout; record post-refactor equivalence"
```
