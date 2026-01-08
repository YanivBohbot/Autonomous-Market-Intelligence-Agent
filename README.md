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
| **01** | Initial Analysis: Agent identifies the need for client data. | `crm_query` | **PAUSE 1: INTERRUPTED** |
| **02** | *User Approves Action 1* | Executes SQL Query (`SELECT name, email, status FROM customers WHERE name LIKE...`). | Running |
| **03** | **Data Synthesis:** Agent reads SQL result and retrieves IA Strategy from Pinecone (RAG). | `send_email` | **PAUSE 2: INTERRUPTED** |
| **04** | *User Approves Action 2* | Executes SMTP Tool (Sends Email). | Completed |

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
