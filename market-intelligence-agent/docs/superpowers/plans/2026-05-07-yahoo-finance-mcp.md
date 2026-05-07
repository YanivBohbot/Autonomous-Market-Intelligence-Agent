# Yahoo Finance MCP Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Yahoo Finance market data to the agent as a second MCP stdio tool server with three read-only tools (`yf_quote`, `yf_history`, `yf_news`), and add a `READ_ONLY_TOOLS` allowlist so reads bypass the human-approval interrupt.

**Architecture:** New stdio MCP client at `app/agent/tools/mcp_clients/yfinance_client.py` mirrors the existing `mcp_client.py` pattern. Three module-level LangChain `Tool`s wrap one async MCP shim each, returned via `asyncio.run`. The graph's `approval_node` checks tool names against `READ_ONLY_TOOLS` and skips `interrupt()` for reads; mixed batches use the **interrupt-if-any** rule. The system prompt is extracted to `app/agent/prompts/system.py`, rewritten in English, and given a new `📈 MARKET DATA` section.

**Tech Stack:** Python 3.12, LangGraph, LangChain `Tool`, `mcp` Python SDK, `yfmcp` PyPI package (yfinance MCP server), `pydantic-settings`, `uv` for dependency / process management.

**Reference spec:** `docs/superpowers/specs/2026-05-07-yahoo-finance-mcp-design.md`

**Testing policy:** This plan adds **no new tests**. The spec defers automated and manual verification to a follow-up. The only regression gate after each task is:

```
uv run pytest tests/ -v
```

All previously passing tests must still pass; no test count should drop.

---

## File Map

| Path | Status | Responsibility |
|---|---|---|
| `app/core/config.py` | modify | add `YFINANCE_TIMEOUT_S: int = 10` |
| `app/agent/prompts/__init__.py` | create | empty package marker |
| `app/agent/prompts/system.py` | create | `SYSTEM_PROMPT` constant (English, with MARKET DATA section) |
| `app/agent/nodes/generate.py` | modify | import `SYSTEM_PROMPT`, drop inline French prompt |
| `app/agent/tools/mcp_clients/yfinance_client.py` | create | stdio MCP client + 3 LangChain `Tool`s |
| `app/agent/tools/__init__.py` | modify | register yf tools, export `READ_ONLY_TOOLS` |
| `app/agent/graph.py` | modify | `approval_node` consults `READ_ONLY_TOOLS` |
| `pyproject.toml` | modify | add `yfmcp` dependency |
| `README.md` | modify | one-line note about yfinance |

---

## Task 1: Add `YFINANCE_TIMEOUT_S` setting and install `yfmcp`

**Files:**
- Modify: `market-intelligence-agent/app/core/config.py:9-24`
- Modify: `market-intelligence-agent/pyproject.toml`

**Why first:** Other tasks depend on `settings.YFINANCE_TIMEOUT_S` and the `yfmcp` server binary being available.

- [ ] **Step 1: Add the timeout setting to `Settings`**

Edit `app/core/config.py`. Add a new line inside `class Settings` after `API_URL`:

```python
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
    YFINANCE_TIMEOUT_S: int = 10

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

- [ ] **Step 2: Install the yfinance MCP server package**

Run from `market-intelligence-agent/`:

```bash
uv add yfmcp
```

This installs `yfmcp` (a community-maintained MCP server wrapping `yfinance`) and updates both `pyproject.toml` and `uv.lock`. It exposes a `yfmcp` console-script that becomes our subprocess command.

If `yfmcp` is unavailable on PyPI, fall back to `yfinance-mcp`. If neither is available, install raw `yfinance` and a small custom server is out of scope for this task — escalate.

- [ ] **Step 3: Verify the binary is invokable**

Run from `market-intelligence-agent/`:

```bash
uv run yfmcp --help
```

Expected: a usage banner from the yfmcp server (any non-error exit is acceptable; many MCP servers print no `--help` and instead exit with a help message). If the binary is not found, the PyPI package name was different — adjust and re-run Step 2 / 3.

- [ ] **Step 4: Run the existing test suite**

```bash
uv run pytest tests/ -v
```

Expected: same pass count as before this task (config import still works, no other behavior changed).

- [ ] **Step 5: Commit**

```bash
git add market-intelligence-agent/app/core/config.py market-intelligence-agent/pyproject.toml market-intelligence-agent/uv.lock
git commit -m "feat(config): add YFINANCE_TIMEOUT_S; install yfmcp dependency"
```

---

## Task 2: Extract system prompt to `app/agent/prompts/system.py` (English + MARKET DATA section)

**Files:**
- Create: `market-intelligence-agent/app/agent/prompts/__init__.py`
- Create: `market-intelligence-agent/app/agent/prompts/system.py`

**Why before generate.py:** the new module must exist before `generate.py` can import from it.

- [ ] **Step 1: Create the package marker**

Create `app/agent/prompts/__init__.py` as an empty file:

```python
```

- [ ] **Step 2: Create `system.py` with the English prompt**

Create `app/agent/prompts/system.py`:

```python
SYSTEM_PROMPT = """You are an expert assistant for data analysis and communication.

🛠️ YOUR TOOLS

CRM (read-only):
1. `crm_query` — run a SELECT query against the customer database.

Market data (read-only, Yahoo Finance):
2. `yf_quote` — current price and day stats for a ticker (args: `ticker: str`).
3. `yf_history` — historical prices for a ticker (args: `ticker: str`, optional `period: str` like "1mo", "3mo", "1y"; default "1mo").
4. `yf_news` — recent news headlines for a ticker (args: `ticker: str`, optional `limit: int`; default 5).

Side effects (require human approval):
5. `send_email` — send a report or message.

🗄️ CRM SCHEMA (table: `customers`)
- `id` (INTEGER): unique id
- `name` (TEXT): full name
- `email` (TEXT): email address
- `status` (TEXT): customer tier (e.g., 'VIP', 'Standard', 'Premium')
- `total_spend` (REAL): total amount spent

🧠 INSTRUCTIONS
- You are autonomous: write valid `SELECT` SQL queries based on the user's request. You may use WHERE, ORDER BY, LIMIT, and aggregates (COUNT, SUM).
- To find a customer by name, use `LIKE '%Name%'`.
- Before sending an email, make sure you have the recipient's address — fetch it from the CRM if needed.

📈 MARKET DATA GUIDELINES
- For "what's X trading at" questions, call `yf_quote`.
- For trend / performance / chart questions ("how has X done over the last quarter"), call `yf_history` with an appropriate `period`.
- For "any news on X" questions, call `yf_news`.
- You may call multiple market-data tools in parallel for the same ticker, or across several tickers, when the question benefits from it.
- Tickers are case-insensitive but conventionally uppercase (e.g., AAPL, MSFT, NVDA).
- Yahoo Finance is unauthenticated and may return "no data found" for invalid tickers — explain this to the user and suggest verifying the symbol.

Use the provided context (RAG documents and conversation history) to answer precisely.
"""

ERROR_RECOVERY_PROMPT = (
    "A tool returned a technical error. Analyze the error, explain it simply "
    "to the user, and propose a workaround if possible."
)
```

- [ ] **Step 3: Run the existing test suite**

```bash
uv run pytest tests/ -v
```

Expected: same pass count as before this task. The new files are not yet imported anywhere.

- [ ] **Step 4: Commit**

```bash
git add market-intelligence-agent/app/agent/prompts/
git commit -m "feat(prompts): extract SYSTEM_PROMPT to dedicated module; rewrite in English with market-data section"
```

---

## Task 3: Wire `generate.py` to the new prompt module

**Files:**
- Modify: `market-intelligence-agent/app/agent/nodes/generate.py`

- [ ] **Step 1: Replace the inline prompts with imports**

Open `app/agent/nodes/generate.py`. Replace the entire file contents with:

```python
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from app.core.config import settings
from app.agent.state import AgentState
from app.agent.tools import TOOLS
from app.agent.prompts.system import SYSTEM_PROMPT, ERROR_RECOVERY_PROMPT

logger = logging.getLogger(__name__)

_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True)
_llm_with_tools = _llm.bind_tools(TOOLS)


def generate_answer(state: AgentState) -> dict:
    logger.info("GENERATE: Building response")
    question = state["question"]
    documents = state["documents"]
    messages = state.get("messages", [])
    context = "\n\n".join(documents)

    if messages:
        last_message = messages[-1]
        if isinstance(last_message, ToolMessage) and "Error" in str(last_message.content):
            logger.warning("GENERATE: Tool error detected — generating explanation")
            return {
                "messages": [
                    _llm.invoke([
                        SystemMessage(content=ERROR_RECOVERY_PROMPT),
                        HumanMessage(content=f"Technical error: {last_message.content}"),
                    ])
                ]
            }

    msgs = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"User question: {question}\n\nDocument context (RAG):\n{context}"),
    ]
    if messages:
        msgs.extend(messages)

    response = _llm_with_tools.invoke(msgs)
    return {"messages": [response]}
```

- [ ] **Step 2: Run the existing test suite**

```bash
uv run pytest tests/ -v
```

Expected: same pass count. `generate.py` is not under direct unit test today (only graph-level tests touch it), so this should be inert at the test level.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/nodes/generate.py
git commit -m "refactor(generate): use SYSTEM_PROMPT and ERROR_RECOVERY_PROMPT from prompts module"
```

---

## Task 4: Create `yfinance_client.py` with three LangChain tools

**Files:**
- Create: `market-intelligence-agent/app/agent/tools/mcp_clients/yfinance_client.py`

**Pattern reference:** `app/agent/tools/mcp_clients/mcp_client.py:1-53` (existing MCP stdio client). The new file mirrors that structure: one `StdioServerParameters`, one async helper, one sync wrapper, and one `Tool` per yfinance verb — but the sync wrapper takes a `tool_name` argument so all three tools share it.

- [ ] **Step 1: Create the file**

Create `app/agent/tools/mcp_clients/yfinance_client.py`:

```python
import asyncio
import logging
import os
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_core.tools import Tool
from app.core.config import settings

logger = logging.getLogger(__name__)

server_params = StdioServerParameters(
    command="uv",
    args=["run", "yfmcp"],
    env=os.environ,
)


async def _call_yfmcp(tool_name: str, arguments: dict) -> str:
    """Invoke a single tool on the yfmcp stdio server and return its text result."""
    logger.info("YFMCP: %s args=%s", tool_name, arguments)
    async with AsyncExitStack() as stack:
        read_stream, write_stream = await stack.enter_async_context(
            stdio_client(server_params)
        )
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        result = await session.call_tool(tool_name, arguments=arguments)
        if result.content and len(result.content) > 0:
            return result.content[0].text
        return f"No data returned by {tool_name}."


def _sync_call(tool_name: str, arguments: dict) -> str:
    """Sync shim with timeout + error envelope. Returns a string the LLM can read."""
    timeout = settings.YFINANCE_TIMEOUT_S
    try:
        return asyncio.run(asyncio.wait_for(_call_yfmcp(tool_name, arguments), timeout))
    except asyncio.TimeoutError:
        logger.error("YFMCP: timeout after %ss for %s", timeout, tool_name)
        return "Error: Yahoo Finance request timed out"
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                asyncio.wait_for(_call_yfmcp(tool_name, arguments), timeout)
            )
        except asyncio.TimeoutError:
            return "Error: Yahoo Finance request timed out"
        except Exception as e:
            logger.error("YFMCP: error — %s", e)
            return f"Error: Yahoo Finance service unavailable: {e}"
        finally:
            loop.close()
    except Exception as e:
        logger.error("YFMCP: error — %s", e)
        return f"Error: Yahoo Finance service unavailable: {e}"


def _quote(ticker: str) -> str:
    return _sync_call("get_quote", {"ticker": ticker})


def _history(ticker: str, period: str = "1mo") -> str:
    return _sync_call("get_history", {"ticker": ticker, "period": period})


def _news(ticker: str, limit: int = 5) -> str:
    return _sync_call("get_news", {"ticker": ticker, "limit": limit})


yf_quote_tool = Tool(
    name="yf_quote",
    func=_quote,
    description=(
        "Get the current price and day statistics for a stock ticker from "
        "Yahoo Finance. Args: ticker (str, e.g. 'AAPL')."
    ),
)

yf_history_tool = Tool(
    name="yf_history",
    func=_history,
    description=(
        "Get historical prices for a stock ticker from Yahoo Finance. "
        "Args: ticker (str), period (str, optional, default '1mo'; e.g. '1mo', '3mo', '1y', '5y')."
    ),
)

yf_news_tool = Tool(
    name="yf_news",
    func=_news,
    description=(
        "Get recent news headlines for a stock ticker from Yahoo Finance. "
        "Args: ticker (str), limit (int, optional, default 5)."
    ),
)
```

> **Note on the underlying `yfmcp` tool names** (`get_quote`, `get_history`, `get_news`): if `yfmcp` exposes different names, adjust the three constants in `_quote`, `_history`, `_news`. Inspect the server with: `uv run python -c "import asyncio; from mcp import ClientSession, StdioServerParameters; from mcp.client.stdio import stdio_client; from contextlib import AsyncExitStack; import os; async def m():\n params=StdioServerParameters(command='uv', args=['run','yfmcp'], env=os.environ);\n async with AsyncExitStack() as s:\n  r,w=await s.enter_async_context(stdio_client(params));\n  sess=await s.enter_async_context(ClientSession(r,w));\n  await sess.initialize();\n  print([t.name for t in (await sess.list_tools()).tools])\nasyncio.run(m())"` and rename the constants.

- [ ] **Step 2: Run the existing test suite**

```bash
uv run pytest tests/ -v
```

Expected: same pass count. The new file is not yet imported by `tools/__init__.py`.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/mcp_clients/yfinance_client.py
git commit -m "feat(tools): add Yahoo Finance MCP client with quote, history, news tools"
```

---

## Task 5: Register yfinance tools in `TOOLS` and export `READ_ONLY_TOOLS`

**Files:**
- Modify: `market-intelligence-agent/app/agent/tools/__init__.py`

- [ ] **Step 1: Replace the file contents**

Open `app/agent/tools/__init__.py` and replace its contents with:

```python
from app.agent.tools.emails import send_email_tool
from app.agent.tools.mcp_clients.mcp_client import crm_tool
from app.agent.tools.mcp_clients.yfinance_client import (
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
)

TOOLS = [
    send_email_tool,
    crm_tool,
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
]

READ_ONLY_TOOLS: set[str] = {"crm_query", "yf_quote", "yf_history", "yf_news"}

__all__ = [
    "TOOLS",
    "READ_ONLY_TOOLS",
    "send_email_tool",
    "crm_tool",
    "yf_quote_tool",
    "yf_history_tool",
    "yf_news_tool",
]
```

- [ ] **Step 2: Run the existing test suite**

```bash
uv run pytest tests/ -v
```

Expected: same pass count. The graph still works — `bind_tools(TOOLS)` now includes three more tools, but no graph behavior changed yet (approval_node still gates everything).

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/__init__.py
git commit -m "feat(tools): register yfinance tools; export READ_ONLY_TOOLS allowlist"
```

---

## Task 6: Update `approval_node` to consult `READ_ONLY_TOOLS`

**Files:**
- Modify: `market-intelligence-agent/app/agent/graph.py:27-53`

This is the only behavior-changing task. Read-only batches now bypass `interrupt()`; mixed batches surface only the side-effect tool calls to the human (interrupt-if-any rule).

- [ ] **Step 1: Update imports and `approval_node`**

In `app/agent/graph.py`, change the imports block at the top to include `READ_ONLY_TOOLS`:

```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from langchain_core.messages import ToolMessage
from app.agent.state import AgentState
from app.agent.nodes.rag import retrieve_internal_documentation
from app.agent.nodes.research import web_search
from app.agent.nodes.grader import grade_documents
from app.agent.nodes.generate import generate_answer
from app.agent.tools import TOOLS, READ_ONLY_TOOLS
from app.agent.memory.checkpointer import create_checkpointer
```

Then replace the existing `approval_node` function (lines ~27-53) with:

```python
def approval_node(state: AgentState) -> dict:
    """Pause graph execution and surface pending side-effect tool calls for human review.

    Read-only tool calls (per READ_ONLY_TOOLS allowlist) bypass the interrupt and execute
    immediately. Mixed batches follow the interrupt-if-any rule: if any call is a side
    effect, the node interrupts and surfaces the side-effect call(s) to the human.
    Resumer passes 'approve' to proceed or 'reject' to cancel; on reject, every tool
    call in the batch (read-only or not) is cancelled with a ToolMessage."""
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []

    side_effect_calls = [tc for tc in tool_calls if tc["name"] not in READ_ONLY_TOOLS]
    if not side_effect_calls:
        # All read-only — no human approval needed.
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
    decision = interrupt(requests)[0]
    if isinstance(decision, dict):
        decision = decision.get("type", "reject")
    if decision == "approve":
        return {}
    cancel_msgs = [
        ToolMessage(content="Action cancelled by user.", tool_call_id=t["id"], name=t["name"])
        for t in tool_calls
    ]
    return {"messages": cancel_msgs}
```

- [ ] **Step 2: Run the existing test suite**

```bash
uv run pytest tests/ -v
```

Expected: same pass count. The existing `tests/unit/test_hitl_interrupt.py` tests assert behavior for `send_email` (a side-effect tool) and for the no-tool-call case — both unchanged. If a test breaks here, the most likely cause is that an existing test asserted `interrupt()` is called for a tool name now in `READ_ONLY_TOOLS` — investigate before proceeding.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/graph.py
git commit -m "feat(graph): bypass approval interrupt for read-only tool calls"
```

---

## Task 7: README note

**Files:**
- Modify: `market-intelligence-agent/README.md`

- [ ] **Step 1: Add the yfinance line to the tools table or relevant section**

Open `README.md`, locate the existing tools table or list (the same place that mentions `crm_query` and `send_email`). Add a row / bullet for each new tool:

```markdown
| Tool | Type | Description |
|---|---|---|
| `crm_query` | read-only (MCP / SQLite) | SELECT against the `customers` table |
| `yf_quote` | read-only (MCP / yfinance) | Current price + day stats for a ticker |
| `yf_history` | read-only (MCP / yfinance) | Historical prices, configurable period |
| `yf_news` | read-only (MCP / yfinance) | Recent news headlines for a ticker |
| `send_email` | side-effect (SMTP) | Sends email; gated by HITL approval |
```

If the README has prose rather than a table, add: *"Yahoo Finance market data (`yf_quote`, `yf_history`, `yf_news`) is exposed via the `yfmcp` MCP stdio server — read-only, bypasses the human-approval gate."*

- [ ] **Step 2: Run the existing test suite**

```bash
uv run pytest tests/ -v
```

Expected: same pass count.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/README.md
git commit -m "docs(readme): document Yahoo Finance MCP tools"
```

---

## Final verification

After all tasks complete:

- [ ] **Step 1: Full regression check**

```bash
uv run pytest tests/ -v
```

Expected: same pass count as the start of this plan. **No new failures.**

- [ ] **Step 2: Confirm tool registration at runtime**

```bash
uv run python -c "from app.agent.tools import TOOLS, READ_ONLY_TOOLS; print([t.name for t in TOOLS]); print(READ_ONLY_TOOLS)"
```

Expected output (order of TOOLS may vary):

```
['send_email', 'crm_query', 'yf_quote', 'yf_history', 'yf_news']
{'crm_query', 'yf_quote', 'yf_history', 'yf_news'}
```

- [ ] **Step 3: Confirm the graph compiles**

```bash
uv run python -c "from app.agent.graph import agent_app; print('compiled OK')"
```

Expected output: `compiled OK`.

---

## Self-Review Notes

**Spec coverage:** every "Components & Files" entry in the spec has a task — config (Task 1), prompts module (Task 2), generate.py wiring (Task 3), yfinance client (Task 4), tools registry + allowlist (Task 5), approval_node (Task 6), README (Task 7). Spec's "Open Decisions" (exact PyPI name, error-prompt placement) are resolved in Tasks 1 and 2 respectively.

**Type / name consistency:** `READ_ONLY_TOOLS: set[str]` is declared in Task 5 and consumed in Task 6. Tool names `yf_quote`, `yf_history`, `yf_news` match across the prompt (Task 2), the client (Task 4), the registry (Task 5), and the allowlist (Task 6). Underlying yfmcp tool names (`get_quote`, `get_history`, `get_news`) are flagged as adjustable in Task 4 with an inspection command.

**Testing policy:** plan adds zero tests per spec direction; the regression gate after each task is `uv run pytest tests/ -v` with same pass count. This is intentional — a follow-up spec will add coverage.
