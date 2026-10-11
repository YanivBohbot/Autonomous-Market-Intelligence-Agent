# RAG on Standard LangChain Components

Date: 2026-10-11
Branch: `feat/rag-langchain-components`, branched from `feat/product-ui-modernization` at a513bb1. Worktree: `F:\langchain-langgraph-mcp\mia-rag`.

## Goal

Restructure PDF ingestion (bulk CLI and single-file upload) and knowledge-base retrieval so that each stage is an explicit, standard LangChain component: Document Loader, Text Splitter, Embeddings, Vector Store and Retriever. Only modern packages are used. **Behavior must stay identical**: same chunks, same chunk IDs, same relevance filtering, same reranking and the same text returned to the agent.

## Decisions (agreed with the user)

1. **Refactor only (option A).** No new capabilities: no new loaders, no MMR or hybrid search, no multi-query.
2. **Modern packages only. No `langchain-classic`.** That rules out `ContextualCompressionRetriever`. Reranking is composed in a custom retriever that subclasses `langchain_core.retrievers.BaseRetriever`, which the LangChain retriever-integrations page describes as the way to build custom retrievers.
3. **`PyPDFLoader` from `langchain-community`.** pypdf has no dedicated partner package, and the current LangChain docs place `PyPDFLoader` in `langchain-community`, which is maintained and is not a legacy package.
4. Work happens on a new branch in a short-path worktree, so the open `feat/product-ui-modernization` branch and the app the user is testing are untouched.

## Component Map

| Stage | LangChain component | Package | Class |
|---|---|---|---|
| Load | Document Loader | `langchain-community` | `PyPDFLoader` → `list[Document]` |
| Document model | Document | `langchain-core` | `Document` |
| Split | Text Splitter | `langchain-text-splitters` | `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)` |
| Embed | Embeddings | `langchain-openai` | `OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)` |
| Store | Vector Store | `langchain-pinecone` | `PineconeVectorStore(index_name=settings.PINECONE_INDEX_NAME, embedding=...)` |
| Retrieve (candidates) | Retriever (from vector store) | `langchain-core` / `langchain-pinecone` | `vectorstore.as_retriever(search_type="similarity_score_threshold", ...)` → `VectorStoreRetriever` |
| Rerank | Document Compressor | `langchain-pinecone` | `PineconeRerank(model="bge-reranker-v2-m3", top_n=k)` (subclass of `langchain_core.documents.compressor.BaseDocumentCompressor`) |
| Retrieve (final) | Custom Retriever | `langchain-core` | `RerankingRetriever(BaseRetriever)` |

## Architecture: new package `app/rag/`

One file per component, each with a single responsibility:

- `app/rag/loaders.py`: `load_pdf(path: str, *, filename: str, source: str | None = None) -> list[Document]`. Uses `PyPDFLoader(path).load()`. When `source` is given, it overwrites `metadata["source"]` on every page; the upload path passes the bare filename, exactly as `pdf_ingest.py` does today. When `source` is omitted, the loader's own `source` (the file path) is kept, as the bulk path does today. It does **not** set `filename`; the ingestion step does, as today.
- `app/rag/splitters.py`: `build_text_splitter() -> RecursiveCharacterTextSplitter` with `chunk_size=1000` and `chunk_overlap=200`, the constants defined once.
- `app/rag/vectorstore.py`: `get_embeddings() -> OpenAIEmbeddings`, and `get_vectorstore() -> PineconeVectorStore` with `lru_cache(maxsize=1)`. It is lazy because `PineconeVectorStore.__init__` makes a network call; keeping it lazy keeps imports offline-safe for tests. This is the **single** place the store is constructed. Today it is built separately in `app/ingest.py` and `app/agent/tools/knowledge_base.py`.
- `app/rag/ingestion.py`: the indexing pipeline.
  - `chunk_id(source, page, chunk_index) -> str` and `assign_chunk_ids(splits) -> list[str]` move here **unchanged**: sha256 of `f"{source}:{page}:{chunk_index}"`, with a per-(source, page) counter.
  - `index_documents(documents: list[Document], filename: str) -> list[str]`: split with `build_text_splitter()`, set `metadata["filename"] = filename` on each split, compute the IDs, then `get_vectorstore().add_documents(splits, ids=ids)`, and return the IDs.
  - `add_documents` with explicit IDs is the vector store's standard upsert and replaces today's `PineconeVectorStore.from_documents(..., ids=ids)`. Same IDs mean an overwrite, not a duplicate.
- `app/rag/retriever.py`: retrieval.
  - Constants moved from `knowledge_base.py` with their calibration comments:
    - `RELEVANCE_THRESHOLD_COSINE = 0.35`
    - `RERANK_CANDIDATES = 20`
    - `RERANK_MODEL = "bge-reranker-v2-m3"`
  - **Threshold translation (load-bearing).** `as_retriever(search_type="similarity_score_threshold")` filters on *relevance* scores. For cosine, `PineconeVectorStore` maps them with `relevance = (cosine + 1) / 2` (`langchain_pinecone/vectorstores.py`, `_cosine_relevance_score_fn`). The retriever therefore uses `score_threshold = (RELEVANCE_THRESHOLD_COSINE + 1) / 2 = 0.675`. The mapping is monotonic, so it keeps exactly the chunks `cosine >= 0.35` keeps today.
  - `class RerankingRetriever(BaseRetriever)`, with fields:
    - `base_retriever: BaseRetriever`
    - `reranker: BaseDocumentCompressor`
    - `top_n: int`

    `_get_relevant_documents(query, *, run_manager)` does three things:
    1. `docs = base_retriever.invoke(query)`;
    2. if `docs` is empty, it returns `[]`;
    3. otherwise it tries `list(reranker.compress_documents(docs, query))`. On **any** exception it logs `KB_SEARCH: rerank failed, using vector order (...)` and returns `docs[:top_n]`, which is today's fallback.
  - `build_kb_retriever(k: int, metadata_filter: dict | None) -> RerankingRetriever`. The base retriever is `get_vectorstore().as_retriever(search_type="similarity_score_threshold", search_kwargs={"k": RERANK_CANDIDATES, "score_threshold": 0.675, "filter": metadata_filter})`, with the `filter` key omitted when `None`. The reranker is `PineconeRerank(model=RERANK_MODEL, top_n=k, pinecone_api_key=settings.PINECONE_API_KEY)`, and `top_n=k`.
  - The retriever is built per call because `k` and the filter vary per tool call. Construction is cheap: the vector store is cached.

### Callers become thin clients

- `app/ingest.py` (bulk CLI, `python -m app.ingest`): `load_pdf(os.path.join("data", file), filename=file)` → `index_documents(docs, file)`. The manifest is still overwritten (`_write_manifest`), and the printed messages are unchanged.
  - For backward compatibility, `app/ingest.py` keeps the names `_chunk_id`, `_assign_chunk_ids` (re-exported from `app.rag.ingestion`), `_write_manifest` and `embed_and_upsert_pdf_documents` (a thin alias of `index_documents`), so existing imports keep working.
- `app/data_import/pdf_ingest.py` (upload): keeps its Windows-safe temp-file handling (`delete=False`, close, unlink in `finally`). It then calls `load_pdf(tmp.name, filename=filename, source=filename)` → `index_documents(docs, filename)`. The manifest is still appended, not overwritten.
- `app/agent/tools/knowledge_base.py` (`search_knowledge_base`): keeps the parts that are not retrieval:
  - the manifest (`KB_MANIFEST_PATH`, `_list_ingested_pdfs`) and `source_filter` resolution;
  - `KBSearchInput`;
  - the "no matching document" message;
  - the citation formatting (`[Source: <filename>, page <1-based>] <content>`).

  It then calls `build_kb_retriever(k, filter_kwarg).invoke(query)`. An exception from the retriever returns `Knowledge base search failed: {exc}`, as today; this is the vector-store failure path. An empty result returns `No relevant results found in the knowledge base for this query.`, as today. `_get_vectorstore`, `_get_pinecone`, `_rerank`, `_RELEVANCE_THRESHOLD`, `_RERANK_CANDIDATES` and `_RERANK_MODEL` are removed from this module, since they now live in `app/rag/`. `web_search` is untouched.

## Behavior Equivalence (must hold)

| Aspect | Before | After |
|---|---|---|
| Chunking | Recursive splitter, 1000/200 | identical (`build_text_splitter`) |
| Chunk IDs | sha256(source:page:index) | identical function, same inputs per path |
| `metadata["filename"]` | set on every split | identical |
| Upload `source` | bare filename | identical (`load_pdf(..., source=filename)`) |
| Bulk `source` | PyPDFLoader path | identical (no override) |
| Manifest | bulk overwrites, upload appends | identical |
| Candidates | top 20 by cosine | identical (`k=20`) |
| Relevance filter | cosine ≥ 0.35 | relevance ≥ 0.675, equivalent |
| Metadata filter | `{"filename": {"$in": [...]}}` | identical, passed via `search_kwargs["filter"]` |
| Rerank | Pinecone inference `bge-reranker-v2-m3`, top_n=k | `PineconeRerank`, same model, top_n=k |
| Rerank failure | vector order, first k | identical |
| Tool output strings | as today | identical |

## Error Handling

- Vector-store or network failure during retrieval: the tool returns `Knowledge base search failed: …` and logs a warning.
- Reranker failure: logged, and the results fall back to vector order. Search never fails because of the reranker.
- Missing manifest: as today, a warning and an empty list.

## Testing

TDD, using targeted test files only. The user forbids full-suite runs. Python runs with `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui`.

- New `tests/unit/test_rag_components.py`:
  - `build_text_splitter` has chunk_size 1000 and overlap 200;
  - `load_pdf` keeps the loader's source when none is given and overrides it when given (using a fake loader);
  - `index_documents` sets `filename`, calls `add_documents` with `ids` equal to `assign_chunk_ids(splits)` (fake vector store), and returns the IDs;
  - `chunk_id` outputs equal the pre-refactor values for fixed inputs (golden values computed from the current implementation before moving it);
  - the threshold translation: the retriever's `search_kwargs["score_threshold"] == 0.675`, `k == 20`, and the filter is present or absent;
  - `RerankingRetriever` returns reranked docs, returns `docs[:top_n]` when the reranker raises, and returns `[]` without calling the reranker when there are no candidates.
- Update `tests/unit/test_knowledge_base_tools.py` to patch `app.agent.tools.knowledge_base.build_kb_retriever` or `app.rag.retriever.get_vectorstore`, plus `PineconeRerank`. Every existing behavioral assertion is preserved: message strings, filter resolution, citation format, top-k order and rerank fallback.
- Update `tests/unit/test_data_import_pdf_ingest.py` and `tests/unit/test_ingest_chunk_ids.py` to the new patch points. Their assertions are unchanged: the manifest is appended and deduplicated, chunk IDs are stable across re-uploads, and importing `app.ingest` prints nothing.
- Also run `tests/unit/test_multi_agent_rag_agent.py`, and grep that no `app/` module still constructs `PineconeVectorStore` outside `app/rag/vectorstore.py`.
- **Live equivalence check** (backend from this worktree): ask "What does Amazon's 2024 annual report say about AI?" through `/stream` and confirm `search_knowledge_base` returns chunks citing `Amazon-2024-Annual-Report.pdf`, with the same page set as a run against the pre-refactor branch for the same query. Record both outputs. Do not re-ingest live: it costs embeddings and the IDs are proven equal by unit tests.

## Documentation

- `CLAUDE.md` (Data ingestion section, and the `search_knowledge_base` tool row) and `docs/TOOLS.md` (the `search_knowledge_base` entry): describe the `app/rag/` component layout. Edit; never delete.

## Out of Scope (tracked follow-ups)

- Unifying the `source` of bulk and upload ingestion. Today a PDF ingested by both paths is stored twice. Fixing that changes existing chunk IDs and needs a migration or cleanup.
- New loaders, MMR, hybrid search, multi-query, and evaluation datasets.
