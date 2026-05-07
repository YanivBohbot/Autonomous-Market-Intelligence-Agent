# Feature Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Prerequisite:** Complete `2026-05-04-enterprise-foundation.md` first.

**Goal:** Add four high-value capabilities — long-term agent memory, multi-query RAG, token-streaming SSE, and dynamic MCP tool discovery — that make the agent demonstrably smarter and production-extensible.

**Architecture:** LangGraph `InMemoryStore` (swappable to Redis/Postgres) powers cross-session memory through two new graph nodes (`retrieve_memories`, `save_memory`). `MultiQueryRetriever` generates parallel question reformulations for better Pinecone recall. A `/stream` SSE endpoint pushes tokens via `astream_events`. `MCPToolRegistry` auto-discovers tools from any MCP server by calling `list_tools`, so adding a new data source requires zero code changes.

**Tech Stack:** LangGraph Store (`InMemoryStore`), LangChain `MultiQueryRetriever`, FastAPI `StreamingResponse` (SSE), MCP `ClientSession.list_tools()`, existing stack.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `app/agent/memory/store.py` | Singleton `InMemoryStore` factory |
| Create | `app/agent/nodes/memory.py` | `retrieve_memories` + `save_memory` graph nodes |
| Modify | `app/agent/state.py` | Add `memories: List[str]`, `user_id: str` fields |
| Modify | `app/agent/nodes/generate.py` | Inject retrieved memories into system prompt |
| Modify | `app/agent/graph.py` | Wire memory nodes, compile with store |
| Modify | `app/agent/nodes/rag.py` | Swap to `MultiQueryRetriever` |
| Create | `app/api/routers/stream.py` | `/stream` SSE endpoint |
| Modify | `app/api/server.py` | Register stream router |
| Modify | `app/api/models/models.py` | Add `StreamRequest` |
| Modify | `app/ui/app.py` | Add streaming toggle in sidebar |
| Create | `app/agent/tools/registry.py` | `MCPToolRegistry` — discovers + wraps MCP tools |
| Modify | `app/agent/tools/mcp_clients/mcp_client.py` | Use registry; expose `crm_tool` via it |
| Create | `tests/unit/test_memory_nodes.py` | Memory node unit tests |
| Create | `tests/unit/test_rag.py` | Multi-query RAG unit tests |
| Create | `tests/unit/test_registry.py` | MCPToolRegistry unit tests |

---

## Task 1: Long-Term Agent Memory (LangGraph Store)

Add `retrieve_memories` as the graph entry point and `save_memory` before END. The store persists Q&A pairs keyed by `user_id` across conversations, injected into the system prompt for context.

**Files:**
- Create: `app/agent/memory/store.py`
- Create: `app/agent/nodes/memory.py`
- Modify: `app/agent/state.py`
- Modify: `app/agent/nodes/generate.py`
- Modify: `app/agent/graph.py`
- Create: `tests/unit/test_memory_nodes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_memory_nodes.py
import pytest
from langchain_core.messages import AIMessage
from langgraph.store.memory import InMemoryStore
from app.agent.nodes.memory import retrieve_memories, save_memory


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def memory_state():
    return {
        "question": "What is AWS revenue in 2024?",
        "documents": [],
        "messages": [],
        "memories": [],
        "user_id": "test_user",
    }


def test_retrieve_memories_returns_empty_on_first_call(memory_state, store):
    result = retrieve_memories(memory_state, store)
    assert result["memories"] == []


def test_save_memory_stores_qa_pair(memory_state, store):
    memory_state["messages"] = [AIMessage(content="AWS revenue was $91B in 2024.")]
    save_memory(memory_state, store)
    results = store.search(("memories", "test_user"), query="AWS revenue", limit=5)
    assert len(results) == 1
    assert "AWS revenue" in results[0].value["content"]


def test_retrieve_memories_finds_saved_memory(memory_state, store):
    memory_state["messages"] = [AIMessage(content="AWS revenue was $91B in 2024.")]
    save_memory(memory_state, store)
    result = retrieve_memories(memory_state, store)
    assert len(result["memories"]) > 0
    assert any("AWS" in m for m in result["memories"])


def test_save_memory_skips_empty_messages(memory_state, store):
    save_memory(memory_state, store)
    results = store.search(("memories", "test_user"), query="anything", limit=5)
    assert len(results) == 0
```

- [ ] **Step 2: Run tests to confirm failure**

```
uv run pytest tests/unit/test_memory_nodes.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.agent.nodes.memory'`

- [ ] **Step 3: Create `app/agent/memory/store.py`**

```python
from langgraph.store.memory import InMemoryStore

_store: InMemoryStore | None = None


def get_store() -> InMemoryStore:
    global _store
    if _store is None:
        _store = InMemoryStore()
    return _store
```

- [ ] **Step 4: Create `app/agent/nodes/memory.py`**

```python
import logging
import uuid
from langchain_core.messages import AIMessage
from langgraph.store.base import BaseStore
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


def retrieve_memories(state: AgentState, store: BaseStore) -> dict:
    user_id = state.get("user_id", "default")
    question = state["question"]
    results = store.search(("memories", user_id), query=question, limit=3)
    memory_texts = [r.value["content"] for r in results]
    logger.info("MEMORY: Retrieved %d memories for user %s", len(memory_texts), user_id)
    return {"memories": memory_texts}


def save_memory(state: AgentState, store: BaseStore) -> dict:
    user_id = state.get("user_id", "default")
    messages = state.get("messages", [])
    if not messages:
        return {}
    last_msg = messages[-1]
    if isinstance(last_msg, AIMessage) and last_msg.content:
        store.put(
            ("memories", user_id),
            str(uuid.uuid4()),
            {"content": f"Q: {state['question']}\nA: {str(last_msg.content)[:500]}"},
        )
        logger.info("MEMORY: Saved Q&A pair for user %s", user_id)
    return {}
```

- [ ] **Step 5: Update `app/agent/state.py`**

```python
import operator
from typing import Annotated, List, TypedDict
from langchain_core.messages import AnyMessage


class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], operator.add]
    question: str
    documents: List[str]
    memories: List[str]
    user_id: str
```

- [ ] **Step 6: Update `app/agent/nodes/generate.py` to inject memories**

```python
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from app.core.config import settings
from app.agent.state import AgentState
from app.agent.tools.emails import send_email_tool
from app.agent.tools.mcp_clients.mcp_client import crm_tool

logger = logging.getLogger(__name__)


def generate_answer(state: AgentState) -> dict:
    logger.info("GENERATE: Building response")
    question = state["question"]
    documents = state["documents"]
    messages = state.get("messages", [])
    memories = state.get("memories", [])
    context = "\n\n".join(documents)
    memory_context = (
        "\n".join(f"- {m}" for m in memories)
        if memories
        else "No prior context available."
    )

    if messages:
        last_message = messages[-1]
        if isinstance(last_message, ToolMessage) and "Error" in str(last_message.content):
            logger.warning("GENERATE: Tool error detected — generating explanation")
            llm_error = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
            return {
                "messages": [
                    llm_error.invoke([
                        SystemMessage(content="L'outil a retourné une erreur technique. Analyse l'erreur, explique-la simplement à l'utilisateur et propose une solution si possible."),
                        HumanMessage(content=f"Erreur technique : {last_message.content}"),
                    ])
                ]
            }

    llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
    llm_with_tools = llm.bind_tools([send_email_tool, crm_tool])

    system_prompt = f"""Tu es un assistant expert en analyse de données et en communication.

🧠 CONTEXTE DE CONVERSATIONS PRÉCÉDENTES :
{memory_context}

🛠️ TES OUTILS :
1. `crm_query` : Pour interroger la base de données clients.
2. `send_email` : Pour envoyer des rapports ou des messages.

🗄️ SCHÉMA DE LA BASE DE DONNÉES (Table: 'customers') :
- `id` (INTEGER), `name` (TEXT), `email` (TEXT), `status` (TEXT: 'VIP'/'Standard'/'Premium'), `total_spend` (REAL)

🧠 TES INSTRUCTIONS :
- Tu es autonome pour écrire des requêtes SQL SELECT valides.
- Si on demande une action (email), vérifie d'abord si tu as l'email via le CRM.
- Utilise le contexte de conversations précédentes pour personnaliser les réponses si pertinent.
"""

    msgs = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Question Utilisateur: {question}\n\nContexte Documentaire (RAG):\n{context}"),
    ]
    if messages:
        msgs.extend(messages)

    response = llm_with_tools.invoke(msgs)
    return {"messages": [response]}
```

- [ ] **Step 7: Update `app/agent/graph.py` to wire memory nodes and store**

```python
from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes.rag import retriveal_internal_documention
from app.agent.nodes.research import web_search
from app.agent.nodes.grader import grade_documents
from app.agent.nodes.generate import generate_answer
from app.agent.nodes.memory import retrieve_memories, save_memory
from langgraph.prebuilt import ToolNode, tools_condition
from app.agent.tools.emails import send_email_tool
from app.agent.tools.mcp_clients.mcp_client import crm_tool
from app.agent.memory.checkpointer import create_checkpointer
from app.agent.memory.store import get_store


def decide_next_step(state: AgentState) -> str:
    return "generate" if state["documents"] else "web_search"


workflow = StateGraph(AgentState)
workflow.add_node("retrieve_memories", retrieve_memories)
workflow.add_node("rag", retriveal_internal_documention)
workflow.add_node("grader", grade_documents)
workflow.add_node("web_search", web_search)
workflow.add_node("generate", generate_answer)
workflow.add_node("save_memory", save_memory)
workflow.add_node("tools", ToolNode([send_email_tool, crm_tool]))

workflow.set_entry_point("retrieve_memories")
workflow.add_edge("retrieve_memories", "rag")
workflow.add_edge("rag", "grader")
workflow.add_conditional_edges(
    "grader",
    decide_next_step,
    {"generate": "generate", "web_search": "web_search"},
)
workflow.add_edge("web_search", "generate")
workflow.add_conditional_edges(
    "generate",
    tools_condition,
    {"tools": "tools", END: "save_memory"},
)
workflow.add_edge("tools", "generate")
workflow.add_edge("save_memory", END)

checkpointer = create_checkpointer()
store = get_store()
agent_app = workflow.compile(
    checkpointer=checkpointer,
    store=store,
    interrupt_before=["tools"],
)
```

- [ ] **Step 8: Run memory tests**

```
uv run pytest tests/unit/test_memory_nodes.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 9: Smoke-test graph with new nodes**

```
uv run python -c "
from app.agent.graph import agent_app
nodes = list(agent_app.get_graph().nodes.keys())
assert 'retrieve_memories' in nodes and 'save_memory' in nodes
print('Memory nodes wired — OK:', nodes)
"
```
Expected: prints all node names including `retrieve_memories` and `save_memory`

- [ ] **Step 10: Commit**

```bash
git add app/agent/memory/store.py app/agent/nodes/memory.py app/agent/state.py app/agent/nodes/generate.py app/agent/graph.py tests/unit/test_memory_nodes.py
git commit -m "feat: add long-term agent memory via LangGraph InMemoryStore"
```

---

## Task 2: Multi-Query RAG Pipeline

Replace single-vector Pinecone lookup with `MultiQueryRetriever`, which generates 3–5 question reformulations and unions the results — improving recall significantly on complex financial queries.

**Files:**
- Modify: `app/agent/nodes/rag.py`
- Create: `tests/unit/test_rag.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_rag.py
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def rag_state():
    return {
        "question": "What is Amazon's cloud revenue in 2024?",
        "documents": [],
        "messages": [],
        "memories": [],
        "user_id": "default",
    }


def test_rag_returns_internal_resource_prefix(rag_state):
    mock_doc = MagicMock()
    mock_doc.page_content = "AWS generated $91B in 2024."

    with patch("app.agent.nodes.rag.PineconeVectorStore"), \
         patch("app.agent.nodes.rag.ChatOpenAI"), \
         patch("app.agent.nodes.rag.OpenAIEmbeddings"), \
         patch("app.agent.nodes.rag.MultiQueryRetriever") as mock_mqr_class:

        mock_mqr_class.from_llm.return_value.invoke.return_value = [mock_doc]
        from app.agent.nodes.rag import retriveal_internal_documention
        result = retriveal_internal_documention(rag_state)

    assert len(result["documents"]) == 1
    assert result["documents"][0].startswith("[INTERNAL Resource]")
    assert "AWS" in result["documents"][0]


def test_rag_returns_empty_list_when_no_docs_found(rag_state):
    with patch("app.agent.nodes.rag.PineconeVectorStore"), \
         patch("app.agent.nodes.rag.ChatOpenAI"), \
         patch("app.agent.nodes.rag.OpenAIEmbeddings"), \
         patch("app.agent.nodes.rag.MultiQueryRetriever") as mock_mqr_class:

        mock_mqr_class.from_llm.return_value.invoke.return_value = []
        from app.agent.nodes.rag import retriveal_internal_documention
        result = retriveal_internal_documention(rag_state)

    assert result["documents"] == []


def test_rag_uses_multi_query_retriever(rag_state):
    with patch("app.agent.nodes.rag.PineconeVectorStore"), \
         patch("app.agent.nodes.rag.ChatOpenAI"), \
         patch("app.agent.nodes.rag.OpenAIEmbeddings"), \
         patch("app.agent.nodes.rag.MultiQueryRetriever") as mock_mqr_class:

        mock_mqr_class.from_llm.return_value.invoke.return_value = []
        from app.agent.nodes.rag import retriveal_internal_documention
        retriveal_internal_documention(rag_state)

    mock_mqr_class.from_llm.assert_called_once()
```

- [ ] **Step 2: Run tests to confirm failure**

```
uv run pytest tests/unit/test_rag.py -v
```
Expected: FAIL — `MultiQueryRetriever` not in rag.py imports

- [ ] **Step 3: Update `app/agent/nodes/rag.py`**

```python
import logging
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_pinecone import PineconeVectorStore
from langchain.retrievers.multi_query import MultiQueryRetriever
from app.core.config import settings
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


def retriveal_internal_documention(state: AgentState) -> dict:
    logger.info("RAG: Starting multi-query internal search")
    question = state["question"]

    embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
    vectorstore = PineconeVectorStore(
        index_name=settings.PINECONE_INDEX_NAME, embedding=embeddings
    )
    llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
    retriever = MultiQueryRetriever.from_llm(
        retriever=vectorstore.as_retriever(search_kwargs={"k": 3}),
        llm=llm,
    )
    docs = retriever.invoke(question)
    content = [f"[INTERNAL Resource] {d.page_content}" for d in docs]
    logger.info("RAG: Retrieved %d chunks via multi-query", len(content))
    return {"documents": content}
```

- [ ] **Step 4: Run RAG tests**

```
uv run pytest tests/unit/test_rag.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/agent/nodes/rag.py tests/unit/test_rag.py
git commit -m "feat: upgrade RAG to MultiQueryRetriever for improved document recall"
```

---

## Task 3: SSE Streaming Endpoint

Add a `/stream` POST endpoint that pushes tokens via Server-Sent Events using LangGraph's `astream_events`. The Streamlit UI gets a sidebar toggle to switch between standard and streaming mode.

**Files:**
- Modify: `app/api/models/models.py`
- Create: `app/api/routers/stream.py`
- Modify: `app/api/server.py`
- Modify: `app/ui/app.py`

- [ ] **Step 1: Add `StreamRequest` to `app/api/models/models.py`**

Append to the existing file:

```python
class StreamRequest(BaseModel):
    query: str
    thread_id: str = "default_thread"
```

- [ ] **Step 2: Create `app/api/routers/stream.py`**

```python
import json
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.agent.graph import agent_app
from app.api.models.models import StreamRequest

logger = logging.getLogger(__name__)
router = APIRouter()


async def _token_generator(request: StreamRequest):
    config = {"configurable": {"thread_id": request.thread_id}}

    snapshot = agent_app.get_state(config)
    if snapshot.next:
        data = json.dumps({
            "token": "⚠️ Une action est en attente. Utilisez /approve.",
            "status": "interrupted",
        })
        yield f"data: {data}\n\n"
        return

    inputs = {"question": request.query}
    try:
        async for event in agent_app.astream_events(inputs, config, version="v2"):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content") and chunk.content:
                    data = json.dumps({"token": chunk.content, "status": "streaming"})
                    yield f"data: {data}\n\n"
    except Exception as e:
        logger.error("STREAM: Error — %s", e)
        data = json.dumps({"token": f"Erreur: {str(e)}", "status": "error"})
        yield f"data: {data}\n\n"
        return

    snapshot = agent_app.get_state(config)
    if snapshot.next:
        final = json.dumps({"token": "", "status": "interrupted", "next_step": str(snapshot.next)})
    else:
        final = json.dumps({"token": "", "status": "completed"})
    yield f"data: {final}\n\n"


@router.post("/stream")
async def stream_endpoint(request: StreamRequest):
    return StreamingResponse(
        _token_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 3: Register stream router in `app/api/server.py`**

```python
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.LOG_LEVEL)

from fastapi import FastAPI
from app.api.routers.chat import router as chat_router
from app.api.routers.health import router as health_router
from app.api.routers.stream import router as stream_router

app = FastAPI(title="Market Intelligence Agent API", version="0.1.0")
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(stream_router)
```

- [ ] **Step 4: Add streaming toggle and streaming call to `app/ui/app.py`**

Add `import json` alongside the existing imports at the top.

Add this block immediately after the `last_action` session state init:

```python
if "use_streaming" not in st.session_state:
    st.session_state.use_streaming = False

with st.sidebar:
    st.markdown("### Settings")
    st.session_state.use_streaming = st.toggle(
        "⚡ Streaming mode", value=st.session_state.use_streaming
    )
```

Replace the existing chat input handler's API call block with:

```python
with st.chat_message("assistant"):
    with st.spinner("L'agent réfléchit..."):
        try:
            if st.session_state.use_streaming:
                response_box = st.empty()
                full_response = ""
                with requests.post(
                    f"{API_URL}/stream",
                    json={"query": prompt, "thread_id": st.session_state.thread_id},
                    stream=True,
                    timeout=120,
                ) as r:
                    for line in r.iter_lines():
                        if line and line.startswith(b"data: "):
                            payload = json.loads(line[6:])
                            if payload.get("token"):
                                full_response += payload["token"]
                                response_box.markdown(full_response)
                            status = payload.get("status")
                            if status == "interrupted":
                                st.session_state.awaiting_approval = True
                                st.session_state.last_action = payload.get("next_step", "")
                                st.rerun()
                            elif status in ("completed", "error"):
                                if full_response:
                                    st.session_state.messages.append(
                                        {"role": "assistant", "content": full_response}
                                    )
                                break
            else:
                response = requests.post(
                    f"{API_URL}/chat",
                    json={"query": prompt, "thread_id": st.session_state.thread_id},
                )
                data = response.json()
                if data["status"] == "interrupted":
                    st.session_state.awaiting_approval = True
                    st.session_state.last_action = data["response"]
                    st.warning(f"🛑 {data['response']}")
                    st.rerun()
                else:
                    st.markdown(data["response"])
                    st.session_state.messages.append(
                        {"role": "assistant", "content": data["response"]}
                    )
        except Exception as e:
            st.error(f"Erreur de connexion API : {e}")
```

- [ ] **Step 5: Manual smoke test for SSE**

Start the API:
```bash
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload
```

In a second terminal:
```bash
curl -N -X POST http://localhost:8000/stream \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"What is 2+2?\", \"thread_id\": \"stream_smoke\"}"
```
Expected: multiple `data: {...}` lines ending with `"status":"completed"`

Stop the server with Ctrl+C.

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/stream.py app/api/server.py app/api/models/models.py app/ui/app.py
git commit -m "feat: add SSE streaming endpoint and streaming toggle in Streamlit UI"
```

---

## Task 4: MCP Dynamic Tool Registry

Replace the hardcoded `crm_tool` definition with `MCPToolRegistry`, which calls `list_tools` on any MCP server at startup and wraps each discovered tool as a LangChain `Tool`. Adding a new MCP data source (e.g., a Postgres MCP server) requires only a new `StdioServerParameters` — no code changes.

**Files:**
- Create: `app/agent/tools/registry.py`
- Modify: `app/agent/tools/mcp_clients/mcp_client.py`
- Create: `tests/unit/test_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_registry.py
import os
import pytest
from unittest.mock import patch
from mcp import StdioServerParameters
from app.agent.tools.registry import MCPToolRegistry, sync_discover_mcp_tools


@pytest.fixture
def server_params():
    return StdioServerParameters(
        command="uv",
        args=["run", "mcp-server-sqlite", "--db-path", "customers.db"],
        env=os.environ,
    )


def test_registry_creates_one_tool_per_discovered_tool(server_params):
    mock_meta = [
        {"name": "read_query", "description": "Execute a SELECT SQL query."},
        {"name": "list_tables", "description": "List all tables."},
    ]
    with patch("app.agent.tools.registry.sync_discover_mcp_tools", return_value=mock_meta):
        registry = MCPToolRegistry(server_params).load()

    assert len(registry.tools) == 2
    tool_names = [t.name for t in registry.tools]
    assert "read_query" in tool_names
    assert "list_tables" in tool_names


def test_registry_preserves_tool_descriptions(server_params):
    mock_meta = [{"name": "read_query", "description": "Execute a SELECT SQL query."}]
    with patch("app.agent.tools.registry.sync_discover_mcp_tools", return_value=mock_meta):
        registry = MCPToolRegistry(server_params).load()

    assert registry.tools[0].description == "Execute a SELECT SQL query."


def test_registry_returns_empty_list_when_no_tools_discovered(server_params):
    with patch("app.agent.tools.registry.sync_discover_mcp_tools", return_value=[]):
        registry = MCPToolRegistry(server_params).load()

    assert registry.tools == []
```

- [ ] **Step 2: Run tests to confirm failure**

```
uv run pytest tests/unit/test_registry.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.agent.tools.registry'`

- [ ] **Step 3: Create `app/agent/tools/registry.py`**

```python
import asyncio
import logging
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_core.tools import Tool

logger = logging.getLogger(__name__)


async def _discover_tools_async(server_params: StdioServerParameters) -> list[dict]:
    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        response = await session.list_tools()
        return [{"name": t.name, "description": t.description} for t in response.tools]


def sync_discover_mcp_tools(server_params: StdioServerParameters) -> list[dict]:
    try:
        return asyncio.run(_discover_tools_async(server_params))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_discover_tools_async(server_params))


class MCPToolRegistry:
    def __init__(self, server_params: StdioServerParameters):
        self._server_params = server_params
        self._tools: list[Tool] = []

    def load(self) -> "MCPToolRegistry":
        discovered = sync_discover_mcp_tools(self._server_params)
        logger.info("MCP Registry: discovered tools: %s", [t["name"] for t in discovered])
        for meta in discovered:
            self._tools.append(
                Tool(
                    name=meta["name"],
                    func=self._make_invoke_fn(meta["name"]),
                    description=meta["description"],
                )
            )
        return self

    def _make_invoke_fn(self, tool_name: str):
        server_params = self._server_params

        async def _async_call(query: str) -> str:
            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(stdio_client(server_params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                result = await session.call_tool(tool_name, arguments={"query": query})
                return result.content[0].text if result.content else "No result."

        def _sync_call(query: str) -> str:
            try:
                return asyncio.run(_async_call(query))
            except RuntimeError:
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(_async_call(query))

        return _sync_call

    @property
    def tools(self) -> list[Tool]:
        return self._tools
```

- [ ] **Step 4: Update `app/agent/tools/mcp_clients/mcp_client.py`**

```python
import logging
import os
from mcp import StdioServerParameters
from app.agent.tools.registry import MCPToolRegistry
from langchain_core.tools import Tool

logger = logging.getLogger(__name__)

_server_params = StdioServerParameters(
    command="uv",
    args=["run", "mcp-server-sqlite", "--db-path", "customers.db"],
    env=os.environ,
)

_registry = MCPToolRegistry(_server_params).load()

# Wrap the MCP read_query tool under the legacy name expected by the graph and LLM prompt
_read_query = next((t for t in _registry.tools if t.name == "read_query"), None)
crm_tool = Tool(
    name="crm_query",
    func=_read_query.func if _read_query else lambda q: "CRM unavailable.",
    description=(
        "Exécute une requête SQL SELECT sur la base clients (table: customers). "
        "Colonnes: id, name, email, status, total_spend."
    ),
)

logger.info("MCP CRM tool ready: %s", crm_tool.name)
```

- [ ] **Step 5: Run registry tests**

```
uv run pytest tests/unit/test_registry.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 6: Run full test suite**

```
uv run pytest tests/ -v
```
Expected: All tests PASS (logging ×2, health ×1, checkpointer ×2, grader ×4, memory ×4, rag ×3, registry ×3)

- [ ] **Step 7: Commit**

```bash
git add app/agent/tools/registry.py app/agent/tools/mcp_clients/mcp_client.py tests/unit/test_registry.py
git commit -m "feat: add MCPToolRegistry for dynamic MCP tool discovery"
```

---

## Final Verification

- [ ] **Run full test suite one final time**

```
uv run pytest tests/ -v --tb=short
```
Expected: 19 tests, all PASS

- [ ] **Smoke test the complete graph flow**

```
uv run python -c "
from app.agent.graph import agent_app
nodes = list(agent_app.get_graph().nodes.keys())
expected = ['retrieve_memories', 'rag', 'grader', 'web_search', 'generate', 'save_memory', 'tools']
for n in expected:
    assert n in nodes, f'Missing node: {n}'
print('All nodes present:', nodes)
print('Graph smoke test — PASS')
"
```

- [ ] **Final commit**

```bash
git commit --allow-empty -m "chore: feature enhancements plan complete — memory, multi-query RAG, SSE, MCP registry"
```
