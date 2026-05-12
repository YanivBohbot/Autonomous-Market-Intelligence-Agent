# 🕵️‍♂️ Autonomous Market Intelligence Agent (LangGraph + MCP)

This project delivers an advanced, full-stack AI Agent system designed to perform complex financial research, synthesize data from diverse sources, and execute secure actions under human supervision.

## 🚀 Key Architectural Features

The agent relies on a **Cyclic State Graph** (LangGraph) for its decision-making, enabling intelligent self-correction and multi-step workflow chaining, which is more robust than standard linear RAG pipelines.

| Feature | Components | Why it Matters |
| :--- | :--- | :--- |
| **🧠 Agent Orchestration** | LangGraph, FastAPI | Manages complex, asynchronous, multi-step reasoning processes. |
| **📚 Multi-Source RAG** | Pinecone, OpenAI Embeddings | Retrieves data from static documents (e.g., Annual Reports) for deep, internal context. |
| **🔌 Structured Data (MCP)** | Model Context Protocol, SQLite | Allows the agent to query structured data (simulated CRM/Database) via a standardized client/server protocol. |
| **📈 Live Market Data** | yfinance MCP server | Real-time quotes, price history, and news headlines for any ticker. |
| **🌐 External Context** | Tavily Search API | Provides real-time web results for dynamic queries. |
| **🌍 Headless Browser** | Playwright MCP, Chromium | Lets the agent reach pages Tavily snippets can't — full article bodies, JS-rendered pricing, transcripts — and take screenshots as evidence. |
| **📁 Sandboxed Workspace** | Filesystem MCP | Read/write artifacts (briefs, CSVs, screenshots) inside `data/workspace/` — durable across sessions. |
| **🧠 Long-Term Memory** | LangGraph BaseStore (`InMemoryStore`) | Cross-thread user-facts memory — the agent remembers your email, preferences, exclusion lists without re-asking. |
| **👮‍♂️ Human-in-the-Loop (HITL)** | LangGraph dynamic `interrupt()` + `AsyncSqliteSaver` | Pauses the workflow before every side-effect action (email, file write, memory save), requiring explicit user approval via the API/UI. |
| **📧 Action Capability** | SMTP Tool | Enables the agent to perform external actions (sending reports) rather than just generating text. |

---

## 🛠️ Technical Stack

* **Agent Core:** Python 3.12+, LangGraph 1.x, LangChain
* **LLM & Embeddings:** OpenAI (GPT-4o-mini for reasoning, text-embedding-3-small for vectors)
* **Vector Database:** Pinecone (Cloud, Serverless)
* **Structured DB:** SQLite (accessed via MCP)
* **Checkpointer / State:** `AsyncSqliteSaver` (aiosqlite) for HITL resume; `InMemoryStore` for long-term memory
* **MCP Adapters:** `langchain-mcp-adapters` (`MultiServerMCPClient` registry)
* **MCP Servers:** `mcp-server-sqlite` (CRM), `yfmcp` (Yahoo Finance), `@modelcontextprotocol/server-filesystem` (workspace), `@playwright/mcp` + headless Chromium (browser)
* **Backend API:** FastAPI (async `/stream` SSE endpoint + `/approve` resume)
* **Frontend UI:** Streamlit
* **Deployment:** Docker, AWS App Runner
* **Tooling:** `uv` (Package Manager), `mcp` (Model Context Protocol SDK)

---

## 🎯 Live Demo Scenario: Chained Action & Human-in-the-Loop

This scenario showcases the agent chaining a structured data query (MCP), a document retrieval (RAG), and a secure action (Email) across multiple steps, requiring user intervention for safety.

### 1. The Complex User Prompt (Streamlit UI)

> **"Find client Yaniv Bohbot in the CRM database. If their status is VIP, send them an email summarizing Amazon's AI strategy for 2024."**

### 2. Expected Workflow and Interruptions

| Step | Action Taken by Agent | Agent Tool Called | Status in API/UI |
| :--- | :--- | :--- | :--- |
| **01** | Initial Analysis: Agent identifies the need for client data. | `read_query` | **BYPASSES HITL** (read-only) |
| **02** | Executes SQL Query (`SELECT name, email, status FROM customers WHERE name LIKE...`). | Running | Running |
| **03** | **Data Synthesis:** Agent reads SQL result and retrieves AI Strategy from Pinecone (RAG). | `send_email` | **PAUSE 1: INTERRUPTED** |
| **04** | *User Approves Action 1* | Executes SMTP Tool (Sends Email). | Completed |

### 🛠️ Available Tools (14)

The tool surface is unified through a single `MultiServerMCPClient` registry (see `app/agent/tools/mcp_clients/registry.py`). The `approval_node` gates **only** the side-effect tools; read-only tools flow straight through.

| # | Tool | Type | Backend | Description |
|---|---|---|---|---|
| 1 | `read_query` | read-only | MCP / SQLite (`mcp-server-sqlite`) | SELECT against the `customers` table. |
| 2 | `yfinance_get_ticker_info` | read-only | MCP / `yfmcp` | Current price + day stats for a ticker. |
| 3 | `yfinance_get_price_history` | read-only | MCP / `yfmcp` | Historical OHLCV bars, configurable `period`. |
| 4 | `yfinance_get_ticker_news` | read-only | MCP / `yfmcp` | Recent news headlines for a ticker. |
| 5 | `read_text_file` | read-only | MCP / filesystem | Read a UTF-8 text file from `data/workspace/`. |
| 6 | `list_directory` | read-only | MCP / filesystem | List entries inside a workspace path. |
| 7 | `write_file` | **side-effect (gated)** | MCP / filesystem | Persist a text artifact into `data/workspace/`. |
| 8 | `browser_navigate` | read-only | MCP / `@playwright/mcp` | Load a URL in headless Chromium. |
| 9 | `browser_snapshot` | read-only | MCP / `@playwright/mcp` | Return the current page as an accessibility tree (LLM-friendly structured text). |
| 10 | `browser_take_screenshot` | read-only | MCP / `@playwright/mcp` | Save a PNG of the current page into `data/workspace/screenshots/`. |
| 11 | `recall_memory` | read-only | LangGraph BaseStore | Look up a previously-saved user fact by key. |
| 12 | `list_memories` | read-only | LangGraph BaseStore | Enumerate every saved user fact. |
| 13 | `save_memory` | **side-effect (gated)** | LangGraph BaseStore | Persist a durable user fact across sessions. |
| 14 | `send_email` | **side-effect (gated)** | SMTP / Gmail | Send a real email (simulates if credentials are placeholder). |

**Note on HITL:** Read-only tools bypass the human-approval gate and execute immediately. The three gated tools (`write_file`, `save_memory`, `send_email`) pause the graph via dynamic `interrupt()`, surface the proposed action in the Streamlit modal, and resume only when the user clicks **Approve**.

---

## 📂 Workspace & Memory

The agent has a sandboxed read-write workspace at `data/workspace/`. Drop files there (UTF-8 text — CSV, markdown, JSON, etc.) and the agent can read them via `read_text_file` and `list_directory`. The agent can also save artifacts via `write_file`; saves are HITL-gated. The folder is bind-mounted into Docker, so artifacts survive container restarts.

The headless browser via `@playwright/mcp` (`browser_navigate`, `browser_snapshot`, `browser_take_screenshot`) lets the agent reach pages Tavily snippets can't — full article bodies, JS-rendered competitor pricing, investor-relations transcripts. Screenshots land in `data/workspace/screenshots/`.

Cross-thread memory uses LangGraph's `BaseStore` (`save_memory`, `recall_memory`, `list_memories`). Tell the agent "remember my email is …" once and it can use that fact in future sessions without you re-stating it. The v1 backend is `InMemoryStore` (lost on server restart); persistent `AsyncSqliteStore` is a planned follow-up.

---

## 📦 Installation and Deployment

### 1. **Setup**

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/YanivBohbot/Autonomous-Market-Intelligence-Agent.git
    cd Autonomous-Market-Intelligence-Agent/market-intelligence-agent
    ```

2.  **Install Python dependencies:**
    ```bash
    pip install uv
    uv sync
    ```

3.  **Install Node 20+ and Chromium** (for the filesystem and Playwright MCP servers — Docker handles this automatically):
    ```bash
    # On Linux/macOS, install Node 20 via your package manager, then:
    npx -y playwright install --with-deps chromium
    ```

4.  **Configuration:** Create a `.env` file with your API keys (OpenAI, Pinecone, Tavily) and SMTP credentials. `EMAIL_SENDER` containing the placeholder `ton_email` will switch the email tool to simulation mode.

### 2. **Run Locally**

The application runs two services (FastAPI backend + Streamlit UI). The FastAPI lifespan opens the `AsyncSqliteSaver` checkpointer and the `InMemoryStore` at startup.

```bash
# 1. Create the dummy SQLite database
uv run python create_db.py

# 2. (Optional) Ingest PDFs from ./data/ into Pinecone for the RAG path
uv run python app/ingest.py

# 3. Launch the FastAPI backend
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 &

# 4. Launch the Streamlit UI
uv run streamlit run app/ui/app.py --server.port 8080 --server.address 0.0.0.0
```

Open the UI at **http://localhost:8080**. Health check at **http://localhost:8000/health**, OpenAPI docs at **http://localhost:8000/docs**.

### 3. **Run in Docker**

```bash
docker compose up --build
```

The image bakes in Node 20 + Chromium and pre-pulls the filesystem and Playwright MCP packages so the first request doesn't pay a cold-start penalty.
