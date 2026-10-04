# Clients Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/clients` into a client list + per-client chat workspace (profile/P&L header + Market Desk chat scoped to that client), replacing `/data`'s Clients tab.

**Architecture:** Backend: a new deterministic `GET /data/clients/{id}/summary` endpoint (no agent) computes live P&L; a new graph node derives which client is active straight from the thread id (`clients_<id>`) and writes a short blurb into shared graph state; three specialists (`portfolio_agent`, `finance_agent`, `rag_agent`) read that blurb into their system prompt via a `dynamic_prompt` middleware. Frontend: a client list page and a per-client workspace page (profile header + `CopilotChat` + the existing `DeskActivityRail`), both new routes under the existing `AppLayout`.

**Tech Stack:** FastAPI, sqlite3 (direct, not MCP), LangChain `create_agent`/`dynamic_prompt`/`state_schema`, LangGraph `StateGraph`, React 19, react-router-dom, CopilotKit v2 (`@copilotkit/react-core/v2`), Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-10-04-clients-workspace-design.md`

## Global Constraints

- No change to `app/api/routers/copilot.py` — thread id already flows through unmodified.
- No change to `email_agent.py`, `browser_agent.py`, `memory_agent.py`, `filesystem_agent.py` — `client_context_prompt` touches only `portfolio_agent`, `finance_agent`, `rag_agent`.
- `frontend/src/data/ClientsList.tsx` and its test are **moved** to `frontend/src/clients/`, never duplicated.
- TDD throughout: write the failing test, watch it fail, then implement.
- Full regression (frontend Vitest, backend pytest) must stay green at the end — currently 122 frontend / 413 backend passing.

## Review Focus

- A client with holdings where **every** ticker's live price fails (not just one) — `compute_portfolio_metrics` raises on an empty position list; the summary builder must guard this and return `totals: None` instead of a 500. Pinned in Task 2.
- A thread whose id matches the `clients_<id>` shape but whose id no longer exists in `customers.db` (client deleted after the thread started) — `load_client_context` must return `None`, not raise. Pinned in Task 4.
- `load_client_context` re-reads the DB **every turn**, not just the first — a client's data edited mid-conversation (via `/data/import`) must show up on the very next turn, not stay stale from an earlier checkpoint. Pinned in Task 4.
- A non-numeric or otherwise invalid `:id` in the `/clients/:id` URL (FastAPI's `int` path converter 422s, not 404s) must still surface as a plain error banner in the workspace, not a crash. Pinned in Task 10.
- The `client_context` field must actually cross the subgraph boundary into each of the three specialists — easy to wire the parent graph state and forget the specialist's own `state_schema`, which silently makes `request.state.get("client_context")` always `None` inside the specialist. Pinned by the integration test in Task 6.

---

## Task 1: `get_client_with_holdings` DB query

**Files:**
- Modify: `app/data_import/db.py`
- Test: `tests/unit/test_data_import_db.py`

**Interfaces:**
- Produces: `get_client_with_holdings(conn: sqlite3.Connection, client_id: int) -> dict | None` — `{"client_id", "name", "email", "segment", "risk_profile", "advisor", "city", "holdings": [{"ticker", "shares", "avg_cost"}, ...]}`, or `None` if no client has that id. Consumed by Task 2 (`build_client_summary`) and Task 4 (`load_client_context`).

- [ ] **Step 1: Write the failing test**

Open `tests/unit/test_data_import_db.py` and add (reuse the file's existing `_SCHEMA`/fixture pattern — check the top of the file for the existing `conn` fixture and companies/clients/holdings seed helper before adding these; follow its exact style):

```python
def test_get_client_with_holdings_returns_the_client_and_their_holdings(conn):
    conn.execute("INSERT INTO companies VALUES ('AAPL', 'Apple Inc.', 'Technology')")
    conn.execute(
        "INSERT INTO clients VALUES (1, 'Jane Doe', 'jane@x.com', 'VIP', 'balanced', 'Sam', 'Paris', '2024-01-01')"
    )
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.commit()

    result = get_client_with_holdings(conn, 1)

    assert result == {
        "client_id": 1, "name": "Jane Doe", "email": "jane@x.com", "segment": "VIP",
        "risk_profile": "balanced", "advisor": "Sam", "city": "Paris",
        "holdings": [{"ticker": "AAPL", "shares": 10.0, "avg_cost": 150.0}],
    }


def test_get_client_with_holdings_returns_none_for_an_unknown_id(conn):
    assert get_client_with_holdings(conn, 999) is None
```

Add `get_client_with_holdings` to the existing `from app.data_import.db import (...)` import block at the top of the test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_data_import_db.py -k get_client_with_holdings -v`
Expected: FAIL with `ImportError` or `AttributeError: ... get_client_with_holdings` (name not defined yet).

- [ ] **Step 3: Write minimal implementation**

Add to `app/data_import/db.py`, after `list_clients_with_holdings`:

```python
def get_client_with_holdings(conn: sqlite3.Connection, client_id: int) -> dict | None:
    row = conn.execute(
        "SELECT client_id, name, email, segment, risk_profile, advisor, city "
        "FROM clients WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    if row is None:
        return None
    cid, name, email, segment, risk_profile, advisor, city = row
    holdings = [
        {"ticker": ticker, "shares": shares, "avg_cost": avg_cost}
        for ticker, shares, avg_cost in conn.execute(
            "SELECT ticker, shares, avg_cost FROM holdings WHERE client_id = ?", (cid,)
        )
    ]
    return {
        "client_id": cid, "name": name, "email": email, "segment": segment,
        "risk_profile": risk_profile, "advisor": advisor, "city": city,
        "holdings": holdings,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_data_import_db.py -k get_client_with_holdings -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add app/data_import/db.py tests/unit/test_data_import_db.py
git commit -m "feat(data-import): add get_client_with_holdings for single-client lookup"
```

---

## Task 2: `build_client_summary` — deterministic P&L builder

**Files:**
- Create: `app/data_import/client_summary.py`
- Test: `tests/unit/test_client_summary.py`

**Interfaces:**
- Consumes: `get_client_with_holdings`'s return shape (Task 1) as its `client` argument; `Position`/`compute_portfolio_metrics` from `app/agent/tools/finance_calc.py` (existing).
- Produces: `async def build_client_summary(*, client: dict, get_price: Callable[[str], Awaitable[float]]) -> dict` — `{"client_id", "name", "email", "segment", "risk_profile", "advisor", "city", "totals": {"market_value", "cost_basis", "unrealized_pnl", "unrealized_pnl_pct"} | None, "positions": [...], "unpriced_tickers": [str, ...]}`. Consumed by Task 3 (the router endpoint).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_client_summary.py`:

```python
"""build_client_summary computes a client's live P&L for GET
/data/clients/{id}/summary -- a view, not an agent tool: unlike
client_portfolio_tool (app/agent/tools/client_portfolio.py), which fails
closed if any ticker's price can't be fetched, this degrades: a bad ticker
is reported in unpriced_tickers and excluded from totals instead of
raising, so one stale ticker doesn't blank the whole page.
"""
import asyncio

import pytest

from app.data_import.client_summary import build_client_summary

_CLIENT = {
    "client_id": 1, "name": "Jane Doe", "email": "jane@x.com", "segment": "VIP",
    "risk_profile": "balanced", "advisor": "Sam", "city": "Paris",
    "holdings": [
        {"ticker": "AAPL", "shares": 10.0, "avg_cost": 150.0},
        {"ticker": "MSFT", "shares": 5.0, "avg_cost": 300.0},
    ],
}
_PRICES = {"AAPL": 200.0, "MSFT": 350.0}


def _run(client=_CLIENT, prices=_PRICES, failing: set[str] = frozenset()):
    async def get_price(ticker):
        if ticker in failing:
            raise ValueError("no data")
        return prices[ticker]

    return asyncio.run(build_client_summary(client=client, get_price=get_price))


def test_computes_totals_from_live_prices():
    result = _run()
    assert result["totals"]["market_value"] == pytest.approx(200.0 * 10 + 350.0 * 5)
    assert result["client_id"] == 1
    assert result["name"] == "Jane Doe"


def test_client_with_no_holdings_has_no_totals_and_does_not_crash():
    client = {**_CLIENT, "holdings": []}
    result = _run(client=client)
    assert result["totals"] is None
    assert result["positions"] == []
    assert result["unpriced_tickers"] == []


def test_one_unpriced_ticker_is_excluded_and_reported_but_totals_still_compute():
    result = _run(failing={"MSFT"})
    assert result["unpriced_tickers"] == ["MSFT"]
    assert [p["ticker"] for p in result["positions"]] == ["AAPL"]
    assert result["totals"]["market_value"] == pytest.approx(200.0 * 10)


def test_every_ticker_unpriced_gives_none_totals_not_a_crash():
    result = _run(failing={"AAPL", "MSFT"})
    assert result["totals"] is None
    assert result["positions"] == []
    assert sorted(result["unpriced_tickers"]) == ["AAPL", "MSFT"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_client_summary.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.data_import.client_summary'`

- [ ] **Step 3: Write minimal implementation**

Create `app/data_import/client_summary.py`:

```python
"""Deterministic client P&L summary for GET /data/clients/{id}/summary --
no agent involved, same CRUD-not-agent philosophy as the rest of
app/data_import/. Unlike client_portfolio_tool
(app/agent/tools/client_portfolio.py), which fails closed (raises if any
ticker's price can't be fetched, so the agent never reports a silently
wrong total), this is a UI view: one bad ticker should not blank the
whole client's page, so a failed price is reported in unpriced_tickers
and excluded from totals instead of raising.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agent.tools.finance_calc import Position, compute_portfolio_metrics


async def build_client_summary(
    *,
    client: dict,
    get_price: Callable[[str], Awaitable[float]],
) -> dict:
    holdings = client["holdings"]
    tickers = [h["ticker"] for h in holdings]
    results = await asyncio.gather(*(get_price(t) for t in tickers), return_exceptions=True)

    positions = []
    unpriced: list[str] = []
    for holding, result in zip(holdings, results):
        if isinstance(result, BaseException):
            unpriced.append(holding["ticker"])
            continue
        positions.append(Position(
            ticker=holding["ticker"], shares=holding["shares"],
            avg_cost=holding["avg_cost"], price=float(result),
        ))

    totals = None
    position_rows: list[dict] = []
    if positions:
        metrics = compute_portfolio_metrics(positions)
        totals = metrics["totals"]
        position_rows = metrics["positions"]

    return {
        "client_id": client["client_id"], "name": client["name"], "email": client["email"],
        "segment": client["segment"], "risk_profile": client["risk_profile"],
        "advisor": client["advisor"], "city": client["city"],
        "totals": totals, "positions": position_rows, "unpriced_tickers": unpriced,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_client_summary.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add app/data_import/client_summary.py tests/unit/test_client_summary.py
git commit -m "feat(data-import): add build_client_summary, degrading on unpriced tickers"
```

---

## Task 3: `GET /data/clients/{client_id}/summary` endpoint

**Files:**
- Modify: `app/api/routers/data.py`
- Test: `tests/unit/test_data_endpoints.py`

**Interfaces:**
- Consumes: `get_client_with_holdings` (Task 1), `build_client_summary` (Task 2), `price_from_quote`/`parse_tool_payload` from `app/agent/tools/concentration.py` (existing).
- Produces: a module-level `async def _live_price(ticker: str) -> float` in `data.py` (the real price source, monkeypatchable by tests) and the route itself.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_data_endpoints.py` (the `client` fixture already seeds `companies`/`clients`; these tests add their own holdings row per-test since the base fixture doesn't seed any):

```python
def test_get_client_summary_computes_totals_from_a_mocked_price(client, monkeypatch):
    import sqlite3
    conn = sqlite3.connect(monkeypatch_db_path := data_router_module.DB_PATH)
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.commit()
    conn.close()

    async def fake_price(ticker):
        assert ticker == "AAPL"
        return 200.0

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)

    resp = client.get("/data/clients/1/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Jane Doe"
    assert body["totals"]["market_value"] == 2000.0
    assert body["unpriced_tickers"] == []


def test_get_client_summary_with_no_holdings_returns_null_totals(client):
    resp = client.get("/data/clients/1/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"] is None
    assert body["positions"] == []


def test_get_client_summary_404s_for_an_unknown_client(client):
    resp = client.get("/data/clients/999/summary")
    assert resp.status_code == 404


def test_get_client_summary_degrades_when_the_price_fetch_raises(client, monkeypatch):
    import sqlite3
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.commit()
    conn.close()

    async def failing_price(ticker):
        raise ValueError("yfinance is down")

    monkeypatch.setattr(data_router_module, "_live_price", failing_price)

    resp = client.get("/data/clients/1/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"] is None
    assert body["unpriced_tickers"] == ["AAPL"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k get_client_summary -v`
Expected: FAIL with `404` on the first test (route doesn't exist yet → FastAPI 404) or `AttributeError: module ... has no attribute '_live_price'`.

- [ ] **Step 3: Write minimal implementation**

In `app/api/routers/data.py`, add to the imports:

```python
from app.agent.tools.concentration import parse_tool_payload, price_from_quote
from app.data_import.client_summary import build_client_summary
from app.data_import.db import (
    DB_PATH,
    client_id_by_email,
    existing_client_emails,
    get_client_with_holdings,
    known_tickers,
    list_clients_with_holdings,
    write_clients,
    write_holdings,
)
```

Then add, after `get_clients`:

```python
async def _live_price(ticker: str) -> float:
    # Deferred import: avoids connecting to the yfinance MCP server at
    # module import time for every test that imports this router, same
    # convention as client_portfolio_tool / concentration_screen_tool.
    from app.agent.tools.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"
    return price_from_quote(parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: ticker})))


@router.get("/clients/{client_id}/summary")
async def get_client_summary(client_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        client = get_client_with_holdings(conn, client_id)
    finally:
        conn.close()
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    return await build_client_summary(client=client, get_price=_live_price)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_data_endpoints.py -v`
Expected: all tests in the file pass, including the 4 new ones.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/data.py tests/unit/test_data_endpoints.py
git commit -m "feat(data): add GET /data/clients/{id}/summary"
```

---

## Task 4: `load_client_context` graph node

**Files:**
- Modify: `app/agent/multi_agent/state.py`
- Modify: `app/agent/multi_agent/graph.py`
- Test: `tests/unit/test_multi_agent_graph_structure.py`
- Test: Create `tests/unit/test_load_client_context.py`

**Interfaces:**
- Consumes: `get_client_with_holdings` (Task 1).
- Produces: `SupervisorState.client_context: Optional[str]`; `load_client_context(state, config) -> dict` wired `START -> load_client_context -> record_question -> supervisor`. Consumed by Task 5 (`client_context_prompt` reads `state["client_context"]`) and Task 6 (specialist `state_schema`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_load_client_context.py`:

```python
"""load_client_context derives which client is active straight from the
thread id (clients_<id>) rather than from a frontend-pushed context -- see
docs/superpowers/specs/2026-10-04-clients-workspace-design.md decision 4.
Runs every turn (not just the first) so edits via /data/import mid-
conversation show up immediately; it is never cached onto the checkpoint.
"""
import sqlite3

import app.agent.multi_agent.graph as graph_module
from app.agent.multi_agent.graph import load_client_context


def _seed(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE clients (
            client_id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            segment TEXT NOT NULL, risk_profile TEXT NOT NULL, advisor TEXT NOT NULL,
            city TEXT NOT NULL, joined_on DATE NOT NULL
        );
        CREATE TABLE holdings (
            client_id INTEGER NOT NULL, ticker TEXT NOT NULL, shares REAL NOT NULL, avg_cost REAL NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO clients VALUES (1, 'Jane Doe', 'jane@x.com', 'VIP', 'balanced', 'Sam', 'Paris', '2024-01-01')"
    )
    conn.commit()
    conn.close()


def test_matching_thread_id_with_an_existing_client_sets_client_context(tmp_path, monkeypatch):
    db_path = tmp_path / "customers.db"
    _seed(db_path)
    monkeypatch.setattr(graph_module, "DB_PATH", str(db_path))

    result = load_client_context({}, {"configurable": {"thread_id": "clients_1"}})

    assert result == {"client_context": "Client actif: Jane Doe, segment VIP, risque balanced, conseiller Sam."}


def test_matching_thread_id_with_no_such_client_gives_none(tmp_path, monkeypatch):
    db_path = tmp_path / "customers.db"
    _seed(db_path)
    monkeypatch.setattr(graph_module, "DB_PATH", str(db_path))

    result = load_client_context({}, {"configurable": {"thread_id": "clients_999"}})

    assert result == {"client_context": None}


def test_non_client_thread_id_gives_none_without_touching_the_db(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_module, "DB_PATH", str(tmp_path / "does-not-exist.db"))

    result = load_client_context({}, {"configurable": {"thread_id": "desk_abc123"}})

    assert result == {"client_context": None}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_load_client_context.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_client_context'`

- [ ] **Step 3: Write minimal implementation**

In `app/agent/multi_agent/state.py`, change:

```python
class SupervisorState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    question: str
    documents: List[str]
    next_agent: Optional[str]
    agent_hops: int
    last_agent: Optional[str]
```

to add one field (keep the existing docstring comment on `last_agent` as-is):

```python
class SupervisorState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    question: str
    documents: List[str]
    next_agent: Optional[str]
    agent_hops: int
    last_agent: Optional[str]
    # Set every turn by load_client_context, from the thread id -- see that
    # function's docstring. None on every thread except a client workspace's.
    client_context: Optional[str]
```

In `app/agent/multi_agent/graph.py`, add near the top (after the existing imports):

```python
import re
import sqlite3

from langchain_core.runnables import RunnableConfig

from app.data_import.db import DB_PATH, get_client_with_holdings

_CLIENT_THREAD_RE = re.compile(r"^clients_(\d+)$")


def load_client_context(state: SupervisorState, config: RunnableConfig) -> dict:
    """Derive which client this thread is scoped to straight from the
    thread id (clients_<id>) rather than anything the frontend pushes --
    see docs/superpowers/specs/2026-10-04-clients-workspace-design.md
    decision 4. Runs every turn (cheap single-row read), not only the
    first, so an edit via /data/import mid-conversation is reflected on
    the very next turn instead of staying stale from an earlier
    checkpoint."""
    thread_id = (config.get("configurable") or {}).get("thread_id", "")
    match = _CLIENT_THREAD_RE.match(thread_id)
    if not match:
        return {"client_context": None}
    conn = sqlite3.connect(DB_PATH)
    try:
        client = get_client_with_holdings(conn, int(match.group(1)))
    finally:
        conn.close()
    if client is None:
        return {"client_context": None}
    return {"client_context": (
        f"Client actif: {client['name']}, segment {client['segment']}, "
        f"risque {client['risk_profile']}, conseiller {client['advisor']}."
    )}
```

Then change `_build_workflow` to wire the new node in front of `record_question`:

```python
def _build_workflow() -> StateGraph:
    workflow = StateGraph(SupervisorState)
    workflow.add_node("load_client_context", load_client_context)
    workflow.add_node("record_question", record_question)
    workflow.add_node("supervisor", supervisor_node, retry_policy=RetryPolicy())
    for name, agent_specialist in SPECIALISTS.items():
        workflow.add_node(name, agent_specialist())
        workflow.add_edge(name, "supervisor")
    workflow.add_edge(START, "load_client_context")
    workflow.add_edge("load_client_context", "record_question")
    workflow.add_edge("record_question", "supervisor")
    return workflow
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_load_client_context.py -v`
Expected: `3 passed`

- [ ] **Step 5: Add the node to the graph-structure test and run the whole file**

Add `"load_client_context"` to the tuple of expected node names in `test_graph_has_supervisor_and_specialist_nodes` (`tests/unit/test_multi_agent_graph_structure.py`).

Run: `uv run pytest tests/unit/test_multi_agent_graph_structure.py tests/unit/test_load_client_context.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/agent/multi_agent/state.py app/agent/multi_agent/graph.py tests/unit/test_load_client_context.py tests/unit/test_multi_agent_graph_structure.py
git commit -m "feat(multi-agent): derive active client from thread id every turn"
```

---

## Task 5: `client_context_prompt` middleware

**Files:**
- Modify: `app/agent/middleware.py`
- Test: `tests/unit/test_middleware.py`

**Interfaces:**
- Consumes: `state["client_context"]` (Task 4).
- Produces: `client_context_prompt` (a `@dynamic_prompt`-decorated callable), appended to the middleware list of `portfolio_agent`/`finance_agent`/`rag_agent` in Task 6.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_middleware.py`, next to `test_today_prompt_appends_todays_date_to_the_static_prompt` (reuse its exact style: `create_agent` with a plain `FakeToolModel`, inspect `model.seen[0][0].content`):

```python
@pytest.mark.anyio
async def test_client_context_prompt_appends_the_active_client_when_set():
    model = FakeToolModel([AIMessage(content="hi")])
    agent = create_agent(
        model=model, tools=[], system_prompt="You are X.",
        middleware=[client_context_prompt], state_schema=ClientContextState,
    )
    await agent.ainvoke({
        "messages": [HumanMessage("q")],
        "client_context": "Client actif: Jane Doe, segment VIP, risque balanced, conseiller Sam.",
    })
    system_text = model.seen[0][0].content
    assert system_text.startswith("You are X.")
    assert "Client actif: Jane Doe" in system_text


@pytest.mark.anyio
async def test_client_context_prompt_leaves_the_prompt_unchanged_when_unset():
    model = FakeToolModel([AIMessage(content="hi")])
    agent = create_agent(
        model=model, tools=[], system_prompt="You are X.",
        middleware=[client_context_prompt], state_schema=ClientContextState,
    )
    await agent.ainvoke({"messages": [HumanMessage("q")]})
    assert model.seen[0][0].content == "You are X."
```

Add `client_context_prompt` to the `from app.agent.middleware import (...)` block, and add this import:

```python
from app.agent.multi_agent.state import ClientContextState
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_middleware.py -k client_context_prompt -v`
Expected: FAIL with `ImportError` (`client_context_prompt` and `ClientContextState` don't exist yet).

- [ ] **Step 3: Write minimal implementation**

In `app/agent/multi_agent/state.py`, add (after `SupervisorState`):

```python
from langchain.agents import AgentState


class ClientContextState(AgentState):
    """create_agent's own state schema, extended with the one field
    specialists need from the parent graph's SupervisorState. Passed as
    state_schema= on portfolio_agent/finance_agent/rag_agent's
    create_agent(...) calls -- without it, the matching key on the parent
    graph's state is never forwarded into the specialist subgraph, and
    request.state.get("client_context") inside client_context_prompt would
    always be None. Key name must match SupervisorState.client_context."""
    client_context: Optional[str]
```

In `app/agent/middleware.py`, add after `fresh_documents_prompt`:

```python
@dynamic_prompt
def client_context_prompt(request: ModelRequest) -> str:
    """Appends the active client's profile blurb (set by
    load_client_context, see app/agent/multi_agent/graph.py) to the system
    prompt when this thread is scoped to a client; leaves the prompt
    untouched on every other thread."""
    client_context = request.state.get("client_context")
    base = request.system_prompt or ""
    if not client_context:
        return base
    return f"{base}\n\n{client_context}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_middleware.py -v`
Expected: all tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add app/agent/multi_agent/state.py app/agent/middleware.py tests/unit/test_middleware.py
git commit -m "feat(multi-agent): add client_context_prompt dynamic system prompt"
```

---

## Task 6: Wire `client_context_prompt` into the three client-facing specialists

**Files:**
- Modify: `app/agent/multi_agent/portfolio_agent.py`
- Modify: `app/agent/multi_agent/finance_agent.py`
- Modify: `app/agent/multi_agent/rag_agent.py`
- Test: Create `tests/unit/test_client_context_reaches_specialists.py`

**Interfaces:**
- Consumes: `client_context_prompt` (Task 5), `ClientContextState` (Task 5), `build_multi_agent_app` (existing, `app/agent/multi_agent/__init__.py`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_client_context_reaches_specialists.py` (mirrors `tests/unit/test_multi_agent_end_to_end.py`'s mocking technique — read that file first if anything below doesn't match its current imports):

```python
"""client_context, set by load_client_context from the thread id, must
actually reach the specialist that answers -- the easy mistake is wiring
the parent graph's state field and forgetting the specialist's own
state_schema, which silently makes request.state.get("client_context")
always None inside the specialist (see Review Focus in the plan)."""
import sqlite3
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import build_multi_agent_app
import app.agent.multi_agent.graph as graph_module
from app.agent.multi_agent import portfolio_agent as portfolio_agent_mod
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision
from tests.unit.fake_chat import FakeToolModel


def test_portfolio_agent_sees_the_active_client_in_its_system_prompt(tmp_path, monkeypatch):
    db_path = tmp_path / "customers.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE clients (
            client_id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            segment TEXT NOT NULL, risk_profile TEXT NOT NULL, advisor TEXT NOT NULL,
            city TEXT NOT NULL, joined_on DATE NOT NULL
        );
        CREATE TABLE holdings (
            client_id INTEGER NOT NULL, ticker TEXT NOT NULL, shares REAL NOT NULL, avg_cost REAL NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO clients VALUES (1, 'Margaret Collins', 'mc@x.com', 'VIP', 'conservative', 'Sam', 'Paris', '2024-01-01')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(graph_module, "DB_PATH", str(db_path))

    fake = FakeToolModel([AIMessage(content="Your portfolio is worth $100.")])
    with patch.object(portfolio_agent_mod, "specialist_model", return_value=fake), \
         patch.object(supervisor_mod, "_router") as router_mock:
        router_mock.invoke.return_value = RoutingDecision(next="portfolio_agent", reasoning="portfolio question")
        graph = build_multi_agent_app(InMemorySaver())
        graph.invoke(
            {"question": "What's my portfolio worth?", "messages": [], "documents": [],
             "next_agent": None, "agent_hops": 0},
            {"configurable": {"thread_id": "clients_1"}},
        )

    system_text = fake.seen[0][0].content
    assert "Margaret Collins" in system_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_client_context_reaches_specialists.py -v`
Expected: FAIL — `assert "Margaret Collins" in system_text` fails because `client_context_prompt`/`state_schema` aren't wired into `portfolio_agent` yet (the prompt never gets the client blurb).

- [ ] **Step 3: Write minimal implementation**

In `app/agent/multi_agent/portfolio_agent.py`, change the imports and `build_portfolio_agent`:

```python
from app.agent.middleware import base_middleware, client_context_prompt, specialist_model
from app.agent.multi_agent.state import ClientContextState
```

```python
def build_portfolio_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=PORTFOLIO_SYSTEM_PROMPT,
        state_schema=ClientContextState,
        middleware=[
            *base_middleware(check_email=False),
            client_context_prompt,
            HumanInTheLoopMiddleware(interrupt_on={"save_portfolio_report": True}),
            market_desk_display,
        ],
        name="portfolio_agent",
    )
```

In `app/agent/multi_agent/finance_agent.py`:

```python
from app.agent.middleware import base_middleware, client_context_prompt, redact_emails, specialist_model
from app.agent.multi_agent.state import ClientContextState
```

```python
def build_finance_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=FINANCE_SYSTEM_PROMPT,
        state_schema=ClientContextState,
        middleware=[*base_middleware(), redact_emails(), client_context_prompt, market_desk_display],
        name="finance_agent",
    )
```

In `app/agent/multi_agent/rag_agent.py`:

```python
from app.agent.middleware import base_middleware, client_context_prompt, fresh_documents_prompt, redact_emails, specialist_model
from app.agent.multi_agent.state import ClientContextState
```

```python
def build_rag_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=RAG_SYSTEM_PROMPT,
        state_schema=ClientContextState,
        middleware=[*base_middleware(), redact_emails(), fresh_documents_prompt, client_context_prompt, market_desk_display],
        name="rag_agent",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_client_context_reaches_specialists.py -v`
Expected: `1 passed`

Then run the full existing middleware/multi-agent test files to confirm the `state_schema`/middleware-order additions didn't break anything already pinned there:

Run: `uv run pytest tests/unit/test_middleware.py tests/unit/test_multi_agent_end_to_end.py tests/unit/test_multi_agent_hitl.py tests/unit/test_multi_agent_finance_agent.py -v`
Expected: all pass. (`test_base_middleware_order` in `test_middleware.py` asserts on `base_middleware()`'s own return value, not on any specialist's full middleware list, so it is unaffected by this task.)

- [ ] **Step 5: Commit**

```bash
git add app/agent/multi_agent/portfolio_agent.py app/agent/multi_agent/finance_agent.py app/agent/multi_agent/rag_agent.py tests/unit/test_client_context_reaches_specialists.py
git commit -m "feat(multi-agent): wire client_context_prompt into portfolio/finance/rag agents"
```

---

## Task 7: Move `ClientsList` under `frontend/src/clients/` and make rows clickable

**Files:**
- Create: `frontend/src/clients/ClientsList.tsx` (moved from `frontend/src/data/ClientsList.tsx`)
- Create: `frontend/src/clients/ClientsList.test.tsx` (moved from `frontend/src/data/ClientsList.test.tsx`)
- Delete: `frontend/src/data/ClientsList.tsx`
- Delete: `frontend/src/data/ClientsList.test.tsx`

**Interfaces:**
- Produces: `ClientsList` (default export unchanged — a plain component, no props), now navigating to `/clients/:id` on row click. Consumed by Task 8 (`ClientsPage`).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/clients/ClientsList.test.tsx` with the moved content from `frontend/src/data/ClientsList.test.tsx` (same 3 existing tests, same imports except the relative path `"./ClientsList"` stays correct since the file moves alongside it), wrapped in a router (needed once the component calls `useNavigate`) and with one new test:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ClientsList } from "./ClientsList";

function renderWithRouter() {
  return render(<MemoryRouter><ClientsList /></MemoryRouter>);
}

describe("ClientsList", () => {
  it("renders each client with their holdings", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 1, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        holdings: [{ ticker: "AAPL", shares: 10, avg_cost: 150 }],
      }],
    }));
    renderWithRouter();
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("renders a client with no holdings without crashing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 1, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris", holdings: [],
      }],
    }));
    renderWithRouter();
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
  });

  it("shows an error message when the fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    renderWithRouter();
    expect(await screen.findByText(/failed to load clients/i)).toBeInTheDocument();
  });

  it("clicking a client row navigates to /clients/:id", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const { Route, Routes } = await import("react-router-dom");
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris", holdings: [],
      }],
    }));
    render(
      <MemoryRouter initialEntries={["/clients"]}>
        <Routes>
          <Route path="/clients" element={<ClientsList />} />
          <Route path="/clients/:id" element={<div data-testid="navigated-to">arrived</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await user.click(await screen.findByText("Jane Doe"));
    expect(await screen.findByTestId("navigated-to")).toBeInTheDocument();
  });
});
```

(Delete `frontend/src/data/ClientsList.tsx` and `frontend/src/data/ClientsList.test.tsx` in this same step — `git mv` in Step 5 is cleaner than create+delete, but the test must exist at the new path before Step 2.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/clients/ClientsList.test.tsx`
Expected: FAIL — module not found at `src/clients/ClientsList.tsx` (it hasn't been moved yet), or (once moved verbatim in a first pass) the last test fails because no row is a `role="button"` yet.

- [ ] **Step 3: Write minimal implementation**

Move the file (`git mv frontend/src/data/ClientsList.tsx frontend/src/clients/ClientsList.tsx`), then add navigation. In `frontend/src/clients/ClientsList.tsx`, add the import and wrap each client card:

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getClients, type ClientWithHoldings } from "../lib/api";

export function ClientsList() {
  const navigate = useNavigate();
  const [clients, setClients] = useState<ClientWithHoldings[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getClients()
      .then(setClients)
      .catch(() => setError("Failed to load clients."));
  }, []);

  return (
    <div className="space-y-3 font-mono text-sm text-terminal-text">
      {error && (
        <div className="rounded border border-terminal-danger/40 bg-terminal-danger/10 px-3 py-2 text-xs text-terminal-danger">
          {error}
        </div>
      )}
      {clients.map((c) => (
        <button
          key={c.client_id}
          type="button"
          onClick={() => navigate(`/clients/${c.client_id}`)}
          aria-label={c.name}
          className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 text-left transition-colors hover:border-terminal-accent/50"
        >
          <div className="flex items-center justify-between">
            <span className="font-semibold">{c.name}</span>
            <span className="text-xs text-terminal-muted">{c.email} · {c.segment} · {c.risk_profile}</span>
          </div>
          {c.holdings.length > 0 ? (
            <table className="mt-2 w-full text-xs">
              <thead>
                <tr className="text-left text-terminal-muted">
                  <th className="pr-3">Ticker</th>
                  <th className="pr-3">Shares</th>
                  <th>Avg cost</th>
                </tr>
              </thead>
              <tbody>
                {c.holdings.map((h) => (
                  <tr key={h.ticker} className="border-t border-terminal-border/50">
                    <td className="pr-3 py-1">{h.ticker}</td>
                    <td className="pr-3 py-1">{h.shares}</td>
                    <td className="py-1">${h.avg_cost.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="mt-2 text-xs text-terminal-muted">No holdings.</div>
          )}
        </button>
      ))}
    </div>
  );
}
```

`git mv frontend/src/data/ClientsList.test.tsx frontend/src/clients/ClientsList.test.tsx`, then overwrite it with the Step 1 content above.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/clients/ClientsList.test.tsx`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/clients frontend/src/data
git commit -m "feat(clients): move ClientsList under clients/, make rows navigate to /clients/:id"
```

---

## Task 8: `ClientsPage`

**Files:**
- Create: `frontend/src/clients/ClientsPage.tsx`
- Test: `frontend/src/clients/ClientsPage.test.tsx`

**Interfaces:**
- Consumes: `ClientsList` (Task 7).
- Produces: `ClientsPage` (no props), consumed by Task 11 (`App.tsx` routing).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/clients/ClientsPage.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ClientsPage } from "./ClientsPage";

describe("ClientsPage", () => {
  it("renders the client list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 1, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris", holdings: [],
      }],
    }));
    render(<MemoryRouter><ClientsPage /></MemoryRouter>);
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/clients/ClientsPage.test.tsx`
Expected: FAIL — `ClientsPage.tsx` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/clients/ClientsPage.tsx`:

```tsx
import { ClientsList } from "./ClientsList";

export function ClientsPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto p-4">
      <ClientsList />
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/clients/ClientsPage.test.tsx`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/clients/ClientsPage.tsx frontend/src/clients/ClientsPage.test.tsx
git commit -m "feat(clients): add ClientsPage"
```

---

## Task 9: `getClientSummary` API client

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Produces: `interface ClientSummary { client_id: number; name: string; email: string; segment: string; risk_profile: string; advisor: string; city: string; totals: { market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number } | null; positions: { ticker: string; shares: number; avg_cost: number; price: number; market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number; weight_pct: number; sector: string | null }[]; unpriced_tickers: string[] }` and `getClientSummary(clientId: number, base = API_BASE): Promise<ClientSummary>`. Consumed by Task 10 (`ClientWorkspace`).

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/lib/api.test.ts`, next to the existing `getClients fetches /data/clients` test:

```ts
it("getClientSummary fetches /data/clients/:id/summary", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      client_id: 1, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
      risk_profile: "balanced", advisor: "Sam", city: "Paris",
      totals: { market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33 },
      positions: [], unpriced_tickers: [],
    }),
  });
  vi.stubGlobal("fetch", fetchMock);
  const result = await getClientSummary(1);
  expect(fetchMock).toHaveBeenCalledWith("/data/clients/1/summary");
  expect(result.name).toBe("Jane Doe");
  expect(result.totals?.market_value).toBe(2000);
});
```

Add `getClientSummary` to the `import { ... } from "./api"` line at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/api.test.ts`
Expected: FAIL — `getClientSummary` is not exported.

- [ ] **Step 3: Write minimal implementation**

Add to `frontend/src/lib/api.ts`, after `ClientWithHoldings`/`getClients`:

```ts
export interface ClientSummary {
  client_id: number;
  name: string;
  email: string;
  segment: string;
  risk_profile: string;
  advisor: string;
  city: string;
  totals: { market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number } | null;
  positions: {
    ticker: string; shares: number; avg_cost: number; price: number;
    market_value: number; cost_basis: number; unrealized_pnl: number;
    unrealized_pnl_pct: number; weight_pct: number; sector: string | null;
  }[];
  unpriced_tickers: string[];
}

export async function getClientSummary(clientId: number, base = API_BASE): Promise<ClientSummary> {
  const res = await fetch(`${base}/data/clients/${clientId}/summary`);
  if (!res.ok) throw new Error(`client summary ${res.status}`);
  return res.json();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/api.test.ts`
Expected: all tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts
git commit -m "feat(api): add getClientSummary"
```

---

## Task 10: `ClientWorkspace`

**Files:**
- Create: `frontend/src/clients/ClientWorkspace.tsx`
- Test: `frontend/src/clients/ClientWorkspace.test.tsx`

**Interfaces:**
- Consumes: `getClientSummary` (Task 9), `useIntelligenceSlot`/`IntelligenceSlotProvider` (existing, `frontend/src/layout/IntelligenceSlot.tsx`), `DeskActivityRail` (existing, `frontend/src/desk/DeskActivityRail.tsx`), `MARKET_DESK_AGENT_ID` (existing, `frontend/src/desk/constants.ts`).
- Produces: `ClientWorkspace` (no props — reads `:id` via `useParams`), consumed by Task 11 (`App.tsx` routing).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/clients/ClientWorkspace.test.tsx` (mirrors `frontend/src/desk/DeskView.test.tsx`'s CopilotKit mocking — read that file first if anything below doesn't match its current mock shape):

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const chatProps: Record<string, unknown>[] = [];
vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotKitProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  CopilotChat: (props: Record<string, unknown>) => {
    chatProps.push(props);
    return null;
  },
  HttpAgent: class {},
  useAgent: () => ({ agent: { subscribe: () => ({ unsubscribe: () => undefined }) } }),
}));
vi.mock("../layout/IntelligenceSlot", () => ({ useIntelligenceSlot: () => undefined }));

import { ClientWorkspace } from "./ClientWorkspace";

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/clients/${id}`]}>
      <Routes>
        <Route path="/clients/:id" element={<ClientWorkspace />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ClientWorkspace", () => {
  it("renders the client's profile and computed P&L in the header", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: { market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33 },
        positions: [], unpriced_tickers: [],
      }),
    }));
    renderAt("12");
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText(/VIP/)).toBeInTheDocument();
  });

  it("shows 'no position' copy when totals is null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: null, positions: [], unpriced_tickers: [],
      }),
    }));
    renderAt("12");
    expect(await screen.findByText(/no position/i)).toBeInTheDocument();
  });

  it("passes a client-scoped threadId to CopilotChat", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: null, positions: [], unpriced_tickers: [],
      }),
    }));
    renderAt("12");
    await screen.findByText("Jane Doe");
    expect(chatProps[chatProps.length - 1].threadId).toBe("clients_12");
  });

  it("shows an error banner when the summary fetch fails (e.g. a non-numeric id)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({}) }));
    renderAt("not-a-number");
    expect(await screen.findByText(/failed to load/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/clients/ClientWorkspace.test.tsx`
Expected: FAIL — `ClientWorkspace.tsx` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/clients/ClientWorkspace.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CopilotChat } from "@copilotkit/react-core/v2";
import { MARKET_DESK_AGENT_ID } from "../desk/constants";
import { DeskActivityRail } from "../desk/DeskActivityRail";
import { useIntelligenceSlot } from "../layout/IntelligenceSlot";
import { getClientSummary, type ClientSummary } from "../lib/api";

export function ClientWorkspace() {
  const { id } = useParams<{ id: string }>();
  const clientId = Number(id);
  const [summary, setSummary] = useState<ClientSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intelligencePortal = useIntelligenceSlot(<DeskActivityRail />);

  useEffect(() => {
    setSummary(null);
    setError(null);
    getClientSummary(clientId)
      .then(setSummary)
      .catch(() => setError("Failed to load this client."));
  }, [clientId]);

  return (
    <>
      {intelligencePortal}
      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="border-b border-terminal-border bg-terminal-panel px-4 py-3 font-mono text-sm text-terminal-text">
          {error && <div className="text-terminal-danger">{error}</div>}
          {summary && (
            <div className="flex items-center justify-between">
              <div>
                <span className="font-semibold">{summary.name}</span>
                <span className="ml-2 text-xs text-terminal-muted">
                  {summary.segment} · {summary.risk_profile} · {summary.advisor}
                </span>
              </div>
              {summary.totals ? (
                <span className="text-xs text-terminal-accent">
                  ${summary.totals.market_value.toFixed(2)} ({summary.totals.unrealized_pnl_pct.toFixed(1)}%)
                </span>
              ) : (
                <span className="text-xs text-terminal-muted">No position.</span>
              )}
            </div>
          )}
        </div>
        <CopilotChat
          agentId={MARKET_DESK_AGENT_ID}
          threadId={`clients_${clientId}`}
          className="h-full"
          input={{
            positioning: "static",
            className: "border-t border-terminal-border bg-terminal-panel px-3 py-3",
            textArea:
              "rounded-xl border border-terminal-border bg-terminal-bg px-3.5 py-2.5 font-mono text-sm text-terminal-text placeholder-terminal-muted outline-none transition-colors focus:border-terminal-accent/60",
            sendButton:
              "rounded-xl bg-terminal-accent px-4 py-2.5 font-mono text-sm font-semibold text-terminal-bg shadow-glow-green transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none",
          }}
        />
      </main>
    </>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/clients/ClientWorkspace.test.tsx`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/clients/ClientWorkspace.tsx frontend/src/clients/ClientWorkspace.test.tsx
git commit -m "feat(clients): add ClientWorkspace (profile+P&L header, scoped chat, activity rail)"
```

---

## Task 11: Wire `/clients` and `/clients/:id` routes; trim the 3-placeholder test

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `ClientsPage` (Task 8), `ClientWorkspace` (Task 10).

- [ ] **Step 1: Write the failing test**

In `frontend/src/App.test.tsx`, replace the 3-placeholder test and add two new ones:

```tsx
vi.mock("./clients/ClientWorkspace", () => ({
  ClientWorkspace: () => <div data-testid="client-workspace" />,
}));
```

(add this mock next to the existing `vi.mock("./desk/DeskView", ...)` block at the top of the file)

```tsx
it("the two not-yet-built sections render ComingSoonPage without crashing", () => {
  for (const path of ["/briefing", "/rapports"]) {
    const { unmount } = renderAt(path);
    expect(screen.getByText(/bientôt disponible/i)).toBeInTheDocument();
    unmount();
  }
});

it("/clients renders the client list", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url === "/data/clients") {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.resolve({ ok: true, json: async () => ({ status: "ok", version: "1.2.3" }) });
    }),
  );
  renderAt("/clients");
  expect(screen.queryByTestId("client-workspace")).not.toBeInTheDocument();
});

it("/clients/:id renders the client workspace", () => {
  renderAt("/clients/12");
  expect(screen.getByTestId("client-workspace")).toBeInTheDocument();
});
```

(replace the existing `it("the three not-yet-built sections render ComingSoonPage without crashing", ...)` test with the "two" version above)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL — `/clients` still renders `ComingSoonPage` ("bientôt disponible" still shows there), and `/clients/:id` has no route (404 / blank).

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/App.tsx`, add the imports:

```tsx
import { ClientsPage } from "./clients/ClientsPage";
import { ClientWorkspace } from "./clients/ClientWorkspace";
```

Replace the `/clients` route's `ComingSoonPage` element and add the new route right after it:

```tsx
<Route path="/clients" element={<ClientsPage />} />
<Route path="/clients/:id" element={<ClientWorkspace />} />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: all tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(app): wire /clients and /clients/:id routes"
```

---

## Task 12: Trim `DataPage` to Documents + Import

**Files:**
- Modify: `frontend/src/data/DataPage.tsx`
- Test: Create `frontend/src/data/DataPage.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/data/DataPage.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataPage } from "./DataPage";

describe("DataPage", () => {
  it("only shows the Documents and Import tabs", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    render(<DataPage />);
    expect(screen.getByRole("button", { name: "Documents" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clients" })).not.toBeInTheDocument();
  });

  it("defaults to the Documents tab", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    render(<DataPage />);
    expect(screen.getByRole("button", { name: "Documents" })).toHaveClass("text-terminal-accent");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/data/DataPage.test.tsx`
Expected: FAIL — the default tab is still `"clients"`, so the "Documents" button doesn't have the active class, and a "Clients" button is present.

- [ ] **Step 3: Write minimal implementation**

Replace `frontend/src/data/DataPage.tsx` with:

```tsx
import { useState } from "react";
import { DocumentsList } from "./DocumentsList";
import { ImportPanel } from "./ImportPanel";

type Tab = "documents" | "import";

export function DataPage() {
  const [tab, setTab] = useState<Tab>("documents");

  const tabs: { id: Tab; label: string }[] = [
    { id: "documents", label: "Documents" },
    { id: "import", label: "Import" },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col p-4">
      <div className="mb-3 flex gap-1 overflow-hidden rounded border border-terminal-border self-start">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 font-mono text-xs transition-colors ${
              tab === t.id ? "bg-terminal-accent/15 text-terminal-accent" : "bg-terminal-bg text-terminal-muted hover:text-terminal-text"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {tab === "documents" && <DocumentsList />}
        {tab === "import" && <ImportPanel />}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/data/DataPage.test.tsx`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/data/DataPage.tsx frontend/src/data/DataPage.test.tsx
git commit -m "feat(data): drop the Clients tab, absorbed into /clients"
```

---

## Task 13: Full regression

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend suite**

Run: `uv run pytest tests/ -q`
Expected: all tests pass (413 pre-existing + the new ones from Tasks 1–6).

- [ ] **Step 2: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all tests pass (122 pre-existing + the new ones from Tasks 7–12).

- [ ] **Step 3: Run the frontend build**

Run: `cd frontend && npm run build`
Expected: builds without errors (catches any TypeScript issue the test run didn't, e.g. an unused import left behind by the `DataPage`/`ClientsList` moves).

- [ ] **Step 4: Live QA pass**

With the backend (`uv run uvicorn app.api.server:app --reload`) and frontend (`cd frontend && npm run dev`) running:
1. Open `/clients`, confirm the list renders.
2. Click a client, confirm the workspace opens with their profile + computed P&L (or "No position." if they hold nothing) in the header.
3. Ask a portfolio question without naming the client (e.g. "What's my portfolio worth?"); confirm the answer is about the right client.
4. Reload the page; confirm the conversation resumed (same messages visible).
5. Go back to `/clients`, open a *different* client, ask the same question; confirm no mention of the previous client (no context leakage).
6. Open `/data`; confirm only Documents and Import tabs remain and both still work.

No commit for this task (verification only, no code change expected).
