# 🕵️‍♂️ Autonomous Market Intelligence Agent (LangGraph + MCP)

This project delivers an advanced, full-stack AI Agent system designed to perform complex financial research, synthesize data from diverse sources, and execute secure actions under human supervision.

## 🚀 Key Architectural Features

The agent relies on a **Cyclic State Graph** (LangGraph) for its decision-making, enabling intelligent self-correction and multi-step workflow chaining, which is more robust than standard linear RAG pipelines.

| Feature | Components | Why it Matters |
| :--- | :--- | :--- |
| **🧠 Agent Orchestration** | LangGraph, FastAPI | Manages complex, asynchronous, multi-step reasoning processes. |
| **📚 Multi-Source RAG** | Pinecone, OpenAI Embeddings | Retrieves data from static documents (e.g., Annual Reports) for deep, internal context. |
| **🔌 Structured Data (MCP)** | Model Context Protocol, SQLite | Allows the agent to query structured data (simulated CRM/Database) via a standardized client/server protocol. |
| **🌐 External Context** | Tavily Search API | Provides real-time web results for dynamic queries (e.g., current stock prices). |
| **👮‍♂️ Human-in-the-Loop (HITL)** | LangGraph Checkpointing | Pauses the workflow before critical external actions (like sending an email), requiring explicit user approval via the API/UI. |
| **📧 Action Capability** | SMTP Tool | Enables the agent to perform external actions (sending reports) rather than just generating text. |

---

## 🛠️ Technical Stack

* **Agent Core:** Python 3.11+, LangGraph, LangChain
* **LLM & Embeddings:** OpenAI (GPT-4o-mini for reasoning, text-embedding-3-small for vectors)
* **Vector Database:** Pinecone (Cloud, Serverless)
* **Structured DB:** SQLite (accessed via MCP)
* **Backend API:** FastAPI (Async Endpoints for Chat/Approve)
* **Frontend UI:** Streamlit
* **Deployment:** Docker, AWS App Runner
* **Tooling:** `uv` (Package Manager), `mcp` (Model Context Protocol SDK)

---

## 🎯 Live Demo Scenario: Chained Action & Human-in-the-Loop

This scenario showcases the agent's ability to chain a structured data query (MCP), a document retrieval (RAG), and a secure action (Email) across multiple steps, requiring user intervention for safety.

### 1. The Complex User Prompt (Streamlit UI)

> **"Find client Yaniv Bohbot in the CRM database. If their status is VIP, send them an email summarizing Amazon's AI strategy for 2024."**

### 2. Expected Workflow and Interruptions

| Step | Action Taken by Agent | Agent Tool Called | Status in API/UI |
| :--- | :--- | :--- | :--- |
| **01** | Initial Analysis: Agent identifies the need for client data. | `read_query` | **BYPASSES HITL** (read-only) |
| **02** | Executes SQL Query (`SELECT name, email, status FROM customers WHERE name LIKE...`). | Running | Running |
| **03** | **Data Synthesis:** Agent reads SQL result and retrieves IA Strategy from Pinecone (RAG). | `send_email` | **PAUSE 1: INTERRUPTED** |
| **04** | *User Approves Action 1* | Executes SMTP Tool (Sends Email). | Completed |

### 🛠️ Available Tools

| Tool | Type | Description |
|---|---|---|
| `read_query` | read-only (MCP / SQLite) | SELECT against the `customers` table; bypasses HITL approval |
| `yfinance_get_ticker_info` | read-only (MCP / yfinance) | Current price and day stats for a ticker; bypasses HITL approval |
| `yfinance_get_price_history` | read-only (MCP / yfinance) | Historical prices, configurable period; bypasses HITL approval |
| `yfinance_get_ticker_news` | read-only (MCP / yfinance) | Recent news headlines for a ticker; bypasses HITL approval |
| `read_text_file` | read-only (MCP / filesystem) | Read a text file from the workspace; bypasses HITL approval |
| `list_directory` | read-only (MCP / filesystem) | List files/directories inside the workspace; bypasses HITL approval |
| `write_file` | side-effect (MCP / filesystem) | Write a file to the workspace; requires HITL approval before execution |
| `send_email` | side-effect (SMTP) | Sends email via Gmail; requires HITL approval before execution |

**Note on HITL:** Read-only tools (data queries) bypass the human-approval gate and execute immediately, improving agent responsiveness. Side-effect tools (like `send_email`) still require explicit user approval via the API/UI before execution.

---

## Workspace folder

The agent has a sandboxed read-write workspace at `data/workspace/`. Drop files there (text only — UTF-8 CSV, markdown, JSON, etc.) and the agent can read them via `read_text_file` and `list_directory`. The agent can also save artifacts (briefs, snapshots) via `write_file`; saves are gated by HITL approval. The folder is bind-mounted into Docker, so artifacts survive container restarts.

---

## 📦 Installation and Deployment

### 1. **Setup**

1.  **Clone the Repository:**
    ```bash
    git clone [https://github.com/your-username/market-intelligence-agent.git](https://github.com/your-username/market-intelligence-agent.git)
    cd market-intelligence-agent
    ```

2.  **Install Dependencies:**
    ```bash
    pip install uv
    uv sync
    ```

3.  **Configuration:** Create a `.env` file containing your API keys and SMTP credentials.

### 2. **Run Locally (Development)**

The application runs two services (FastAPI and Streamlit) inside a single container environment.

```bash
# 1. Create the dummy SQLite database
uv run python create_db.py

# 2. Launch the combined process (FastAPI + Streamlit + MCP Server)
# NOTE: Ensure you use the exact command from the final Dockerfile CMD
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 &
uv run streamlit run app/ui/app.py --server.port 8080 --server.address 0.0.0.0
