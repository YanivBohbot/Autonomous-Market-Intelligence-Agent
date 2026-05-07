# Enterprise Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the current prototype into a production-ready service with structured logging, persistent HITL session memory, proper FastAPI routing, and containerized deployment.

**Architecture:** Replace in-memory `MemorySaver` with `SqliteSaver` so HITL sessions survive server restarts. Extract FastAPI routes into dedicated router modules. Replace all `print()` calls with structured JSON logging. Containerize with Docker Compose including a healthcheck probe.

**Tech Stack:** `langgraph-checkpoint-sqlite` (SqliteSaver), FastAPI APIRouter, Python `logging` with JSON formatter, Docker Compose, pytest + pytest-mock.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `app/core/logging.py` | JSON formatter + `configure_logging()` |
| Modify | `app/core/config.py` | Add `LOG_LEVEL`, `CHECKPOINT_DB_PATH`, `API_URL` |
| Modify | `app/agent/nodes/rag.py` | Replace print → logger |
| Modify | `app/agent/nodes/grader.py` | Replace print → logger |
| Modify | `app/agent/nodes/research.py` | Replace print → logger |
| Modify | `app/agent/nodes/generate.py` | Replace print → logger |
| Modify | `app/agent/tools/emails.py` | Replace print → logger |
| Modify | `app/agent/tools/mcp_clients/mcp_client.py` | Replace print → logger |
| Modify | `app/ingest.py` | Replace print → logger |
| Create | `app/api/routers/__init__.py` | Empty package marker |
| Create | `app/api/routers/health.py` | `/health` GET endpoint |
| Create | `app/api/routers/chat.py` | `/chat` and `/approve` POST endpoints |
| Rename | `app/api/models/Models.py` → `app/api/models/models.py` | Pydantic models (PEP8 filename) |
| Modify | `app/api/server.py` | App factory — include all routers |
| Create | `app/agent/memory/__init__.py` | Empty package marker |
| Create | `app/agent/memory/checkpointer.py` | `SqliteSaver` factory |
| Modify | `app/agent/graph.py` | Use persistent checkpointer |
| Modify | `app/ui/app.py` | Read `API_URL` from env instead of hardcode |
| Create | `Dockerfile` | Single-container build |
| Create | `docker-compose.yml` | Local multi-service orchestration |
| Create | `tests/__init__.py` | Empty package marker |
| Create | `tests/unit/__init__.py` | Empty package marker |
| Create | `tests/conftest.py` | Shared `base_agent_state` fixture |
| Create | `tests/unit/test_logging.py` | JSONFormatter unit tests |
| Create | `tests/unit/test_health.py` | Health endpoint test |
| Create | `tests/unit/test_checkpointer.py` | SqliteSaver factory test |
| Create | `tests/unit/test_grader.py` | Grader node unit tests |
| Delete | `app/agent/nodes/tools.py` | Empty stub |
| Delete | `app/agent/nodes/writer.py` | Empty stub |

---

## Task 1: Structured Logging

Replace every `print()` with structured JSON logging. Add `LOG_LEVEL` to config. Call `configure_logging()` once at server startup.

**Files:**
- Create: `app/core/logging.py`
- Modify: `app/core/config.py`
- Modify: `app/agent/nodes/rag.py`, `grader.py`, `research.py`, `generate.py`
- Modify: `app/agent/tools/emails.py`, `app/agent/tools/mcp_clients/mcp_client.py`
- Create: `tests/unit/test_logging.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_logging.py
import logging
import json
from app.core.logging import configure_logging, JSONFormatter


def test_json_formatter_produces_valid_json():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello world", args=(), exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["message"] == "hello world"
    assert parsed["level"] == "INFO"
    assert "timestamp" in parsed


def test_configure_logging_sets_root_level():
    configure_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING
    configure_logging("INFO")  # reset for other tests
```

- [ ] **Step 2: Run tests to confirm failure**

```
uv run pytest tests/unit/test_logging.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.core.logging'`

- [ ] **Step 3: Create `app/core/logging.py`**

```python
import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
```

- [ ] **Step 4: Add config fields to `app/core/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    OPENAI_MODEL: str
    OPENAI_EMBEDDING_MODEL: str
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str
    TAVILY_API_KEY: str
    EMAIL_SENDER: str
    EMAIL_PASSWORD: str
    EMAIL_SMTP_SERVER: str
    EMAIL_SMTP_PORT: int
    LOG_LEVEL: str = "INFO"
    CHECKPOINT_DB_PATH: str = "data/checkpoints.db"
    API_URL: str = "http://127.0.0.1:8000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
```

- [ ] **Step 5: Replace `print()` in `app/agent/nodes/rag.py`**

```python
import logging
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from app.core.config import settings
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


def retriveal_internal_documention(state: AgentState) -> dict:
    logger.info("RAG: Starting internal document search")
    question = state["question"]
    embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
    vectorstore = PineconeVectorStore(
        index_name=settings.PINECONE_INDEX_NAME, embedding=embeddings
    )
    docs = vectorstore.similarity_search(question, k=3)
    content = [f"[INTERNAL Resource] {d.page_content}" for d in docs]
    logger.info("RAG: Retrieved %d chunks", len(content))
    return {"documents": content}
```

- [ ] **Step 6: Replace `print()` in `app/agent/nodes/grader.py`**

```python
import logging
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from app.core.config import settings
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


class GradeDocument(BaseModel):
    binary_score: str = Field(description="'yes' or 'no'")


def grade_documents(state: AgentState) -> dict:
    logger.info("GRADER: Scoring %d documents", len(state["documents"]))
    question = state["question"]
    documents = state["documents"]
    llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
    structured_llm_grader = llm.with_structured_output(GradeDocument)
    system_prompt = " the document answer to the question ? answer 'yes' ou 'no'."
    filtered_docs = []
    for doc in documents:
        res = structured_llm_grader.invoke(f"Question: {question}\nDoc: {doc}\n{system_prompt}")
        if res.binary_score == "yes":
            filtered_docs.append(doc)
    logger.info("GRADER: Kept %d/%d documents", len(filtered_docs), len(documents))
    return {"documents": filtered_docs}
```

- [ ] **Step 7: Replace `print()` in `app/agent/nodes/research.py`**

```python
import logging
from tavily import TavilyClient
from app.core.config import settings
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


def web_search(state: AgentState) -> dict:
    logger.info("WEB_SEARCH: Querying Tavily")
    question = state["question"]
    tavily = TavilyClient(api_key=settings.TAVILY_API_KEY)
    response = tavily.search(query=question, max_results=3, search_depth="advanced")
    web_results = [
        f"[SOURCE WEB: {r['url']}] {r['content']}"
        for r in response["results"]
    ]
    logger.info("WEB_SEARCH: Got %d results", len(web_results))
    return {"documents": web_results}
```

- [ ] **Step 8: Replace `print()` in `app/agent/tools/emails.py`**

```python
import logging
import smtplib
from email.mime.text import MIMEText
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailInput(BaseModel):
    recipient: str = Field(description="L'adresse email du destinataire")
    subject: str = Field(description="Le sujet de l'email")
    body: str = Field(description="Le corps du mail (le contenu principal)")


@tool("send_email", args_schema=EmailInput)
def send_email_tool(recipient: str, subject: str, body: str) -> str:
    """Utilise cet outil pour envoyer un email professionnel avec un rapport ou une réponse."""
    logger.info("SEND_EMAIL: Sending to %s", recipient)
    if "ton_email" in settings.EMAIL_SENDER or "ton_mdp" in settings.EMAIL_PASSWORD:
        logger.warning("SEND_EMAIL: Simulation mode — no real email sent")
        return f"SIMULATION SUCCÈS : Email virtuellement envoyé à {recipient} avec le sujet '{subject}'."
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_SENDER
    msg["To"] = recipient
    try:
        with smtplib.SMTP_SSL(settings.EMAIL_SMTP_SERVER, settings.EMAIL_SMTP_PORT) as server:
            server.login(settings.EMAIL_SENDER, settings.EMAIL_PASSWORD)
            server.sendmail(settings.EMAIL_SENDER, recipient, msg.as_string())
        logger.info("SEND_EMAIL: Sent successfully")
        return "Email envoyé avec succès !"
    except Exception as e:
        logger.error("SEND_EMAIL: Failed — %s", e)
        return f"Erreur critique lors de l'envoi : {str(e)}"
```

- [ ] **Step 9: Replace `print()` in `app/agent/tools/mcp_clients/mcp_client.py`**

```python
import asyncio
import logging
import os
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_core.tools import Tool

logger = logging.getLogger(__name__)

server_params = StdioServerParameters(
    command="uv",
    args=["run", "mcp-server-sqlite", "--db-path", "customers.db"],
    env=os.environ,
)


async def query_crm_tool(query: str) -> str:
    logger.info("MCP: Executing CRM query: %.80s", query)
    try:
        async with AsyncExitStack() as stack:
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(server_params)
            )
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            result = await session.call_tool("read_query", arguments={"query": query})
            if result.content and len(result.content) > 0:
                return result.content[0].text
            return "Aucun résultat trouvé."
    except Exception as e:
        logger.error("MCP: Error — %s", e)
        return f"Erreur MCP : {str(e)}"


def sync_query_wrapper(query: str) -> str:
    try:
        return asyncio.run(query_crm_tool(query))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(query_crm_tool(query))


crm_tool = Tool(
    name="crm_query",
    func=sync_query_wrapper,
    description="Exécute une requête SQL SELECT sur la base clients (table: customers). Colonnes: id, name, email, status, total_spend.",
)
```

- [ ] **Step 10: Run logging tests**

```
uv run pytest tests/unit/test_logging.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 11: Delete empty stub files**

```bash
git rm app/agent/nodes/tools.py app/agent/nodes/writer.py
```

- [ ] **Step 12: Commit**

```bash
git add app/core/logging.py app/core/config.py app/agent/nodes/ app/agent/tools/ tests/unit/test_logging.py
git commit -m "feat: replace print() with structured JSON logging, add LOG_LEVEL config"
```

---

## Task 2: FastAPI Router Extraction + Health Endpoint

Split the monolithic `server.py` into focused router modules. Add `/health` for container liveness probes.

**Files:**
- Create: `app/api/routers/__init__.py`
- Create: `app/api/routers/health.py`
- Create: `app/api/routers/chat.py`
- Rename: `app/api/models/Models.py` → `app/api/models/models.py`
- Modify: `app/api/server.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/conftest.py`
- Create: `tests/unit/test_health.py`

- [ ] **Step 1: Create empty package markers**

Create these four empty files:
- `tests/__init__.py`
- `tests/unit/__init__.py`
- `app/api/routers/__init__.py`

- [ ] **Step 2: Create `tests/conftest.py`**

```python
import pytest


@pytest.fixture
def base_agent_state():
    return {
        "question": "What is Amazon's net revenue in 2024?",
        "documents": [],
        "messages": [],
    }
```

- [ ] **Step 3: Write failing health test**

```python
# tests/unit/test_health.py
from fastapi.testclient import TestClient
from app.api.server import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "version" in response.json()
```

- [ ] **Step 4: Run test to confirm failure**

```
uv run pytest tests/unit/test_health.py -v
```
Expected: FAIL with `404 Not Found`

- [ ] **Step 5: Create `app/api/routers/health.py`**

```python
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return {"status": "ok"}
```

- [ ] **Step 6: Create `app/api/routers/chat.py`**

```python
import logging
from fastapi import APIRouter
from app.agent.graph import agent_app
from app.api.models.models import ChatRequest, ChatResponse, ApproveRequest

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_safe_content(state: dict) -> str:
    if "messages" not in state or not state["messages"]:
        return "Aucune réponse générée."
    last_msg = state["messages"][-1]
    content = last_msg.content
    if content is None:
        return ""
    if isinstance(content, list):
        return " ".join(
            c.get("text", "") for c in content if isinstance(c, dict) and "text" in c
        )
    return str(content)


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    snapshot = agent_app.get_state(config)
    if snapshot.next:
        return {
            "response": "⚠️ Une action est en attente. Utilisez /approve.",
            "status": "interrupted",
            "next_step": str(snapshot.next),
        }
    inputs = {"question": request.query}
    final_state = agent_app.invoke(inputs, config)
    snapshot = agent_app.get_state(config)
    if snapshot.next:
        last_msg = final_state["messages"][-1]
        action_desc = last_msg.content
        if not action_desc and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            tc = last_msg.tool_calls[0]
            action_desc = f"Exécuter : {tc['name']} ({tc['args']})"
        return {
            "response": f"⏸️ ACTION REQUISE : {action_desc}",
            "status": "interrupted",
            "next_step": str(snapshot.next),
        }
    return {
        "response": _get_safe_content(final_state),
        "status": "completed",
        "next_step": None,
    }


@router.post("/approve", response_model=ChatResponse)
async def approve_endpoint(request: ApproveRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    snapshot = agent_app.get_state(config)
    if not snapshot.next:
        return {
            "response": "⚠️ Session expirée ou terminée. Veuillez relancer votre demande.",
            "status": "completed",
            "next_step": None,
        }
    if request.approved:
        logger.info("Action approved for thread %s", request.thread_id)
        final_state = agent_app.invoke(None, config)
    else:
        logger.info("Action refused for thread %s", request.thread_id)
        return {
            "response": "Action annulée par l'utilisateur.",
            "status": "completed",
            "next_step": None,
        }
    snapshot = agent_app.get_state(config)
    if snapshot.next:
        last_msg = final_state["messages"][-1]
        action_desc = last_msg.content
        if not action_desc and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            tc = last_msg.tool_calls[0]
            action_desc = f"Exécuter : {tc['name']} ({tc['args']})"
        return {
            "response": f"⏸️ NOUVELLE ACTION REQUISE : {action_desc}",
            "status": "interrupted",
            "next_step": str(snapshot.next),
        }
    return {
        "response": _get_safe_content(final_state),
        "status": "completed",
        "next_step": None,
    }
```

- [ ] **Step 7: Rename models file and update content**

```bash
git mv app/api/models/Models.py app/api/models/models.py
```

Verify `app/api/models/models.py` contains:

```python
from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    query: str
    thread_id: str = "default_thread"


class ChatResponse(BaseModel):
    response: str
    status: str
    next_step: Optional[str] = None


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool
```

- [ ] **Step 8: Replace `app/api/server.py` with app factory**

```python
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.LOG_LEVEL)

from fastapi import FastAPI
from app.api.routers.chat import router as chat_router
from app.api.routers.health import router as health_router

app = FastAPI(title="Market Intelligence Agent API", version="0.1.0")
app.include_router(health_router)
app.include_router(chat_router)
```

- [ ] **Step 9: Run health test**

```
uv run pytest tests/unit/test_health.py -v
```
Expected: PASS (1 test)

- [ ] **Step 10: Commit**

```bash
git add app/api/routers/ app/api/models/models.py app/api/server.py tests/
git commit -m "refactor: split server.py into routers, add /health endpoint, fix Models.py casing"
```

---

## Task 3: Persistent SqliteSaver Checkpointer

Replace `MemorySaver` with `SqliteSaver` so approved HITL sessions are not lost when the server restarts.

**Files:**
- Create: `app/agent/memory/__init__.py`
- Create: `app/agent/memory/checkpointer.py`
- Modify: `app/agent/graph.py`
- Modify: `pyproject.toml`
- Create: `tests/unit/test_checkpointer.py`

- [ ] **Step 1: Add the sqlite checkpointer package**

```bash
uv add langgraph-checkpoint-sqlite
```

- [ ] **Step 2: Create `app/agent/memory/__init__.py`** (empty)

- [ ] **Step 3: Write failing test**

```python
# tests/unit/test_checkpointer.py
import os
from app.agent.memory.checkpointer import create_checkpointer


def test_checkpointer_creates_instance(tmp_path):
    db_path = str(tmp_path / "test_checkpoints.db")
    checkpointer = create_checkpointer(db_path)
    assert checkpointer is not None


def test_checkpointer_creates_parent_directory(tmp_path):
    db_path = str(tmp_path / "nested" / "dir" / "checkpoints.db")
    create_checkpointer(db_path)
    assert os.path.exists(os.path.dirname(db_path))
```

- [ ] **Step 4: Run test to confirm failure**

```
uv run pytest tests/unit/test_checkpointer.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.agent.memory'`

- [ ] **Step 5: Create `app/agent/memory/checkpointer.py`**

```python
import os
from langgraph.checkpoint.sqlite import SqliteSaver
from app.core.config import settings


def create_checkpointer(db_path: str | None = None) -> SqliteSaver:
    path = db_path or settings.CHECKPOINT_DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return SqliteSaver.from_conn_string(path)
```

- [ ] **Step 6: Update `app/agent/graph.py`**

```python
from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes.rag import retriveal_internal_documention
from app.agent.nodes.research import web_search
from app.agent.nodes.grader import grade_documents
from app.agent.nodes.generate import generate_answer
from langgraph.prebuilt import ToolNode, tools_condition
from app.agent.tools.emails import send_email_tool
from app.agent.tools.mcp_clients.mcp_client import crm_tool
from app.agent.memory.checkpointer import create_checkpointer


def decide_next_step(state: AgentState) -> str:
    return "generate" if state["documents"] else "web_search"


workflow = StateGraph(AgentState)
workflow.add_node("rag", retriveal_internal_documention)
workflow.add_node("grader", grade_documents)
workflow.add_node("web_search", web_search)
workflow.add_node("generate", generate_answer)
workflow.add_node("tools", ToolNode([send_email_tool, crm_tool]))

workflow.set_entry_point("rag")
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
    {"tools": "tools", END: END},
)
workflow.add_edge("tools", "generate")

checkpointer = create_checkpointer()
agent_app = workflow.compile(
    checkpointer=checkpointer,
    interrupt_before=["tools"],
)
```

- [ ] **Step 7: Run checkpointer tests**

```
uv run pytest tests/unit/test_checkpointer.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 8: Smoke-test graph compilation**

```
uv run python -c "
from app.agent.graph import agent_app
nodes = list(agent_app.get_graph().nodes.keys())
print('Nodes:', nodes)
assert 'rag' in nodes and 'generate' in nodes
print('Graph compiled with SqliteSaver — OK')
"
```
Expected: prints node list with no error

- [ ] **Step 9: Commit**

```bash
git add app/agent/memory/ app/agent/graph.py pyproject.toml tests/unit/test_checkpointer.py
git commit -m "feat: replace MemorySaver with SqliteSaver for persistent HITL sessions"
```

---

## Task 4: Grader Unit Tests

Add the foundational test for the grader node (the most logic-dense node, easiest to unit test).

**Files:**
- Create: `tests/unit/test_grader.py`

- [ ] **Step 1: Create `tests/unit/test_grader.py`**

```python
from unittest.mock import MagicMock, patch


def test_grade_keeps_relevant_document(base_agent_state):
    base_agent_state["documents"] = ["Amazon 2024 revenue was $620B."]
    mock_grader = MagicMock()
    mock_grader.invoke.return_value = MagicMock(binary_score="yes")

    with patch("app.agent.nodes.grader.ChatOpenAI") as mock_llm:
        mock_llm.return_value.with_structured_output.return_value = mock_grader
        from app.agent.nodes.grader import grade_documents
        result = grade_documents(base_agent_state)

    assert len(result["documents"]) == 1
    assert "Amazon" in result["documents"][0]


def test_grade_drops_irrelevant_document(base_agent_state):
    base_agent_state["documents"] = ["Coffee brewing techniques."]
    mock_grader = MagicMock()
    mock_grader.invoke.return_value = MagicMock(binary_score="no")

    with patch("app.agent.nodes.grader.ChatOpenAI") as mock_llm:
        mock_llm.return_value.with_structured_output.return_value = mock_grader
        from app.agent.nodes.grader import grade_documents
        result = grade_documents(base_agent_state)

    assert result["documents"] == []


def test_grade_filters_mixed_documents(base_agent_state):
    base_agent_state["documents"] = [
        "Amazon revenue was $620B in 2024.",
        "Unrelated cat content.",
    ]
    mock_grader = MagicMock()
    mock_grader.invoke.side_effect = [
        MagicMock(binary_score="yes"),
        MagicMock(binary_score="no"),
    ]

    with patch("app.agent.nodes.grader.ChatOpenAI") as mock_llm:
        mock_llm.return_value.with_structured_output.return_value = mock_grader
        from app.agent.nodes.grader import grade_documents
        result = grade_documents(base_agent_state)

    assert len(result["documents"]) == 1
    assert "Amazon" in result["documents"][0]


def test_grade_empty_documents_returns_empty(base_agent_state):
    base_agent_state["documents"] = []

    with patch("app.agent.nodes.grader.ChatOpenAI"):
        from app.agent.nodes.grader import grade_documents
        result = grade_documents(base_agent_state)

    assert result["documents"] == []
```

- [ ] **Step 2: Run test**

```
uv run pytest tests/unit/test_grader.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_grader.py
git commit -m "test: add grader node unit tests"
```

---

## Task 5: Dockerfile + Docker Compose

Containerize both services (FastAPI + Streamlit) with a health-check probe.

**Files:**
- Modify: `app/ui/app.py`
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Update `app/ui/app.py` to read `API_URL` from environment**

Replace the hardcoded line:
```python
API_URL = "http://127.0.0.1:8000"
```
With:
```python
import os
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
```

Add the import at the top of the file alongside existing imports.

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

COPY . .

RUN mkdir -p data

EXPOSE 8000 8080

CMD ["sh", "-c", \
  "uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 & \
   uv run streamlit run app/ui/app.py --server.port 8080 --server.address 0.0.0.0"]
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  agent:
    build: .
    ports:
      - "8000:8000"
      - "8080:8080"
    env_file:
      - .env
    environment:
      API_URL: "http://localhost:8000"
    volumes:
      - ./data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
```

- [ ] **Step 4: Verify Docker build**

```bash
docker build -t market-intelligence-agent .
```
Expected: build exits 0

- [ ] **Step 5: Verify health probe works inside container**

```bash
docker compose up -d
sleep 15
curl http://localhost:8000/health
docker compose down
```
Expected: `{"status":"ok","version":"0.1.0"}`

- [ ] **Step 6: Run full test suite one final time**

```
uv run pytest tests/ -v
```
Expected: All tests PASS (logging ×2, health ×1, checkpointer ×2, grader ×4)

- [ ] **Step 7: Commit**

```bash
git add Dockerfile docker-compose.yml app/ui/app.py
git commit -m "feat: add Dockerfile and Docker Compose with healthcheck"
```
