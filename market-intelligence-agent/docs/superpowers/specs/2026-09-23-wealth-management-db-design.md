# Wealth-Management Database + Portfolio Tools — Design

## Context

The agent's structured-data source is `customers.db` (SQLite), created by
`create_db.py`: one table `customers(id, name, email, status, total_spend)`
with 6 hand-typed rows (including "JAmes Bond"). It has no link to the
market domain — nothing the agent reads from SQL can be combined with
Yahoo Finance prices or the ingested company reports (Pinecone). Multi-step
workflows that mix sources ("which clients are exposed to NVIDIA and what
are their positions worth today?") are impossible.

How the DB is reached today:

- **Local:** `mcp-server-sqlite --db-path customers.db` over stdio
  (`app/agent/tools/mcp_clients/registry.py`). The server offers
  `read_query, write_query, create_table, list_tables, describe_table,
  append_insight`; only `read_query` is selected (`mcp_client.py`).
- **Prod:** Lambda `sqlite_crm` (`prod/lambdas/sqlite_crm/handler.py`)
  downloads `customers.db` from S3 bucket `mia-data` into `/tmp` on cold
  start and opens it read-only. It implements only `read_query`. Nothing
  automated uploads the DB to S3 — it was copied manually during phase 7.

## Decisions (from brainstorming, 2026-09-23)

| Question | Decision |
|---|---|
| Who is the agent's user? | A **wealth-management advisor** following many clients and their portfolios. |
| Data | **~25 hand-written clients**, deterministic seed script, all data in **English**. |
| Read/write | **Read-only.** Matches the prod Lambda; writes are a separate future project. |
| Scope | New DB + schema tools (`list_tables`, `describe_table`) + deterministic financial calc tools. Email drafting is the next project. |
| `fundamentals` table | **Not created.** Report figures already live in the RAG index; duplicating them in SQL creates two sources that can disagree, and non-PDF tickers would need invented numbers. |
| Calc approach | **Typed financial functions** (`portfolio_metrics`, `pct_change`) called by the LLM with numbers copied from tool outputs — not a free-form calculator, not an all-in-one snapshot tool (the DB sits behind a Lambda in prod, so a composite tool can't read it from the agent container). |
| Multi-agent | `crm_agent` becomes **`portfolio_agent`** holding every tool a portfolio computation needs. |
| Prod DB sync | CDK **`BucketDeployment`** uploads `customers.db` from the repo on every deploy. |

## Relationship to the RAG pipeline

**Unchanged:** Pinecone index, `search_knowledge_base` (rerank, 0.35 floor,
`source_filter`), `ingest.py`, `kb_documents.json`. No re-ingestion.

Roles: SQL answers *who holds what, since when*; the knowledge base answers
*what is happening in the company*; Yahoo Finance gives *the current price*.
The agent combines them.

The only link is `companies.kb_document`, which stores the exact ingested
filename (e.g. `Tesla-TSLA-Q2-2026-Update.pdf`) so the agent knows which
companies have a report and which `source_filter` to use. A test enforces
that every non-null `kb_document` exists in `kb_documents.json`.

## Data model

File stays `customers.db` (same S3 key, no Lambda env change). The old
`customers` table is dropped and replaced by:

```sql
CREATE TABLE companies (
    ticker       TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    sector       TEXT NOT NULL,
    kb_document  TEXT              -- ingested PDF filename, or NULL
);

CREATE TABLE clients (
    client_id    INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    email        TEXT NOT NULL UNIQUE,
    segment      TEXT NOT NULL CHECK (segment IN ('VIP','Premium','Standard')),
    risk_profile TEXT NOT NULL CHECK (risk_profile IN ('conservative','balanced','aggressive')),
    advisor      TEXT NOT NULL,
    city         TEXT NOT NULL,
    joined_on    DATE NOT NULL
);

CREATE TABLE transactions (
    txn_id       INTEGER PRIMARY KEY,
    client_id    INTEGER NOT NULL REFERENCES clients(client_id),
    ticker       TEXT NOT NULL REFERENCES companies(ticker),
    side         TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    shares       REAL NOT NULL CHECK (shares > 0),
    price        REAL NOT NULL CHECK (price > 0),
    trade_date   DATE NOT NULL
);

CREATE TABLE holdings (
    client_id    INTEGER NOT NULL REFERENCES clients(client_id),
    ticker       TEXT NOT NULL REFERENCES companies(ticker),
    shares       REAL NOT NULL CHECK (shares > 0),
    avg_cost     REAL NOT NULL CHECK (avg_cost > 0),
    PRIMARY KEY (client_id, ticker)
);

CREATE TABLE watchlists (
    client_id    INTEGER NOT NULL REFERENCES clients(client_id),
    ticker       TEXT NOT NULL REFERENCES companies(ticker),
    alert_price  REAL NOT NULL CHECK (alert_price > 0),
    direction    TEXT NOT NULL CHECK (direction IN ('above','below')),
    PRIMARY KEY (client_id, ticker)
);
```

**Consistency by construction.** The seed writes only `transactions`;
`holdings` is **derived**: `shares = Σ BUY − Σ SELL`, `avg_cost` = weighted
average cost of shares still held (average-cost method: sells reduce shares
at the running average, they don't change it). Positions that net to zero
produce no `holdings` row. Sells never exceed shares held at trade date.

**Content.**

- ~14 tickers: AMZN, TSLA, NVDA, GS (have a `kb_document`), MSFT, AAPL,
  GOOGL, META, JPM, JNJ, KO, XOM, SPY, BND (ETFs; sector `ETF`).
- ~25 clients with coherent profiles (e.g. conservative retiree in JNJ/KO/BND,
  aggressive tech founder concentrated in NVDA/TSLA, balanced banker in
  GS/JPM/MSFT). The user is one VIP client with `yanivbohbot5@gmail.com`
  (the only SES-verified address, so the only real send target in tests);
  every other email is `@example.com`.
- ~150 transactions, 2022–2026, at plausible period prices.
- Deliberate QA fixtures: a conservative client >30% in NVDA (concentration
  risk); a client who fully sold a ticker (history, no holding); watchlist
  alerts set near current prices.

`create_db.py` becomes the seed script (deterministic: same output every
run; it deletes and rebuilds the file). The regenerated `customers.db` is
committed.

## Tools

### Schema tools (read-only, no approval)

- `list_tables()` — table names.
- `describe_table(table_name)` — columns and types.
- **Local:** selected from the existing `mcp-server-sqlite` registry, like
  `read_query` (`mcp_client.py`). `write_query`, `create_table`,
  `append_insight` stay unselected.
- **Prod:** added to `prod/lambdas/sqlite_crm/handler.py` `_DISPATCH` and
  `tool_schema.json`, returning the same shape as the local server.
  `describe_table` validates the name against `sqlite_master` before running
  `PRAGMA table_info`; unknown names return the list of existing tables.

### Financial calc tools (native, read-only, no approval) — `app/agent/tools/finance_calc.py`

- `portfolio_metrics(positions: list[{ticker, shares, avg_cost, price, sector?}])`
  → per position: `market_value`, `cost_basis`, `unrealized_pnl`,
  `unrealized_pnl_pct`, `weight_pct`; totals: `total_market_value`,
  `total_cost_basis`, `total_unrealized_pnl`, `total_unrealized_pnl_pct`;
  `sector_allocation` (pct by sector) when every position has a sector.
  Validation: `shares > 0`, `avg_cost > 0`, `price > 0`, no duplicate ticker,
  at least one position. Money rounded to 2 decimals, percentages to 2.
- `pct_change(old, new)` → `{change, pct_change}`; error if `old == 0`.
- Pure functions; run in the agent container (no Lambda) in both local and prod.

### Registration

All four added to `TOOLS` and `READ_ONLY_TOOLS`; `docs/TOOLS.md` gets a
summary row and a per-tool section for each (project rule), and the
`read_query` entry is updated for the new schema. `CLAUDE.md` (tool table,
`READ_ONLY_TOOLS` list, `create_db.py` description) is updated to match.
Gateway-prefixed names (`sqlite-crm___list_tables`) are already handled by
`is_read_only`.

## Prompts and agents

### Single-agent (`app/agent/prompts/system.py`; also used by voice)

- Remove the hard-coded `customers` schema.
- Add a one-line-per-table DB overview and "call `describe_table` when unsure
  about a column".
- Source roles: SQL = who holds what; knowledge base = company reports;
  Yahoo Finance = live prices. Use `companies.kb_document` as `source_filter`.
- Portfolio recipe: read `holdings` (+ `companies.sector`) → fetch prices in
  parallel → `portfolio_metrics`. **Never do arithmetic in the answer; use
  `portfolio_metrics` / `pct_change`.**

### Multi-agent

- `crm_agent.py` → `portfolio_agent.py` with tools `read_query`,
  `list_tables`, `describe_table`, `yfinance_get_ticker_info`,
  `portfolio_metrics`, `pct_change`; prompt `PORTFOLIO_SYSTEM_PROMPT`
  (with `with_today`).
- Supervisor `RoutingDecision` literals, `supervisor_node` return type,
  `SUPERVISOR_ROUTING_PROMPT`, `multi_agent/graph.py` and tests renamed.
- **Known limitation, not fixed here:** the supervisor's deterministic finish
  (end as soon as a specialist returns a plain answer) prevents chaining
  specialists (e.g. `rag_agent` → `portfolio_agent`). Portfolio math works
  inside one specialist; cross-specialist chaining is a prerequisite for the
  multi-agent API cutover. The API serves the single agent, which chains all
  tools freely.

## Prod deployment

- CDK: `BucketDeployment` of `customers.db` into the `mia-data` bucket (key
  `customers.db`) in the stack that owns the bucket, so every deploy syncs S3
  with git. The Lambda code change recycles instances, which re-download the DB.
- Lambda `sqlite_crm`: new tools as above.

## Error handling

The graphs already use `ToolNode(handle_tool_errors=True)`: tool exceptions
become `ToolMessage`s the LLM can react to.

- Calc tools raise clear `ValueError`s on invalid input.
- `describe_table` on an unknown table returns the table list.
- Invalid SQL returns the SQLite error; the LLM can retry.

## Testing

**Unit (TDD):**

- Seed: `holdings` equals aggregated `transactions`; no sell exceeds shares
  held; every non-null `kb_document` is in `kb_documents.json`; foreign keys
  valid; only the user's email is outside `@example.com`; QA fixtures present;
  running the seed twice yields identical data.
- Calc: hand-computed values, sector allocation, rounding, every validation error.
- Lambda: `list_tables`, `describe_table` (incl. injection attempt such as
  `clients; DROP TABLE clients`), `read_query` still works, unknown tool.
- Registration: tools in `TOOLS` / `READ_ONLY_TOOLS`; `portfolio_agent`
  compiles with expected nodes; supervisor routes to `portfolio_agent`.

**Live grounded QA** (added to the QA battery; expected values computed from
the DB and from the tool outputs, never from the agent):

- "Which clients hold NVDA?" — exact client set vs a reference SQL query.
- "How is <client>'s portfolio performing?" — figures match
  `portfolio_metrics` on the prices yfinance returned in that run.
- "Which conservative clients are concentrated in a single stock?" — finds
  the seeded fixture.
- "Tesla reported Q2 deliveries — which clients hold TSLA?" — single agent
  chains RAG + SQL.
- The existing 16 cases keep passing (the old CRM case is rewritten for the
  new schema).

## Explicitly out of scope

- Writing to the DB (interaction logs, watchlist edits).
- `create_email_draft`, report/chart generation, anti-injection prompt rule
  (next project: deliverables & email).
- Scheduler / price alerts firing automatically.
- Supervisor multi-specialist chaining (multi-agent API cutover).
- PostgreSQL / RDS.
