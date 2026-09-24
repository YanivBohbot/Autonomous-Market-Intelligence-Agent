# Agentic RAG Knowledge Base — Design

## Context

The single-agent graph (`app/agent/graph.py`, served by `server.py`'s
lifespan) currently runs RAG as a **fixed pre-generation pipeline**:

```
record_question → rag → grader → [generate | web_search → generate]
```

`rag` (`app/agent/nodes/rag.py`) always fires a single `similarity_search`
against Pinecone before the LLM ever sees the question. `grader`
(`app/agent/nodes/grader.py`) then makes one LLM call *per retrieved chunk*
to binary-score relevance. If nothing survives grading, `web_search`
(`app/agent/nodes/research.py`, Tavily) runs instead. Results land in
`state["documents"]` and get spliced into a transient `SystemMessage` inside
`generate_answer` right before the LLM call.

This was built and ingested against a single PDF (Amazon 2024 Annual
Report, 425 chunks — see `project_rag_live` memory). `data/` now holds 4
PDFs spanning at least two companies (Amazon, Tesla, plus two generically
named reports still unverified). The fixed one-shot pipeline doesn't fit a
multi-document knowledge base: it can't target a specific document, can't
retry with a different query, and burns a grader LLM call per chunk before
the main reasoning LLM even starts.

The multi-agent supervisor graph (`app/agent/multi_agent/`, not currently
wired into `server.py` despite an earlier cutover spec) has its own
`rag_agent` specialist. **Out of scope for this design** — this spec covers
the single-agent graph only, per explicit decision to sequence single-agent
first and revisit multi-agent as a follow-up.

## Decision: retrieval becomes agentic (tool-based), not a fixed node

Confirmed against `langchain-rag` skill's documented pattern
(`<ex-rag-with-agent>`): wrap the retriever in a `@tool`, bind it to the
LLM, let the LLM decide when to call it. This project's design matches that
pattern and extends it (source+page citation, read-only HITL gating,
idempotent ingestion) — no conflict with official LangChain guidance.

Both retrieval mechanisms — internal KB and live web — move from graph
nodes into tools available inside the existing ReAct loop
(`generate → approval → tools → generate`). The per-chunk LLM grader is
dropped: the reasoning LLM judges relevance itself when it reads tool
output, same as it already does for every other tool result (yfinance,
CRM, filesystem). This is standard practice for agentic RAG and removes
up to k sequential LLM calls per turn.

## Architecture

### New tools — `app/agent/tools/knowledge_base.py`

```python
class KBSearchInput(BaseModel):
    query: str = Field(description="...")
    k: int = Field(default=4, description="...")
    source_filter: str | None = Field(
        default=None,
        description="Optional filename substring (e.g. 'TSLA', 'Amazon') "
        "to restrict the search to one ingested document.",
    )

@tool("search_knowledge_base", args_schema=KBSearchInput)
def search_knowledge_base_tool(query: str, k: int = 4, source_filter: str | None = None) -> str:
    """Search the internal knowledge base of ingested company reports/documents.
    Use for questions about specific companies' financials, risk factors, or
    any content from ingested PDFs. Pass source_filter to target one document
    when the question names a specific company/ticker."""
```

- Reuses the `@lru_cache(maxsize=1)` lazy vectorstore pattern from
  `rag.py`.
- Switches from `vectorstore.similarity_search()` to
  `vectorstore.as_retriever(search_kwargs={"k": k, "filter": ...})` +
  `.invoke(query)` — the idiomatic LangChain `Runnable` retriever
  interface (functionally equivalent to direct `similarity_search`, but
  matches the documented pattern exactly).
- `source_filter`, when set, becomes a Pinecone metadata filter:
  `{"source": {"$in": [...]}}` matched against the `source` field
  PyPDFLoader already attaches (full path) — matching is substring-based
  at the tool layer (resolve `source_filter` against the set of known
  ingested filenames before building the exact filter), so the LLM can
  pass `"TSLA"` without knowing the exact ingested path.
- Return format: each chunk prefixed `[Source: <filename>, page <n>]`,
  joined with blank lines. Empty result set returns an explicit string
  ("No relevant results found in the knowledge base for this query.") so
  the LLM can decide to try `web_search` or rephrase, instead of a bare
  empty string.
- Error handling: try/except around the retriever call, mirrors
  `emails.py`'s convention of returning a descriptive error string rather
  than raising, so the tool-calling loop can react instead of crashing the
  thread (relevant given the prior `thread_poisoning` bug —
  `ToolNode(handle_tool_errors=True)` is already a safety net, but an
  explicit string is friendlier to the LLM's next decision).

```python
@tool("web_search", args_schema=WebSearchInput)
def web_search_tool(query: str) -> str:
    """Search the live web. Use when the knowledge base has no relevant
    information, or the question needs current/external information."""
```

- Logic moved verbatim from `app/agent/nodes/research.py` (Tavily,
  `max_results=3`, `search_depth="advanced"`), same `[SOURCE WEB: <url>]`
  prefix convention.

Both registered in `TOOLS` (`app/agent/tools/__init__.py`) and added to
`READ_ONLY_TOOLS` — no side effects, no HITL interrupt, consistent with
`yfinance_*` / `read_text_file` / etc.

### `graph.py` simplification

Removed: `rag` node, `grader` node, `web_search` node, `decide_next_step`
routing function, the `grader → [generate | web_search]` conditional edge.

Kept unchanged: `record_question`, `generate`, `approval_node`,
`route_after_approval`, `route_after_generate`, `run_tools`/`ToolNode`.

New graph:

```
START → record_question → generate → (tool_calls?) → approval → tools → generate → ... → END
```

This is the same ReAct loop structure the ecosystem-primer/langgraph
skills document — retrieval is now just two more entries in the tool
roster the loop already cycles through.

### `state.py` simplification

`documents: List[str]` field removed from `AgentState`. It existed solely
to carry `rag`/`grader`/`web_search` output into `generate_answer`'s
manual context-injection block. With retrieval as tools, results arrive as
ordinary `ToolMessage`s in `messages` — the existing, already-correct
`add_messages` reducer handles them like any other tool result.

### `generate.py` changes

Remove the `context = "\n\n".join(documents)` block and the conditional
`SystemMessage` injection (lines 18-20, 43-50 of the current file). The
prompt-caching contract (stable `SystemMessage` prefix, conversation
history next) simplifies further since there's no longer a
per-turn-variable context block breaking the cacheable prefix at all —
this was already noted as a deliberate exception in the current code's
comments; removing it is a net simplification, not a regression.

### Ingestion — `app/ingest.py`

Add deterministic per-chunk IDs so re-running ingestion after adding new
PDFs to `data/` is idempotent (no duplicate vectors for already-ingested
documents):

```python
import hashlib

def _chunk_id(source: str, page: int, chunk_index: int) -> str:
    return hashlib.sha256(f"{source}:{page}:{chunk_index}".encode()).hexdigest()
```

IDs passed to `PineconeVectorStore.from_documents(..., ids=[...])`.
Pinecone upsert semantics mean re-ingesting identical content overwrites
the same vector IDs — no explicit "check if already indexed" step needed.
`source`/`page` metadata (already attached by `PyPDFLoader`) is preserved
as-is; no changes needed there since the new `search_knowledge_base` tool
reads it directly for citation and filtering.

### Prompt updates — `app/agent/prompts/system.py`

Add `search_knowledge_base` and `web_search` to the tool list section,
including guidance to cite `[Source: filename, page N]` in the final
answer when knowledge-base content is used, and to prefer
`source_filter` when the question names a specific company/ticker.

### Cleanup

Delete `app/agent/nodes/rag.py`, `app/agent/nodes/grader.py`,
`app/agent/nodes/research.py` — logic fully migrated into
`app/agent/tools/knowledge_base.py`. Any existing tests targeting these
nodes or the old `rag → grader → generate` graph shape need updating to
reflect the new tool-based flow (exact scope determined during
implementation).

### `docs/TOOLS.md`

Per the project's standing rule (CLAUDE.md, "keep docs/TOOLS.md in sync
with TOOLS"): add both new tools to the summary table and per-tool detail
sections, and note their `READ_ONLY_TOOLS` membership, in the same change
that adds them to `TOOLS`.

## Explicitly out of scope (this spec)

- Multi-agent (`app/agent/multi_agent/`) `rag_agent` specialist — follow-up
  spec once single-agent is validated.
- Structured "report" document generation (file output, multi-section
  synthesis) — confirmed with user that "final report" currently just
  means the LLM's normal synthesized text answer; no new report artifact
  type is being built here.
- MMR search (`search_type="mmr"`) — not needed at current corpus scale (4
  documents); revisit if the KB grows large enough that near-duplicate
  chunks start crowding out diverse results.
- Multi-query / HyDE query transformation, reranking, contextual chunking
  (LLM-generated per-chunk summaries) — noted as available upgrades during
  design discussion, deferred as YAGNI at current scale.

## Testing

- Unit: `search_knowledge_base_tool` and `web_search_tool` in isolation
  (mock vectorstore / Tavily client), covering empty-result and
  error-path strings.
- Graph-shape test: confirm `graph.py`'s node/edge set matches the new
  simplified structure (no `rag`/`grader`/`web_search` nodes).
- Integration: at least one live/recorded run per new tool exercising the
  full `generate → tools → generate` loop, plus one exercising
  `source_filter` against two of the four ingested PDFs to confirm the
  metadata filter actually narrows results.
- Ingestion: re-run `ingest.py` twice against the same `data/` folder,
  confirm Pinecone vector count is stable (no duplication) via index
  stats.
