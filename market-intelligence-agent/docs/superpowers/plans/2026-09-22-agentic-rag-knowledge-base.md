# Agentic RAG Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn RAG retrieval into two LLM-callable tools (`search_knowledge_base`, `web_search`) so the single-agent graph searches a multi-document Pinecone knowledge base agentically instead of through a fixed `rag → grader → web_search` pre-generation pipeline.

**Architecture:** Move the vectorstore-query logic from `app/agent/nodes/rag.py` and the Tavily logic from `app/agent/nodes/research.py` into a new `app/agent/tools/knowledge_base.py`, register both as read-only tools in the existing `TOOLS` list, and delete the `rag`/`grader`/`web_search` graph nodes plus the now-unused `documents` state field. The existing ReAct loop (`generate → approval → tools → generate`) is untouched — the LLM picks up the two new tools the same way it already uses `yfinance_*`.

**Tech Stack:** LangChain (`langchain-pinecone>=0.2.13`, `PineconeVectorStore.as_retriever`), LangGraph, Tavily, pytest + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-09-22-agentic-rag-knowledge-base-design.md`

## Global Constraints

- Both new tools are read-only (no side effects) — must be added to `READ_ONLY_TOOLS` in `app/agent/tools/__init__.py`.
- `docs/TOOLS.md` must be updated in the same change that adds the tools to `TOOLS` (project rule, CLAUDE.md).
- `source_filter` matching is case-insensitive substring against ingested PDF filenames in `data/`, resolved to the exact `source` metadata values `PyPDFLoader` wrote at ingest time (`os.path.join("data", filename)`).
- Ingestion IDs must be deterministic (`sha256(f"{source}:{page}:{chunk_index}")`) so re-running `app/ingest.py` after adding new PDFs never duplicates already-ingested vectors.
- All existing MCP-backed tools (`crm_tool`, `yf_*`, `fs_*`, `browser_*`) and their HITL/approval behavior are out of scope — do not modify `app/agent/tools/mcp_clients/`.
- Multi-agent graph (`app/agent/multi_agent/`) is out of scope for this plan.

---

## Task 1: `search_knowledge_base` and `web_search` tools

**Files:**
- Create: `app/agent/tools/knowledge_base.py`
- Test: `tests/unit/test_knowledge_base_tools.py`

**Interfaces:**
- Consumes: `app.core.config.settings` (`OPENAI_EMBEDDING_MODEL`, `PINECONE_INDEX_NAME`, `TAVILY_API_KEY`) — already used identically by `app/agent/nodes/rag.py` and `app/agent/nodes/research.py`.
- Produces: `search_knowledge_base_tool` (LangChain `@tool`, name `"search_knowledge_base"`), `web_search_tool` (name `"web_search"`) — both importable from `app.agent.tools.knowledge_base`, both take a single string positional arg via Pydantic schema and return `str`.

- [ ] **Step 1: Write failing tests for `search_knowledge_base_tool`**

```python
# tests/unit/test_knowledge_base_tools.py
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.agent.tools import knowledge_base as kb_mod
from app.agent.tools.knowledge_base import search_knowledge_base_tool, web_search_tool


def _mock_retriever(docs):
    retriever = MagicMock()
    retriever.invoke.return_value = docs
    vectorstore = MagicMock()
    vectorstore.as_retriever.return_value = retriever
    return vectorstore


def test_search_returns_formatted_chunks_with_source_and_page():
    docs = [
        Document(page_content="Revenue was $100M", metadata={"source": "data/Amazon-2024-Annual-Report.pdf", "page": 12}),
    ]
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_retriever(docs)):
        result = search_knowledge_base_tool.invoke({"query": "revenue"})
    assert "[Source: Amazon-2024-Annual-Report.pdf, page 12]" in result
    assert "Revenue was $100M" in result


def test_search_returns_explicit_message_on_empty_results():
    with patch.object(kb_mod, "_get_vectorstore", return_value=_mock_retriever([])):
        result = search_knowledge_base_tool.invoke({"query": "nonexistent topic"})
    assert result == "No relevant results found in the knowledge base for this query."


def test_search_returns_explicit_message_on_vectorstore_error():
    vectorstore = MagicMock()
    vectorstore.as_retriever.side_effect = RuntimeError("Pinecone unreachable")
    with patch.object(kb_mod, "_get_vectorstore", return_value=vectorstore):
        result = search_knowledge_base_tool.invoke({"query": "revenue"})
    assert "Knowledge base search failed" in result
    assert "Pinecone unreachable" in result


def test_search_with_unmatched_source_filter_lists_available_docs():
    with patch.object(kb_mod, "_list_ingested_pdfs", return_value=["Amazon-2024-Annual-Report.pdf", "TSLA-Q2-2026-Update.pdf"]):
        result = search_knowledge_base_tool.invoke({"query": "revenue", "source_filter": "NoSuchCompany"})
    assert "No ingested document matches source_filter='NoSuchCompany'" in result
    assert "Amazon-2024-Annual-Report.pdf" in result
    assert "TSLA-Q2-2026-Update.pdf" in result


def test_search_with_matched_source_filter_builds_pinecone_filter():
    docs = [Document(page_content="Tesla delivered 500k vehicles", metadata={"source": "data/TSLA-Q2-2026-Update.pdf", "page": 3})]
    vectorstore = _mock_retriever(docs)
    with patch.object(kb_mod, "_get_vectorstore", return_value=vectorstore), \
         patch.object(kb_mod, "_list_ingested_pdfs", return_value=["Amazon-2024-Annual-Report.pdf", "TSLA-Q2-2026-Update.pdf"]):
        result = search_knowledge_base_tool.invoke({"query": "deliveries", "source_filter": "TSLA"})
    vectorstore.as_retriever.assert_called_once_with(
        search_kwargs={"k": 4, "filter": {"source": {"$in": ["data/TSLA-Q2-2026-Update.pdf"]}}}
    )
    assert "Tesla delivered 500k vehicles" in result


def test_web_search_formats_results_with_source_url():
    fake_response = {"results": [{"url": "https://example.com/news", "content": "Market news content"}]}
    with patch.object(kb_mod, "_tavily") as mock_tavily:
        mock_tavily.search.return_value = fake_response
        result = web_search_tool.invoke({"query": "market news"})
    assert "[SOURCE WEB: https://example.com/news]" in result
    assert "Market news content" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_knowledge_base_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agent.tools.knowledge_base'`

- [ ] **Step 3: Implement `app/agent/tools/knowledge_base.py`**

```python
import logging
import os
from functools import lru_cache

from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pydantic import BaseModel, Field
from tavily import TavilyClient

from app.core.config import settings

logger = logging.getLogger(__name__)

_tavily = TavilyClient(api_key=settings.TAVILY_API_KEY)


@lru_cache(maxsize=1)
def _get_vectorstore() -> PineconeVectorStore:
    """Lazy: PineconeVectorStore.__init__ makes a network call to resolve the
    index host, so we defer it past module import to keep tests offline-safe."""
    embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
    return PineconeVectorStore(
        index_name=settings.PINECONE_INDEX_NAME, embedding=embeddings
    )


def _list_ingested_pdfs(data_dir: str = "data") -> list[str]:
    if not os.path.isdir(data_dir):
        return []
    return sorted(f for f in os.listdir(data_dir) if f.lower().endswith(".pdf"))


def _resolve_source_filter(source_filter: str) -> list[str] | None:
    """Case-insensitive substring match against ingested filenames, resolved
    to the exact `source` metadata values app/ingest.py wrote (data dir +
    filename). Returns None if nothing matches."""
    matches = [
        f for f in _list_ingested_pdfs()
        if source_filter.lower() in f.lower()
    ]
    if not matches:
        return None
    return [os.path.join("data", f) for f in matches]


class KBSearchInput(BaseModel):
    query: str = Field(description="The search query against the internal knowledge base.")
    k: int = Field(default=4, description="Number of chunks to retrieve.")
    source_filter: str | None = Field(
        default=None,
        description=(
            "Optional filename substring (e.g. 'TSLA', 'Amazon') to restrict "
            "the search to one ingested document. Use when the question names "
            "a specific company or ticker."
        ),
    )


@tool("search_knowledge_base", args_schema=KBSearchInput)
def search_knowledge_base_tool(query: str, k: int = 4, source_filter: str | None = None) -> str:
    """Search the internal knowledge base of ingested company reports/documents.
    Use for questions about specific companies' financials, risk factors, or
    any content from ingested PDFs. Pass source_filter to target one document
    when the question names a specific company/ticker."""
    search_kwargs: dict = {"k": k}
    if source_filter:
        resolved = _resolve_source_filter(source_filter)
        if resolved is None:
            available = ", ".join(_list_ingested_pdfs()) or "none"
            return (
                f"No ingested document matches source_filter={source_filter!r}. "
                f"Available documents: {available}"
            )
        search_kwargs["filter"] = {"source": {"$in": resolved}}

    try:
        retriever = _get_vectorstore().as_retriever(search_kwargs=search_kwargs)
        docs = retriever.invoke(query)
    except Exception as exc:
        logger.warning("KB_SEARCH: failed (%s)", exc)
        return f"Knowledge base search failed: {exc}"

    if not docs:
        return "No relevant results found in the knowledge base for this query."

    parts = [
        f"[Source: {os.path.basename(d.metadata.get('source', 'unknown'))}, "
        f"page {d.metadata.get('page', '?')}] {d.page_content}"
        for d in docs
    ]
    return "\n\n".join(parts)


class WebSearchInput(BaseModel):
    query: str = Field(description="The web search query.")


@tool("web_search", args_schema=WebSearchInput)
def web_search_tool(query: str) -> str:
    """Search the live web. Use when the knowledge base has no relevant
    information, or the question needs current/external information."""
    try:
        response = _tavily.search(query=query, max_results=3, search_depth="advanced")
    except Exception as exc:
        logger.warning("WEB_SEARCH: failed (%s)", exc)
        return f"Web search failed: {exc}"

    results = response.get("results", [])
    if not results:
        return "No web results found for this query."

    parts = [f"[SOURCE WEB: {r['url']}] {r['content']}" for r in results]
    return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_knowledge_base_tools.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools/knowledge_base.py tests/unit/test_knowledge_base_tools.py
git commit -m "feat(agent): add search_knowledge_base and web_search as agentic RAG tools"
```

---

## Task 2: Wire tools into the registry + `docs/TOOLS.md`

**Files:**
- Modify: `app/agent/tools/__init__.py`
- Modify: `docs/TOOLS.md`

**Interfaces:**
- Consumes: `search_knowledge_base_tool`, `web_search_tool` from Task 1 (`app.agent.tools.knowledge_base`).
- Produces: `TOOLS` (list) now includes both; `READ_ONLY_TOOLS` (set) includes `"search_knowledge_base"` and `"web_search"`.

- [ ] **Step 1: Add the import and registry entries**

In `app/agent/tools/__init__.py`, add after the existing filesystem import block (after line 17):

```python
from app.agent.tools.knowledge_base import search_knowledge_base_tool, web_search_tool
```

Add `search_knowledge_base_tool, web_search_tool,` to the `TOOLS` list (after `fs_write_file_tool,`, before `*_BROWSER_TOOLS,`):

```python
TOOLS = [
    send_email_tool,
    crm_tool,
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
    fs_read_file_tool,
    fs_list_dir_tool,
    fs_write_file_tool,
    search_knowledge_base_tool,
    web_search_tool,
    *_BROWSER_TOOLS,
    save_memory_tool,
    recall_memory_tool,
    list_memories_tool,
]
```

Add `"search_knowledge_base"` and `"web_search"` to `_BASE_READ_ONLY_TOOLS`:

```python
_BASE_READ_ONLY_TOOLS: set[str] = {
    "read_query",
    "yfinance_get_ticker_info",
    "yfinance_get_price_history",
    "yfinance_get_ticker_news",
    "read_text_file",
    "list_directory",
    "browser_navigate",
    "browser_snapshot",
    "browser_take_screenshot",
    "recall_memory",
    "list_memories",
    "search_knowledge_base",
    "web_search",
}
```

Add both symbols to `__all__` (after `"fs_write_file_tool",`):

```python
    "search_knowledge_base_tool",
    "web_search_tool",
```

- [ ] **Step 2: Verify the integrity guard passes**

Run: `uv run python -c "from app.agent.tools import TOOLS, READ_ONLY_TOOLS; print(len(TOOLS)); print('search_knowledge_base' in READ_ONLY_TOOLS)"`
Expected: prints a tool count and `True`, no `RuntimeError` from the `_missing` guard at the bottom of `__init__.py`.

- [ ] **Step 3: Update `docs/TOOLS.md`**

Add two rows to the summary table (after row 14, `save_memory`):

```markdown
| 15 | `search_knowledge_base` | read-only | Pinecone (native) | query, k (default 4), source_filter (optional) | Semantic search over ingested company reports/PDFs. Returns chunks prefixed `[Source: filename, page N]`. `source_filter` restricts to one document by filename substring. | Lets the agent pull grounded facts from ingested reports on demand, as part of its own reasoning loop, instead of a fixed pre-fetch step. |
| 16 | `web_search` | read-only | Tavily (native) | query | Live web search, top 3 results, advanced depth. | Fallback / supplement when the knowledge base has no relevant ingested document for the question. |
```

Update the `READ_ONLY_TOOLS` line (after the table) to include both new names:

```markdown
`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot", "recall_memory", "list_memories", "search_knowledge_base", "web_search"}` — the allowlist consulted by `approval_node` to skip the HITL interrupt for safe reads.
```

Add two per-tool detail sections (after section `14. save_memory`, before the `> **Persistence note:**` line):

```markdown
### 15. `search_knowledge_base`
- **File:** `app/agent/tools/knowledge_base.py`
- **What:** Runs a similarity search against the Pinecone-indexed knowledge base of ingested PDFs, via `vectorstore.as_retriever().invoke(query)`. Returns each chunk prefixed with its source filename and page number. `source_filter` (optional) narrows the search to one document by case-insensitive filename substring match, resolved against `data/*.pdf` at call time.
- **Why:** Replaces the old fixed `rag → grader` pipeline. The LLM now decides when retrieval is useful, how many times to call it, and with which query — standard agentic RAG. Citation (source + page) lets the agent ground claims when multiple reports are ingested, and `source_filter` avoids cross-document noise when the question names a specific company.

### 16. `web_search`
- **File:** `app/agent/tools/knowledge_base.py`
- **What:** Tavily advanced search, top 3 results, each prefixed `[SOURCE WEB: <url>]`.
- **Why:** Replaces the old fixed `web_search` fallback node. The LLM calls it directly when the knowledge base has nothing relevant, or when the question needs current/external information the ingested PDFs can't have.
```

- [ ] **Step 4: Commit**

```bash
git add app/agent/tools/__init__.py docs/TOOLS.md
git commit -m "feat(agent): register search_knowledge_base and web_search as read-only tools"
```

---

## Task 3: Update `SYSTEM_PROMPT` for the new tools

**Files:**
- Modify: `app/agent/prompts/system.py`

**Interfaces:**
- Consumes: nothing new (pure prompt text change).
- Produces: `SYSTEM_PROMPT` now documents `search_knowledge_base`/`web_search` and drops the stale "Use the provided context (RAG documents...)" closing line.

- [ ] **Step 1: Insert a new tool section**

In `app/agent/prompts/system.py`, insert before the `Side effects (require human approval):` line (currently line 33):

```
Knowledge base & web (read-only):
14. `search_knowledge_base` — search ingested company reports/documents (args: `query: str`, optional `k: int` default 4, optional `source_filter: str` to target one document by filename substring, e.g. "TSLA" or "Amazon"). Cite results as "[Source: <filename>, page <N>]" when you use them in your answer.
15. `web_search` — search the live web (args: `query: str`). Use when the knowledge base has nothing relevant, or the question needs current/external information.
```

Renumber the existing `send_email` entry from `14.` to `16.`:

```
Side effects (require human approval):
16. `send_email` — send a report or message.
```

- [ ] **Step 2: Replace the stale closing line**

Replace (current line 77):

```
Use the provided context (RAG documents and conversation history) to answer precisely.
```

with:

```
When a question is about a specific company, product, or ingested report, search the knowledge base before answering from general knowledge. Cite sources (filename + page, or web URL) when you use retrieved content in your answer.
```

- [ ] **Step 3: Sanity-check the prompt still imports cleanly**

Run: `uv run python -c "from app.agent.prompts.system import SYSTEM_PROMPT; assert 'search_knowledge_base' in SYSTEM_PROMPT; print('ok')"`
Expected: prints `ok`

- [ ] **Step 4: Commit**

```bash
git add app/agent/prompts/system.py
git commit -m "docs(agent): document search_knowledge_base and web_search in the system prompt"
```

---

## Task 4: Simplify `AgentState` and `generate_answer`

**Files:**
- Modify: `app/agent/state.py`
- Modify: `app/agent/nodes/generate.py`
- Test: `tests/unit/test_generate_answer.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `AgentState` (TypedDict) with only `messages` and `question` — no `documents` field. `generate_answer(state)` no longer reads `state["documents"]`.

- [ ] **Step 1: Write a failing test asserting `generate_answer` works without a `documents` key**

```python
# tests/unit/test_generate_answer.py
from unittest.mock import patch

from langchain_core.messages import AIMessage

from app.agent.nodes import generate as generate_mod
from app.agent.nodes.generate import generate_answer


def test_generate_answer_does_not_require_documents_key():
    state = {"question": "What is Amazon's revenue?", "messages": []}
    with patch.object(generate_mod, "_llm_with_tools") as mock_llm:
        mock_llm.invoke.return_value = AIMessage(content="Answer")
        result = generate_answer(state)
    assert result["messages"][0].content == "Answer"


def test_generate_answer_does_not_inject_documents_context():
    state = {"question": "What is Amazon's revenue?", "messages": []}
    with patch.object(generate_mod, "_llm_with_tools") as mock_llm:
        mock_llm.invoke.return_value = AIMessage(content="Answer")
        generate_answer(state)
    sent_messages = mock_llm.invoke.call_args[0][0]
    assert not any(
        "Reference material retrieved for this turn" in getattr(m, "content", "")
        for m in sent_messages
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_generate_answer.py -v`
Expected: FAIL — `KeyError: 'documents'` (current `generate_answer` reads `state["documents"]` unconditionally at line 18)

- [ ] **Step 3: Remove `documents` from `AgentState`**

In `app/agent/state.py`, remove the `documents` field:

```python
from typing import Annotated, List, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    question: str
```

- [ ] **Step 4: Remove the context-injection block from `generate_answer`**

In `app/agent/nodes/generate.py`, remove the `documents = state["documents"]` line and the `context`/injection block. New `generate_answer`:

```python
def generate_answer(state: AgentState) -> dict:
    logger.info("GENERATE: Building response")
    messages = state.get("messages", [])

    if messages:
        last_message = messages[-1]
        if isinstance(last_message, ToolMessage) and getattr(last_message, "status", None) == "error":
            logger.warning("GENERATE: Tool error detected — generating explanation")
            return {
                "messages": [
                    _llm.invoke([
                        SystemMessage(content=ERROR_RECOVERY_PROMPT),
                        HumanMessage(content=f"Technical error: {last_message.content}"),
                    ])
                ]
            }

    msgs = [SystemMessage(content=SYSTEM_PROMPT), *messages]
    response = _llm_with_tools.invoke(msgs)
    return {"messages": [response]}
```

Also remove the now-unused `question = state["question"]` line if nothing else in the function reads it, and the `from app.agent.tools import TOOLS` import stays (still used for `_llm_with_tools`). Double check no other line in the file references `documents` or `context` before finishing this step.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_generate_answer.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full unit suite to catch state-shape breakage elsewhere**

Run: `uv run pytest tests/ -v`
Expected: `tests/unit/test_grader.py` fails (module will be deleted in Task 5). All other tests pass. If any other test fails with a `documents`-related error, note it — it will be handled in Task 5's graph cleanup.

- [ ] **Step 7: Commit**

```bash
git add app/agent/state.py app/agent/nodes/generate.py tests/unit/test_generate_answer.py
git commit -m "refactor(agent): drop documents field from AgentState, remove context injection"
```

---

## Task 5: Simplify `graph.py`, delete old nodes, update graph-structure tests

**Files:**
- Modify: `app/agent/graph.py`
- Delete: `app/agent/nodes/rag.py`
- Delete: `app/agent/nodes/grader.py`
- Delete: `app/agent/nodes/research.py`
- Delete: `tests/unit/test_grader.py`
- Create: `tests/unit/test_graph_structure.py`

**Interfaces:**
- Consumes: `TOOLS` from Task 2 (already includes the new tools; `ToolNode(TOOLS, ...)` picks them up with no code change).
- Produces: `build_agent_app(checkpointer, store)` — same signature as before — compiles a 4-node graph: `record_question`, `generate`, `approval`, `tools`.

- [ ] **Step 1: Write the failing graph-structure test**

```python
# tests/unit/test_graph_structure.py
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import build_agent_app


def _build():
    return build_agent_app(InMemorySaver())


def test_graph_compiles():
    _build()


def test_graph_has_exactly_the_expected_nodes():
    nodes = set(_build().get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"record_question", "generate", "approval", "tools"}


def test_graph_no_longer_has_rag_pipeline_nodes():
    nodes = _build().get_graph().nodes
    for removed in ("rag", "grader", "web_search"):
        assert removed not in nodes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_graph_structure.py -v`
Expected: FAIL — current graph has 7 nodes, `test_graph_has_exactly_the_expected_nodes` fails the set comparison.

- [ ] **Step 3: Rewrite `app/agent/graph.py`**

Remove the `decide_next_step` function, remove the `from app.agent.nodes.rag import retrieve_internal_documentation` and `from app.agent.nodes.research import web_search` imports, remove the `from app.agent.nodes.grader import grade_documents` import. Remove `workflow.add_node("rag", ...)`, `workflow.add_node("grader", ...)`, `workflow.add_node("web_search", ...)`, the `grader`-related conditional edges, and the `web_search → generate` edge. New wiring:

```python
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore
from langgraph.types import interrupt
from langchain_core.messages import HumanMessage, ToolMessage
from app.agent.state import AgentState
from app.agent.nodes.generate import generate_answer
from app.agent.tools import TOOLS, READ_ONLY_TOOLS, is_read_only
from app.agent.nodes.tool_utils import strip_image_content as _strip_image_content


def record_question(state: AgentState) -> dict:
    """Persist the user's turn as a HumanMessage so it shows up in checkpointed
    history. Without this, state.question is only used by the RAG/web nodes
    and never reaches state.messages, so cross-turn recall ("what did I ask
    before?") is impossible — the LLM only sees its own past responses.
    """
    q = state.get("question")
    if not q:
        return {}
    return {"messages": [HumanMessage(content=q)]}


def route_after_generate(state: AgentState):
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "approval"
    return END


def approval_node(state: AgentState) -> dict:
    """Pause graph execution and surface pending side-effect tool calls for human review.

    Read-only tool calls (per READ_ONLY_TOOLS allowlist) bypass the interrupt and execute
    immediately. Mixed batches follow the interrupt-if-any rule: if any call is a side
    effect, the node interrupts and surfaces the side-effect call(s) to the human.
    Resumer passes 'approve' to proceed or 'reject' to cancel; on reject, every tool
    call in the batch (read-only or not) is cancelled with a ToolMessage."""
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []

    side_effect_calls = [tc for tc in tool_calls if not is_read_only(tc["name"])]
    if not side_effect_calls:
        return {}

    requests = [
        {
            "action_request": {"action": tc["name"], "args": tc["args"]},
            "config": {
                "allow_ignore": False,
                "allow_respond": False,
                "allow_edit": False,
                "allow_accept": True,
            },
            "description": f"Approve or reject {tc['name']} with args {tc['args']}",
        }
        for tc in side_effect_calls
    ]
    decisions = interrupt(requests)
    if isinstance(decisions, str):
        raw = [decisions] * len(side_effect_calls)
    elif isinstance(decisions, list) and decisions:
        raw = decisions * len(side_effect_calls) if len(decisions) == 1 else decisions
    else:
        raw = ["reject"] * len(side_effect_calls)
    normalized = [
        d.get("type", "reject") if isinstance(d, dict) else d
        for d in raw
    ]
    if normalized and all(d == "approve" for d in normalized):
        return {}
    cancel_msgs = [
        ToolMessage(content="Action cancelled by user.", tool_call_id=t["id"], name=t["name"])
        for t in tool_calls
    ]
    return {"messages": cancel_msgs}


def route_after_approval(state: AgentState):
    last = state["messages"][-1]
    if isinstance(last, ToolMessage):
        return "generate"
    return "tools"


_tool_node = ToolNode(TOOLS, handle_tool_errors=True)


async def run_tools(state: AgentState) -> dict:
    result = await _tool_node.ainvoke(state)
    for msg in result.get("messages", []):
        if isinstance(msg, ToolMessage):
            msg.content = _strip_image_content(msg.content)
    return result


workflow = StateGraph(AgentState)
workflow.add_node("record_question", record_question)
workflow.add_node("generate", generate_answer)
workflow.add_node("approval", approval_node)
workflow.add_node("tools", run_tools)

workflow.add_edge(START, "record_question")
workflow.add_edge("record_question", "generate")
workflow.add_conditional_edges(
    "generate",
    route_after_generate,
    {"approval": "approval", END: END},
)
workflow.add_conditional_edges(
    "approval",
    route_after_approval,
    {"tools": "tools", "generate": "generate"},
)
workflow.add_edge("tools", "generate")


def build_agent_app(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
):
    """Compile the workflow with the supplied checkpointer and optional store.

    Compilation is deferred from module load so the FastAPI lifespan can open an
    `AsyncSqliteSaver` (which requires a running event loop) and pass it in.
    The `store` is the cross-thread long-term memory (LangGraph's BaseStore API).
    Tests that only inspect graph structure can omit the store.
    """
    return workflow.compile(checkpointer=checkpointer, store=store)
```

- [ ] **Step 4: Delete the now-unused node files and their test**

```bash
git rm app/agent/nodes/rag.py app/agent/nodes/grader.py app/agent/nodes/research.py tests/unit/test_grader.py
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_graph_structure.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full unit suite**

Run: `uv run pytest tests/ -v`
Expected: PASS. If `tests/unit/test_hitl_interrupt.py` or `tests/conftest.py` still construct state dicts with a `"documents": []` key, leave them — `AgentState` is a `TypedDict` (not runtime-enforced), so an extra key in a literal dict does not break anything. Fix only if a test actually fails.

- [ ] **Step 7: Commit**

```bash
git add app/agent/graph.py
git commit -m "refactor(agent): simplify graph to record_question->generate->approval->tools, drop rag/grader/web_search nodes"
```

---

## Task 6: Simplify the voice graph

**Files:**
- Modify: `app/voice/graph.py`

**Interfaces:**
- Consumes: `generate_answer` (Task 4 signature — no longer touches `documents`), `AgentState` (Task 4 — no `documents` field).
- Produces: `build_voice_agent_app(checkpointer, store)` — same signature, 3-node graph (`generate`, `approval`, `tools`), no `init` node.

**Context:** `app/voice/graph.py` previously needed an `init` node to pre-populate `documents=[]` because `generate_answer` read `state["documents"]` unconditionally and voice skipped the `rag`/`grader` nodes that would otherwise have set it. Task 4 removed that read entirely, so the workaround is no longer needed — and voice conversations now gain access to `search_knowledge_base`/`web_search` as tools the LLM can opt into per-turn, instead of never having KB access at all.

- [ ] **Step 1: Rewrite `app/voice/graph.py`**

```python
"""Voice-mode LangGraph.

A simplified copy of `app.agent.graph` that skips the HITL-irrelevant
`record_question` bookkeeping node (voice turns are driven by the
delegation worker, not the /stream API). Retrieval (`search_knowledge_base`,
`web_search`) is available the same way it is in text mode: as ordinary
tools the LLM opts into per turn, so voice pays no fixed retrieval latency
tax on every conversational turn.

The remaining flow (`generate` → `approval` → `tools` → ...) is reused
unchanged so voice turns still get the same MCP tools, HITL approval,
and SQLite checkpointing.
"""
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.store.base import BaseStore

from app.agent.graph import approval_node, route_after_approval, route_after_generate, run_tools
from app.agent.nodes.generate import generate_answer
from app.agent.state import AgentState


voice_workflow = StateGraph(AgentState)
voice_workflow.add_node("generate", generate_answer)
voice_workflow.add_node("approval", approval_node)
voice_workflow.add_node("tools", run_tools)

voice_workflow.add_edge(START, "generate")
voice_workflow.add_conditional_edges(
    "generate",
    route_after_generate,
    {"approval": "approval", END: END},
)
voice_workflow.add_conditional_edges(
    "approval",
    route_after_approval,
    {"tools": "tools", "generate": "generate"},
)
voice_workflow.add_edge("tools", "generate")


def build_voice_agent_app(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
):
    """Compile the voice-mode graph. Same checkpointer/store as text mode so
    voice and text can share threads if desired (today they use separate
    `thread_id`s)."""
    return voice_workflow.compile(checkpointer=checkpointer, store=store)
```

- [ ] **Step 2: Add a graph-structure test for the voice graph**

```python
# tests/unit/test_voice_graph_structure.py
from langgraph.checkpoint.memory import InMemorySaver

from app.voice.graph import build_voice_agent_app


def test_voice_graph_compiles():
    build_voice_agent_app(InMemorySaver())


def test_voice_graph_has_no_init_node():
    nodes = set(build_voice_agent_app(InMemorySaver()).get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"generate", "approval", "tools"}
```

- [ ] **Step 3: Run test**

Run: `uv run pytest tests/unit/test_voice_graph_structure.py -v`
Expected: PASS (2 tests)

- [ ] **Step 4: Run the full unit suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/voice/graph.py tests/unit/test_voice_graph_structure.py
git commit -m "refactor(voice): drop init/_init_voice_state workaround now that generate_answer doesn't read documents"
```

---

## Task 7: Idempotent ingestion (deterministic chunk IDs)

**Files:**
- Modify: `app/ingest.py`
- Test: `tests/unit/test_ingest_chunk_ids.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_chunk_id(source: str, page: int, chunk_index: int) -> str`, `_assign_chunk_ids(splits: list[Document]) -> list[str]` — both importable from `app.ingest` for testing; `ingest_document()` passes `ids=` to `PineconeVectorStore.from_documents`.

- [ ] **Step 1: Write failing tests for deterministic ID assignment**

```python
# tests/unit/test_ingest_chunk_ids.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ingest_chunk_ids.py -v`
Expected: FAIL — `ImportError: cannot import name '_assign_chunk_ids'`

- [ ] **Step 3: Implement deterministic IDs in `app/ingest.py`**

```python
import hashlib
import os
from collections import defaultdict
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from app.core.config import settings


def _chunk_id(source: str, page: int, chunk_index: int) -> str:
    return hashlib.sha256(f"{source}:{page}:{chunk_index}".encode()).hexdigest()


def _assign_chunk_ids(splits) -> list[str]:
    """Deterministic per-chunk IDs so re-running ingestion is idempotent:
    Pinecone upsert with the same ID overwrites rather than duplicates."""
    counts: dict[tuple[str, int], int] = defaultdict(int)
    ids = []
    for doc in splits:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", 0)
        chunk_index = counts[(source, page)]
        counts[(source, page)] += 1
        ids.append(_chunk_id(source, page, chunk_index))
    return ids


def ingest_document():
    """

    Read PDF from data folder et index in pinecone
    """
    print(" Starting to ingest to pinecone....")

    data_folder = "data"
    documents = []

    if not os.path.exists(data_folder):
        os.makedirs(data_folder)
        print(f"⚠️ Folder '{data_folder}' created. Put some PDFs and restar.")
        return

    for file in os.listdir(data_folder):
        if file.endswith(".pdf"):
            pdf_path = os.path.join(data_folder, file)
            print(f" Charge the {file}..")
            loader = PyPDFLoader(pdf_path)
            documents.extend(loader.load())

    if not documents:
        print("❌ No document PDF found.")
        return

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)

    splits = text_splitter.split_documents(documents)
    print(f"✂️ Documents découpés en {len(splits)} chunks.")

    ids = _assign_chunk_ids(splits)

    print("cw Stockage dans Pinecone (cela peut prendre quelques secondes)...")

    embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)

    PineconeVectorStore.from_documents(
        documents=splits, embedding=embeddings, index_name=settings.PINECONE_INDEX_NAME, ids=ids
    )


print("✅ Ingestion  finish ! Base Knowledge ready .")


if __name__ == "__main__":
    ingest_document()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ingest_chunk_ids.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full unit suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/ingest.py tests/unit/test_ingest_chunk_ids.py
git commit -m "feat(ingest): deterministic per-chunk IDs so re-ingestion is idempotent"
```

---

## Task 8: Manual end-to-end verification against the real knowledge base

**Files:** none (verification only — no code changes)

**Interfaces:** none.

- [ ] **Step 1: Re-ingest all 4 PDFs currently in `data/` with the new idempotent ingest**

Run: `uv run python create_db.py` (if `customers.db` isn't already present) then `uv run python app/ingest.py`
Expected: completes without error, prints chunk count for all 4 PDFs (`Amazon-2024-Annual-Report.pdf`, `TSLA-Q2-2026-Update.pdf`, `2026-Annual-Report-Web.pdf`, `annual-report.pdf`).

- [ ] **Step 2: Confirm idempotency — re-run ingestion and check Pinecone vector count is stable**

Run: `uv run python app/ingest.py` a second time, then check the index's vector count via the Pinecone console or `uv run python -c "from app.agent.tools.knowledge_base import _get_vectorstore; print(_get_vectorstore()._index.describe_index_stats())"`
Expected: `total_vector_count` after the second run equals the count after the first run (no duplication).

- [ ] **Step 3: Run the smoke test to confirm the agent calls the new tools appropriately**

Run: `uv run python test_agent.py`
Expected: for `q1` ("Quel est le revenu net d'Amazon en 2024 ?"), the agent calls `search_knowledge_base` (visible in the tool-call trace / final answer citing `[Source: Amazon-2024-Annual-Report.pdf, page N]`) rather than answering from parametric knowledge alone. `q2` (Tesla stock price) still uses `yfinance_get_ticker_info` unaffected. `q3` (AWS summary + email) still completes the HITL approval flow for `send_email`.

- [ ] **Step 4: Manually test `source_filter` via a one-off Python REPL**

Run:
```bash
uv run python -c "
from app.agent.tools.knowledge_base import search_knowledge_base_tool
print(search_knowledge_base_tool.invoke({'query': 'vehicle deliveries', 'source_filter': 'TSLA'}))
"
```
Expected: returned chunks are all prefixed with a Tesla-related source filename, not Amazon or the other two reports.

- [ ] **Step 5: Start the API and confirm a real `/stream` turn uses the new tools end-to-end**

Run: `uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload`, then from another terminal:
```bash
curl -N -X POST http://localhost:8000/stream -H "Content-Type: application/json" -d '{"query": "What were Amazon'\''s main risk factors in 2024?", "thread_id": "kb_verify_1"}'
```
Expected: SSE stream shows a `node: tools` event, the final answer cites the Amazon report by name/page, and the stream ends with a `done` event (no `error`).

- [ ] **Step 6: Record the outcome**

No commit for this task (verification only). If any step fails, stop and fix the relevant earlier task before considering the plan complete.
