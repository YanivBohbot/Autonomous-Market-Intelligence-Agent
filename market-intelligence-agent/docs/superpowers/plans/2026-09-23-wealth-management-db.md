# Wealth-Management Database + Portfolio Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 6-row `customers` table with an advisor-facing wealth-management database, add read-only schema tools and deterministic portfolio calc tools, and wire them into the single agent, the multi-agent `portfolio_agent`, the prod Lambda and the CDK deploy.

**Architecture:** `create_db.py` deterministically seeds `customers.db` (companies, clients, transactions, derived holdings, watchlists). The SQLite MCP server (local) / `sqlite_crm` Lambda (prod) expose `read_query`, `list_tables`, `describe_table`; `portfolio_metrics` and `pct_change` are native Python tools running in the agent container. The LLM chains SQL → yfinance → calc tools.

**Tech Stack:** Python 3.12, sqlite3, LangChain tools + Pydantic v2, LangGraph, `mcp-server-sqlite`, AWS Lambda (boto3), AWS CDK (Python, `aws-cdk-lib==2.258.0`), pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-23-wealth-management-db-design.md`

## Global Constraints

- Work on branch `feature/wealth-management-db`; commit after each task; never push.
- All commands run from `market-intelligence-agent/` with `uv run` unless stated (`prod/` paths are relative to the repo root `F:/langchain-langgraph-mcp/market-agent`).
- All seeded data is in **English**. Only the user's client record uses a real address (`yanivbohbot5@gmail.com`); every other email ends with `@example.com`.
- DB file name stays `customers.db` (same S3 key `customers.db`, no Lambda env change).
- **Read-only**: never expose `write_query`, `create_table`, `append_insight`.
- No `fundamentals` table.
- Every new tool goes into `TOOLS`, `READ_ONLY_TOOLS` and `docs/TOOLS.md` (project rule in `CLAUDE.md`).
- Tool names exactly: `list_tables`, `describe_table`, `portfolio_metrics`, `pct_change`.
- Before running `create_db.py`, stop any running backend/Streamlit (on Windows an open `customers.db` handle blocks the delete).
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Ef16qzkiyktnMEUerKmyNs
  ```

---

### Task 1: Deterministic wealth-management seed (`create_db.py`)

**Files:**
- Rewrite: `create_db.py`
- Regenerate + commit: `customers.db`
- Test: `tests/unit/test_wealth_db_seed.py`

**Interfaces:**
- Consumes: `app.agent.tools.knowledge_base.KB_MANIFEST_PATH` (Path to `kb_documents.json`).
- Produces (module `create_db`): `DB_PATH: Path`, `COMPANIES`, `CLIENTS`, `TRADES`, `WATCHLISTS`, `PRICE_ANCHORS`, `price_at(ticker: str, day: date) -> float`, `build_transactions() -> list[tuple]` (rows `(txn_id, client_id, ticker, side, shares, price, trade_date)`), `derive_holdings(transactions) -> list[tuple]` (rows `(client_id, ticker, shares, avg_cost)`), `create_db(path: Path = DB_PATH) -> None`. Tables: `companies`, `clients`, `transactions`, `holdings`, `watchlists` (schema in the spec).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_wealth_db_seed.py`:

```python
import json
import sqlite3
from datetime import date

import pytest

import create_db as seed
from app.agent.tools.knowledge_base import KB_MANIFEST_PATH


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "customers.db"
    seed.create_db(path)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    yield con
    con.close()


def test_schema_has_exactly_the_wealth_tables(db):
    names = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"companies", "clients", "transactions", "holdings", "watchlists"}


def test_seed_sizes(db):
    assert db.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 25
    assert db.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 14
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] >= 100


def test_foreign_keys_are_valid(db):
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_no_buy_after_a_sell_on_the_same_position(db):
    """Keeps the average-cost check below valid: with no BUY after a SELL,
    avg_cost equals the weighted average of all BUYs."""
    rows = db.execute("""
        SELECT b.client_id, b.ticker FROM transactions b
        JOIN transactions s ON s.client_id = b.client_id AND s.ticker = b.ticker
        WHERE b.side = 'BUY' AND s.side = 'SELL' AND b.trade_date > s.trade_date
    """).fetchall()
    assert rows == []


def test_holdings_match_aggregated_transactions(db):
    agg = db.execute("""
        SELECT client_id, ticker,
               SUM(CASE WHEN side = 'BUY' THEN shares ELSE -shares END) AS net,
               SUM(CASE WHEN side = 'BUY' THEN shares * price END)
                 / SUM(CASE WHEN side = 'BUY' THEN shares END) AS buy_avg
        FROM transactions GROUP BY client_id, ticker
    """).fetchall()
    holdings = {(r["client_id"], r["ticker"]): r for r in db.execute("SELECT * FROM holdings")}
    open_positions = 0
    for r in agg:
        key = (r["client_id"], r["ticker"])
        if r["net"] < 1e-9:
            assert key not in holdings
            continue
        open_positions += 1
        assert holdings[key]["shares"] == pytest.approx(r["net"])
        assert holdings[key]["avg_cost"] == pytest.approx(r["buy_avg"], abs=0.01)
    assert len(holdings) == open_positions


def test_every_kb_document_is_an_ingested_file(db):
    manifest = set(json.loads(KB_MANIFEST_PATH.read_text(encoding="utf-8")))
    docs = {r["ticker"]: r["kb_document"] for r in db.execute("SELECT ticker, kb_document FROM companies")}
    assert {t for t, d in docs.items() if d} == {"AMZN", "TSLA", "NVDA", "GS"}
    assert {d for d in docs.values() if d} <= manifest


def test_only_the_user_has_a_real_email(db):
    real = [r["email"] for r in db.execute("SELECT email FROM clients") if not r["email"].endswith("@example.com")]
    assert real == ["yanivbohbot5@gmail.com"]


def test_fixture_conservative_client_concentrated_in_nvda(db):
    client = db.execute("SELECT client_id, risk_profile FROM clients WHERE name = 'Margaret Collins'").fetchone()
    assert client["risk_profile"] == "conservative"
    rows = db.execute("SELECT ticker, shares FROM holdings WHERE client_id = ?", (client["client_id"],)).fetchall()
    values = {r["ticker"]: r["shares"] * seed.price_at(r["ticker"], date(2026, 7, 1)) for r in rows}
    assert values["NVDA"] / sum(values.values()) > 0.30


def test_fixture_client_fully_sold_tsla(db):
    cid = db.execute("SELECT client_id FROM clients WHERE name = 'Robert Hayes'").fetchone()[0]
    assert db.execute("SELECT COUNT(*) FROM transactions WHERE client_id = ? AND ticker = 'TSLA'", (cid,)).fetchone()[0] > 0
    assert db.execute("SELECT COUNT(*) FROM holdings WHERE client_id = ? AND ticker = 'TSLA'", (cid,)).fetchone()[0] == 0


def test_seed_is_deterministic(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    seed.create_db(a)
    seed.create_db(b)
    dump = lambda p: list(sqlite3.connect(p).iterdump())
    assert dump(a) == dump(b)


def test_price_at_interpolates_and_clamps():
    assert seed.price_at("KO", date(2022, 7, 1)) == 62.0
    assert seed.price_at("KO", date(2022, 12, 31)) == pytest.approx(61.5, abs=0.01)
    assert seed.price_at("KO", date(2021, 1, 1)) == 62.0
    assert seed.price_at("KO", date(2030, 1, 1)) == 71.0


def test_derive_holdings_rejects_overselling():
    txns = [
        (1, 1, "KO", "BUY", 1.0, 10.0, "2022-01-01"),
        (2, 1, "KO", "SELL", 2.0, 10.0, "2022-02-01"),
    ]
    with pytest.raises(ValueError, match="sells"):
        seed.derive_holdings(txns)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_wealth_db_seed.py -q -p no:warnings`
Expected: FAIL/ERROR — `create_db` has no `create_db` / `price_at` attribute.

- [ ] **Step 3: Rewrite `create_db.py`**

Replace the whole file with:

```python
"""Seed the wealth-management SQLite database (customers.db).

Deterministic: every run deletes and rebuilds the file with identical data.
Only TRADES is hand-written; `transactions` gets prices from PRICE_ANCHORS
and `holdings` is DERIVED from transactions (average-cost method), so
positions can never contradict the trade history. All data is fictional
except the user's own client record (the only SES-verified address).

Run: `uv run python create_db.py`, then commit customers.db.
"""

import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).with_name("customers.db")

SCHEMA = """
CREATE TABLE companies (
    ticker       TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    sector       TEXT NOT NULL,
    kb_document  TEXT
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
"""

# kb_document must match app/agent/tools/kb_documents.json exactly.
COMPANIES = [
    ("AMZN", "Amazon.com, Inc.", "Consumer Discretionary", "Amazon-2024-Annual-Report.pdf"),
    ("TSLA", "Tesla, Inc.", "Consumer Discretionary", "Tesla-TSLA-Q2-2026-Update.pdf"),
    ("NVDA", "NVIDIA Corporation", "Information Technology", "NVIDIA-NVDA-2026-Annual-Report.pdf"),
    ("GS", "The Goldman Sachs Group, Inc.", "Financials", "Goldman-Sachs-GS-2025-Annual-Report.pdf"),
    ("MSFT", "Microsoft Corporation", "Information Technology", None),
    ("AAPL", "Apple Inc.", "Information Technology", None),
    ("GOOGL", "Alphabet Inc. (Class A)", "Communication Services", None),
    ("META", "Meta Platforms, Inc.", "Communication Services", None),
    ("JPM", "JPMorgan Chase & Co.", "Financials", None),
    ("JNJ", "Johnson & Johnson", "Health Care", None),
    ("KO", "The Coca-Cola Company", "Consumer Staples", None),
    ("XOM", "Exxon Mobil Corporation", "Energy", None),
    ("SPY", "SPDR S&P 500 ETF Trust", "ETF", None),
    ("BND", "Vanguard Total Bond Market ETF", "ETF", None),
]

# Approximate split-adjusted prices on July 1 of each year. Trade prices are
# linearly interpolated between anchors and clamped outside the range.
PRICE_ANCHORS = {
    "AMZN": {2022: 115, 2023: 130, 2024: 195, 2025: 215, 2026: 235},
    "TSLA": {2022: 240, 2023: 260, 2024: 220, 2025: 320, 2026: 400},
    "NVDA": {2022: 17, 2023: 42, 2024: 125, 2025: 155, 2026: 215},
    "GS": {2022: 300, 2023: 330, 2024: 470, 2025: 690, 2026: 820},
    "MSFT": {2022: 260, 2023: 335, 2024: 450, 2025: 490, 2026: 500},
    "AAPL": {2022: 145, 2023: 190, 2024: 215, 2025: 210, 2026: 250},
    "GOOGL": {2022: 112, 2023: 120, 2024: 180, 2025: 175, 2026: 260},
    "META": {2022: 165, 2023: 290, 2024: 505, 2025: 720, 2026: 700},
    "JPM": {2022: 115, 2023: 145, 2024: 205, 2025: 285, 2026: 305},
    "JNJ": {2022: 175, 2023: 160, 2024: 150, 2025: 155, 2026: 190},
    "KO": {2022: 62, 2023: 61, 2024: 65, 2025: 70, 2026: 71},
    "XOM": {2022: 88, 2023: 105, 2024: 115, 2025: 110, 2026: 112},
    "SPY": {2022: 380, 2023: 445, 2024: 545, 2025: 620, 2026: 680},
    "BND": {2022: 74, 2023: 72, 2024: 72, 2025: 73, 2026: 74},
}

# (client_id, name, email, segment, risk_profile, advisor, city, joined_on)
CLIENTS = [
    (1, "Yaniv Bohbot", "yanivbohbot5@gmail.com", "VIP", "aggressive", "Sarah Mitchell", "Tel Aviv", "2022-01-05"),
    (2, "Margaret Collins", "margaret.collins@example.com", "Premium", "conservative", "David Chen", "Boston", "2022-01-12"),
    (3, "Martin Levy", "martin.levy@example.com", "VIP", "balanced", "Sarah Mitchell", "New York", "2022-02-01"),
    (4, "Robert Hayes", "robert.hayes@example.com", "Standard", "aggressive", "Emma Rodriguez", "Austin", "2022-03-01"),
    (5, "Linda Park", "linda.park@example.com", "Premium", "balanced", "David Chen", "Seattle", "2022-02-15"),
    (6, "James Whitaker", "james.whitaker@example.com", "VIP", "aggressive", "Sarah Mitchell", "San Francisco", "2022-04-01"),
    (7, "Susan Grant", "susan.grant@example.com", "Standard", "conservative", "Emma Rodriguez", "Phoenix", "2022-05-10"),
    (8, "Daniel Foster", "daniel.foster@example.com", "Premium", "balanced", "David Chen", "Chicago", "2022-06-01"),
    (9, "Olivia Bennett", "olivia.bennett@example.com", "VIP", "balanced", "Sarah Mitchell", "Miami", "2022-07-01"),
    (10, "Thomas Reed", "thomas.reed@example.com", "Standard", "aggressive", "Emma Rodriguez", "Denver", "2022-08-15"),
    (11, "Emily Carter", "emily.carter@example.com", "Premium", "conservative", "David Chen", "Portland", "2022-09-01"),
    (12, "Michael Torres", "michael.torres@example.com", "Premium", "aggressive", "Sarah Mitchell", "Los Angeles", "2022-10-01"),
    (13, "Rachel Kim", "rachel.kim@example.com", "VIP", "balanced", "David Chen", "New York", "2022-11-01"),
    (14, "William Hughes", "william.hughes@example.com", "Standard", "balanced", "Emma Rodriguez", "Atlanta", "2022-12-01"),
    (15, "Jessica Morgan", "jessica.morgan@example.com", "Premium", "aggressive", "Sarah Mitchell", "San Diego", "2023-01-15"),
    (16, "Christopher Lee", "christopher.lee@example.com", "Standard", "conservative", "David Chen", "Philadelphia", "2023-02-01"),
    (17, "Amanda Brooks", "amanda.brooks@example.com", "VIP", "conservative", "Sarah Mitchell", "Charlotte", "2023-03-01"),
    (18, "Kevin Nguyen", "kevin.nguyen@example.com", "Premium", "aggressive", "Emma Rodriguez", "San Jose", "2023-04-01"),
    (19, "Patricia Wallace", "patricia.wallace@example.com", "Standard", "balanced", "David Chen", "Minneapolis", "2023-05-01"),
    (20, "Brian Connor", "brian.connor@example.com", "Premium", "balanced", "Sarah Mitchell", "Boston", "2023-06-01"),
    (21, "Natalie Diaz", "natalie.diaz@example.com", "VIP", "aggressive", "Emma Rodriguez", "Las Vegas", "2023-08-01"),
    (22, "George Palmer", "george.palmer@example.com", "Standard", "conservative", "David Chen", "Tampa", "2023-10-01"),
    (23, "Hannah Schultz", "hannah.schultz@example.com", "Premium", "balanced", "Sarah Mitchell", "Nashville", "2024-01-15"),
    (24, "Samuel Ortiz", "samuel.ortiz@example.com", "Standard", "aggressive", "Emma Rodriguez", "Houston", "2024-06-01"),
    (25, "Victoria Hale", "victoria.hale@example.com", "VIP", "balanced", "David Chen", "Dallas", "2024-09-01"),
]

# (client_id, trade_date, ticker, side, shares). QA fixtures:
#  - client 2 (Margaret Collins, conservative) is >30% in NVDA
#  - client 4 (Robert Hayes) bought then fully sold TSLA
TRADES = [
    (1, "2022-02-14", "NVDA", "BUY", 300), (1, "2022-09-12", "TSLA", "BUY", 40),
    (1, "2023-03-20", "MSFT", "BUY", 30), (1, "2024-02-05", "AMZN", "BUY", 60),
    (1, "2024-11-18", "NVDA", "SELL", 100), (1, "2025-05-12", "META", "BUY", 20),
    (2, "2022-01-20", "JNJ", "BUY", 100), (2, "2022-01-20", "KO", "BUY", 200),
    (2, "2022-03-15", "BND", "BUY", 200), (2, "2023-01-17", "NVDA", "BUY", 400),
    (2, "2024-06-10", "BND", "BUY", 100),
    (3, "2022-02-10", "GS", "BUY", 80), (3, "2022-02-10", "JPM", "BUY", 150),
    (3, "2022-10-03", "MSFT", "BUY", 60), (3, "2023-05-22", "SPY", "BUY", 50),
    (3, "2024-08-19", "GS", "SELL", 20), (3, "2025-03-10", "AAPL", "BUY", 50),
    (4, "2022-03-08", "TSLA", "BUY", 50), (4, "2023-02-13", "TSLA", "BUY", 30),
    (4, "2024-04-22", "TSLA", "SELL", 80), (4, "2024-05-06", "GOOGL", "BUY", 40),
    (4, "2025-01-13", "AMZN", "BUY", 25),
    (5, "2022-02-22", "AMZN", "BUY", 70), (5, "2022-02-22", "MSFT", "BUY", 40),
    (5, "2023-06-12", "SPY", "BUY", 30), (5, "2024-09-09", "BND", "BUY", 150),
    (5, "2025-07-14", "AMZN", "SELL", 20),
    (6, "2022-04-11", "NVDA", "BUY", 1000), (6, "2022-04-11", "TSLA", "BUY", 60),
    (6, "2023-08-21", "META", "BUY", 50), (6, "2024-03-04", "NVDA", "SELL", 300),
    (6, "2025-02-10", "TSLA", "BUY", 40), (6, "2026-01-12", "GOOGL", "BUY", 100),
    (7, "2022-05-16", "KO", "BUY", 150), (7, "2022-05-16", "JNJ", "BUY", 60),
    (7, "2023-04-10", "BND", "BUY", 250), (7, "2025-09-15", "XOM", "BUY", 40),
    (8, "2022-06-13", "JPM", "BUY", 100), (8, "2022-06-13", "XOM", "BUY", 120),
    (8, "2023-10-02", "AAPL", "BUY", 60), (8, "2024-12-09", "XOM", "SELL", 50),
    (8, "2025-06-02", "SPY", "BUY", 25),
    (9, "2022-07-11", "AAPL", "BUY", 200), (9, "2022-07-11", "MSFT", "BUY", 100),
    (9, "2023-01-09", "GOOGL", "BUY", 150), (9, "2024-05-20", "AMZN", "BUY", 80),
    (9, "2025-10-06", "AAPL", "SELL", 50),
    (10, "2022-08-22", "TSLA", "BUY", 25), (10, "2023-11-13", "NVDA", "BUY", 120),
    (10, "2024-07-15", "META", "BUY", 15), (10, "2025-04-07", "NVDA", "BUY", 50),
    (11, "2022-09-06", "BND", "BUY", 400), (11, "2022-09-06", "JNJ", "BUY", 50),
    (11, "2023-07-17", "KO", "BUY", 100), (11, "2024-10-14", "SPY", "BUY", 20),
    (12, "2022-10-10", "META", "BUY", 120), (12, "2023-02-27", "NVDA", "BUY", 200),
    (12, "2024-01-22", "META", "SELL", 40), (12, "2025-08-11", "TSLA", "BUY", 35),
    (13, "2022-11-14", "GS", "BUY", 60), (13, "2022-11-14", "AMZN", "BUY", 100),
    (13, "2023-09-18", "MSFT", "BUY", 50), (13, "2024-06-24", "JPM", "BUY", 80),
    (13, "2026-02-09", "GS", "BUY", 15),
    (14, "2022-12-05", "SPY", "BUY", 20), (14, "2023-12-11", "AAPL", "BUY", 30),
    (14, "2025-03-24", "BND", "BUY", 60),
    (15, "2023-01-23", "TSLA", "BUY", 70), (15, "2023-01-23", "AMZN", "BUY", 50),
    (15, "2024-09-30", "TSLA", "SELL", 30), (15, "2025-11-17", "NVDA", "BUY", 90),
    (16, "2023-02-06", "KO", "BUY", 120), (16, "2023-02-06", "XOM", "BUY", 50),
    (16, "2024-03-18", "BND", "BUY", 100),
    (17, "2023-03-06", "BND", "BUY", 800), (17, "2023-03-06", "JNJ", "BUY", 150),
    (17, "2023-03-06", "KO", "BUY", 300), (17, "2024-02-26", "JPM", "BUY", 100),
    (17, "2025-05-19", "SPY", "BUY", 60),
    (18, "2023-04-17", "NVDA", "BUY", 300), (18, "2023-04-17", "META", "BUY", 40),
    (18, "2024-08-05", "GOOGL", "BUY", 80), (18, "2025-01-27", "NVDA", "SELL", 100),
    (18, "2026-03-16", "AAPL", "BUY", 40),
    (19, "2023-05-08", "MSFT", "BUY", 20), (19, "2023-05-08", "JNJ", "BUY", 40),
    (19, "2024-11-04", "SPY", "BUY", 15),
    (20, "2023-06-05", "GS", "BUY", 40), (20, "2023-06-05", "XOM", "BUY", 100),
    (20, "2024-04-08", "AMZN", "BUY", 40), (20, "2025-09-29", "GS", "SELL", 10),
    (21, "2023-08-14", "TSLA", "BUY", 150), (21, "2023-08-14", "NVDA", "BUY", 500),
    (21, "2024-12-16", "TSLA", "SELL", 50), (21, "2025-06-23", "META", "BUY", 60),
    (21, "2026-05-11", "AMZN", "BUY", 100),
    (22, "2023-10-09", "BND", "BUY", 150), (22, "2023-10-09", "KO", "BUY", 80),
    (22, "2025-02-24", "JNJ", "BUY", 30),
    (23, "2024-01-22", "AAPL", "BUY", 70), (23, "2024-01-22", "GOOGL", "BUY", 60),
    (23, "2025-04-21", "MSFT", "BUY", 25), (23, "2026-06-08", "AAPL", "SELL", 20),
    (24, "2024-06-17", "NVDA", "BUY", 80), (24, "2024-06-17", "TSLA", "BUY", 20),
    (24, "2025-10-20", "META", "BUY", 10),
    (25, "2024-09-16", "SPY", "BUY", 100), (25, "2024-09-16", "JPM", "BUY", 120),
    (25, "2025-01-06", "GS", "BUY", 30), (25, "2026-04-13", "MSFT", "BUY", 40),
]

# (client_id, ticker, alert_price, direction) — set near late-2026 prices.
WATCHLISTS = [
    (1, "TSLA", 450.0, "above"), (1, "GOOGL", 240.0, "below"),
    (2, "NVDA", 200.0, "below"), (3, "GS", 900.0, "above"),
    (5, "AMZN", 220.0, "below"), (6, "NVDA", 250.0, "above"),
    (9, "AAPL", 230.0, "below"), (12, "META", 650.0, "below"),
    (13, "JPM", 320.0, "above"), (17, "KO", 65.0, "below"),
    (18, "NVDA", 240.0, "above"), (21, "TSLA", 350.0, "below"),
]


def price_at(ticker: str, day: date) -> float:
    anchors = sorted((date(year, 7, 1), price) for year, price in PRICE_ANCHORS[ticker].items())
    if day <= anchors[0][0]:
        return round(float(anchors[0][1]), 2)
    if day >= anchors[-1][0]:
        return round(float(anchors[-1][1]), 2)
    for (d0, p0), (d1, p1) in zip(anchors, anchors[1:]):
        if d0 <= day <= d1:
            t = (day - d0).days / (d1 - d0).days
            return round(p0 + t * (p1 - p0), 2)
    raise AssertionError(f"no anchor interval for {ticker} on {day}")


def build_transactions() -> list[tuple]:
    ordered = sorted(TRADES, key=lambda t: (t[1], t[0], t[2]))
    return [
        (txn_id, client_id, ticker, side, float(shares), price_at(ticker, date.fromisoformat(day)), day)
        for txn_id, (client_id, day, ticker, side, shares) in enumerate(ordered, start=1)
    ]


def derive_holdings(transactions) -> list[tuple]:
    """Average-cost method: BUYs add shares and cost; SELLs remove shares at
    the running average (the average itself is unchanged)."""
    shares: dict[tuple, float] = defaultdict(float)
    cost: dict[tuple, float] = defaultdict(float)
    for _txn_id, client_id, ticker, side, qty, price, day in sorted(transactions, key=lambda r: (r[6], r[0])):
        key = (client_id, ticker)
        if side == "BUY":
            shares[key] += qty
            cost[key] += qty * price
            continue
        if qty > shares[key] + 1e-9:
            raise ValueError(f"client {client_id} sells {qty} {ticker} on {day} but holds {shares[key]}")
        avg = cost[key] / shares[key]
        shares[key] -= qty
        cost[key] -= avg * qty
    return sorted(
        (client_id, ticker, round(qty, 4), round(cost[(client_id, ticker)] / qty, 2))
        for (client_id, ticker), qty in shares.items()
        if qty > 1e-9
    )


def create_db(path: Path = DB_PATH) -> None:
    path = Path(path)
    path.unlink(missing_ok=True)
    transactions = build_transactions()
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(SCHEMA)
        con.executemany("INSERT INTO companies VALUES (?, ?, ?, ?)", COMPANIES)
        con.executemany("INSERT INTO clients VALUES (?, ?, ?, ?, ?, ?, ?, ?)", CLIENTS)
        con.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?)", transactions)
        con.executemany("INSERT INTO holdings VALUES (?, ?, ?, ?)", derive_holdings(transactions))
        con.executemany("INSERT INTO watchlists VALUES (?, ?, ?, ?)", WATCHLISTS)
        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    create_db()
    print(f"✅ Wealth-management database written to {DB_PATH}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_wealth_db_seed.py -q -p no:warnings`
Expected: 12 passed.

- [ ] **Step 5: Regenerate the real DB and sanity-check it**

Run:
```bash
uv run python create_db.py
uv run python -c "import sqlite3; c=sqlite3.connect('customers.db'); print([r[0] for r in c.execute(\"select name from sqlite_master where type='table' order by name\")]); print(c.execute('select count(*) from holdings').fetchone())"
```
Expected: `['clients', 'companies', 'holdings', 'transactions', 'watchlists']` and a holdings count between 80 and 100.

- [ ] **Step 6: Commit**

```bash
git add create_db.py customers.db tests/unit/test_wealth_db_seed.py
git commit -m "feat(db): deterministic wealth-management seed replaces customers table"
```

---

### Task 2: Deterministic portfolio calc tools (`finance_calc.py`)

**Files:**
- Create: `app/agent/tools/finance_calc.py`
- Test: `tests/unit/test_finance_calc.py`

**Interfaces:**
- Produces: `Position` (Pydantic: `ticker: str`, `shares: float > 0`, `avg_cost: float > 0`, `price: float > 0`, `sector: str | None = None`), `compute_portfolio_metrics(positions: list[Position]) -> dict`, `compute_pct_change(old: float, new: float) -> dict`, LangChain tools `portfolio_metrics_tool` (name `"portfolio_metrics"`, arg `positions`) and `pct_change_tool` (name `"pct_change"`, args `old`, `new`).
- Output of `compute_portfolio_metrics`: `{"positions": [{"ticker", "shares", "avg_cost", "price", "sector", "market_value", "cost_basis", "unrealized_pnl", "unrealized_pnl_pct", "weight_pct"}], "totals": {"market_value", "cost_basis", "unrealized_pnl", "unrealized_pnl_pct"}, "sector_allocation": {sector: pct} | None}`.
- Output of `compute_pct_change`: `{"old", "new", "change", "pct_change"}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_finance_calc.py`:

```python
import pytest

from app.agent.tools.finance_calc import (
    Position,
    compute_pct_change,
    compute_portfolio_metrics,
    pct_change_tool,
    portfolio_metrics_tool,
)


def _positions(with_sector=True):
    return [
        Position(ticker="AAA", shares=10, avg_cost=50, price=60, sector="Tech" if with_sector else None),
        Position(ticker="BBB", shares=5, avg_cost=100, price=80, sector="Energy" if with_sector else None),
    ]


def test_per_position_metrics():
    result = compute_portfolio_metrics(_positions())
    aaa, bbb = result["positions"]
    assert (aaa["market_value"], aaa["cost_basis"], aaa["unrealized_pnl"], aaa["unrealized_pnl_pct"], aaa["weight_pct"]) == (600.0, 500.0, 100.0, 20.0, 60.0)
    assert (bbb["market_value"], bbb["cost_basis"], bbb["unrealized_pnl"], bbb["unrealized_pnl_pct"], bbb["weight_pct"]) == (400.0, 500.0, -100.0, -20.0, 40.0)


def test_totals():
    assert compute_portfolio_metrics(_positions())["totals"] == {
        "market_value": 1000.0, "cost_basis": 1000.0, "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0,
    }


def test_sector_allocation_when_every_position_has_a_sector():
    assert compute_portfolio_metrics(_positions())["sector_allocation"] == {"Tech": 60.0, "Energy": 40.0}


def test_sector_allocation_is_none_when_a_sector_is_missing():
    assert compute_portfolio_metrics(_positions(with_sector=False))["sector_allocation"] is None


def test_rounding_to_two_decimals():
    result = compute_portfolio_metrics([Position(ticker="X", shares=3, avg_cost=10.006, price=33.333)])
    p = result["positions"][0]
    assert p["market_value"] == 100.0
    assert p["cost_basis"] == 30.02
    assert p["weight_pct"] == 100.0


def test_duplicate_ticker_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        compute_portfolio_metrics([Position(ticker="X", shares=1, avg_cost=1, price=1), Position(ticker="x", shares=1, avg_cost=1, price=1)])


def test_empty_positions_rejected():
    with pytest.raises(ValueError, match="at least one"):
        compute_portfolio_metrics([])


def test_non_positive_values_rejected_by_schema():
    with pytest.raises(ValueError):
        Position(ticker="X", shares=0, avg_cost=1, price=1)
    with pytest.raises(ValueError):
        Position(ticker="X", shares=1, avg_cost=1, price=-5)


def test_pct_change():
    assert compute_pct_change(22387, 28236) == {"old": 22387.0, "new": 28236.0, "change": 5849.0, "pct_change": 26.13}
    assert compute_pct_change(-100, -50)["pct_change"] == 50.0


def test_pct_change_rejects_zero_base():
    with pytest.raises(ValueError, match="old"):
        compute_pct_change(0, 10)


def test_tools_accept_plain_dicts_from_the_llm():
    out = portfolio_metrics_tool.invoke({"positions": [
        {"ticker": "AAA", "shares": 10, "avg_cost": 50, "price": 60, "sector": "Tech"},
        {"ticker": "BBB", "shares": 5, "avg_cost": 100, "price": 80, "sector": "Energy"},
    ]})
    assert out["totals"]["market_value"] == 1000.0
    assert pct_change_tool.invoke({"old": 100, "new": 110})["pct_change"] == 10.0


def test_tool_names():
    assert portfolio_metrics_tool.name == "portfolio_metrics"
    assert pct_change_tool.name == "pct_change"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_finance_calc.py -q -p no:warnings`
Expected: ERROR — `ModuleNotFoundError: No module named 'app.agent.tools.finance_calc'`.

- [ ] **Step 3: Implement `app/agent/tools/finance_calc.py`**

```python
"""Deterministic portfolio math for the agent.

LLMs make arithmetic mistakes on multi-position portfolios, so every value,
P&L, weight and growth rate the agent reports must come from these pure
functions. The LLM only copies numbers it already has (shares/avg_cost from
the client DB, prices from yfinance) into the tool arguments.
"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class Position(BaseModel):
    ticker: str = Field(description="Ticker symbol, e.g. 'NVDA'.")
    shares: float = Field(gt=0, description="Number of shares held.")
    avg_cost: float = Field(gt=0, description="Average cost per share (holdings.avg_cost).")
    price: float = Field(gt=0, description="Current price per share (from yfinance).")
    sector: str | None = Field(default=None, description="companies.sector, for sector allocation.")


def _r(value: float) -> float:
    return round(value + 0.0, 2)


def compute_portfolio_metrics(positions: list[Position]) -> dict:
    if not positions:
        raise ValueError("portfolio_metrics needs at least one position")
    tickers = [p.ticker.upper() for p in positions]
    if len(set(tickers)) != len(tickers):
        raise ValueError(f"duplicate ticker in positions: {tickers}")

    total_mv = sum(p.shares * p.price for p in positions)
    total_cb = sum(p.shares * p.avg_cost for p in positions)

    rows = []
    for p in positions:
        mv = p.shares * p.price
        cb = p.shares * p.avg_cost
        rows.append({
            "ticker": p.ticker.upper(),
            "shares": p.shares,
            "avg_cost": p.avg_cost,
            "price": p.price,
            "sector": p.sector,
            "market_value": _r(mv),
            "cost_basis": _r(cb),
            "unrealized_pnl": _r(mv - cb),
            "unrealized_pnl_pct": _r((mv - cb) / cb * 100),
            "weight_pct": _r(mv / total_mv * 100),
        })

    sector_allocation = None
    if all(p.sector for p in positions):
        by_sector: dict[str, float] = {}
        for p in positions:
            by_sector[p.sector] = by_sector.get(p.sector, 0.0) + p.shares * p.price
        sector_allocation = {s: _r(v / total_mv * 100) for s, v in by_sector.items()}

    return {
        "positions": rows,
        "totals": {
            "market_value": _r(total_mv),
            "cost_basis": _r(total_cb),
            "unrealized_pnl": _r(total_mv - total_cb),
            "unrealized_pnl_pct": _r((total_mv - total_cb) / total_cb * 100),
        },
        "sector_allocation": sector_allocation,
    }


def compute_pct_change(old: float, new: float) -> dict:
    if old == 0:
        raise ValueError("pct_change is undefined when old is 0")
    return {
        "old": float(old),
        "new": float(new),
        "change": _r(new - old),
        "pct_change": _r((new - old) / abs(old) * 100),
    }


class PortfolioMetricsInput(BaseModel):
    positions: list[Position] = Field(description="Every position of the portfolio.")


@tool("portfolio_metrics", args_schema=PortfolioMetricsInput)
def portfolio_metrics_tool(positions: list) -> dict:
    """Compute per-position and total market value, cost basis, unrealized
    P&L (amount and %), portfolio weights and sector allocation. Use it for
    ANY portfolio value/performance question instead of doing math yourself."""
    parsed = [p if isinstance(p, Position) else Position.model_validate(p) for p in positions]
    return compute_portfolio_metrics(parsed)


class PctChangeInput(BaseModel):
    old: float = Field(description="Starting value.")
    new: float = Field(description="Ending value.")


@tool("pct_change", args_schema=PctChangeInput)
def pct_change_tool(old: float, new: float) -> dict:
    """Compute the change and % change from `old` to `new` (growth rates,
    quarter-over-quarter, price moves). Use it instead of doing math yourself."""
    return compute_pct_change(old, new)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_finance_calc.py -q -p no:warnings`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools/finance_calc.py tests/unit/test_finance_calc.py
git commit -m "feat(tools): deterministic portfolio_metrics and pct_change tools"
```

---

### Task 3: Register schema + calc tools (local) and document them

**Files:**
- Modify: `app/agent/tools/mcp_clients/mcp_client.py`
- Modify: `app/agent/tools/__init__.py`
- Modify: `docs/TOOLS.md`
- Modify: `CLAUDE.md`
- Test: `tests/unit/test_wealth_tools_registration.py`

**Interfaces:**
- Consumes: `portfolio_metrics_tool`, `pct_change_tool` (Task 2); `customers.db` with the wealth schema (Task 1).
- Produces: `crm_list_tables_tool`, `crm_describe_table_tool` exported from `app.agent.tools`; `TOOLS` / `READ_ONLY_TOOLS` contain `list_tables`, `describe_table`, `portfolio_metrics`, `pct_change`; `portfolio_metrics_tool`, `pct_change_tool` exported from `app.agent.tools`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_wealth_tools_registration.py`:

```python
import asyncio

from app.agent.tools import (
    READ_ONLY_TOOLS,
    TOOLS,
    crm_describe_table_tool,
    crm_list_tables_tool,
    is_read_only,
)

NEW_TOOLS = {"list_tables", "describe_table", "portfolio_metrics", "pct_change"}


def _names():
    return {t.name.rsplit("___", 1)[-1] for t in TOOLS}


def test_new_tools_are_registered():
    assert NEW_TOOLS <= _names()


def test_new_tools_are_read_only_including_gateway_prefix():
    assert NEW_TOOLS <= READ_ONLY_TOOLS
    for name in NEW_TOOLS:
        assert is_read_only(name)
        assert is_read_only(f"sqlite-crm___{name}")


def test_write_capable_sqlite_tools_are_not_exposed():
    assert not {"write_query", "create_table", "append_insight"} & _names()


def test_list_tables_reads_the_wealth_schema():
    out = str(asyncio.run(crm_list_tables_tool.ainvoke({})))
    for table in ("companies", "clients", "transactions", "holdings", "watchlists"):
        assert table in out


def test_describe_table_returns_columns():
    out = str(asyncio.run(crm_describe_table_tool.ainvoke({"table_name": "holdings"})))
    for column in ("client_id", "ticker", "shares", "avg_cost"):
        assert column in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_wealth_tools_registration.py -q -p no:warnings`
Expected: ERROR — `ImportError: cannot import name 'crm_describe_table_tool'`.

- [ ] **Step 3: Select the schema tools in `mcp_client.py`**

Replace the module body after `logger = ...` so the file ends with:

```python
CRM_TOOL_NAME = "read_query"

crm_tool: BaseTool = select_tool(CRM_TOOL_NAME, "CRM")
# Read-only schema discovery. mcp-server-sqlite also offers write_query,
# create_table and append_insight — deliberately NOT selected (read-only DB).
crm_list_tables_tool: BaseTool = select_tool("list_tables", "CRM")
crm_describe_table_tool: BaseTool = select_tool("describe_table", "CRM")
```

and update the module docstring's first paragraph to:

```python
"""CRM MCP client — selects client-database tools out of the shared registry.

Public surface: `crm_tool` (read_query), `crm_list_tables_tool` and
`crm_describe_table_tool` — all read-only SQL access to customers.db.
"""
```

- [ ] **Step 4: Register in `app/agent/tools/__init__.py`**

Change the CRM import line to:

```python
from app.agent.tools.mcp_clients.mcp_client import crm_tool, crm_list_tables_tool, crm_describe_table_tool
from app.agent.tools.finance_calc import portfolio_metrics_tool, pct_change_tool
```

In `TOOLS`, replace the single `crm_tool,` entry with:

```python
    crm_tool,
    crm_list_tables_tool,
    crm_describe_table_tool,
    portfolio_metrics_tool,
    pct_change_tool,
```

In `_BASE_READ_ONLY_TOOLS`, after `"read_query",` add:

```python
    "list_tables",
    "describe_table",
    "portfolio_metrics",
    "pct_change",
```

In `__all__`, after `"crm_tool",` add:

```python
    "crm_list_tables_tool",
    "crm_describe_table_tool",
    "portfolio_metrics_tool",
    "pct_change_tool",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_wealth_tools_registration.py -q -p no:warnings`
Expected: 5 passed.

- [ ] **Step 6: Update `docs/TOOLS.md`**

Replace summary row 2 with:

```markdown
| 2 | `read_query` | read-only | MCP stdio → `mcp-server-sqlite` (prod: Lambda `sqlite-crm`) | query (SELECT/WITH) | Runs a read-only SQL query against the wealth-management DB `customers.db` (companies, clients, transactions, holdings, watchlists). | Gives the agent the advisor's private client/portfolio data to combine with market prices and company reports. |
```

Append after the last summary row (keep numbering):

```markdown
| 17 | `list_tables` | read-only | MCP stdio → `mcp-server-sqlite` (prod: Lambda `sqlite-crm`) | — | Lists the tables of `customers.db`. | Lets the agent discover the schema instead of relying on columns hard-coded in prompts. |
| 18 | `describe_table` | read-only | MCP stdio → `mcp-server-sqlite` (prod: Lambda `sqlite-crm`) | table_name | Returns the columns and types of one table. | Same — the agent checks a column before writing SQL. |
| 19 | `portfolio_metrics` | read-only | Native (`finance_calc.py`) | positions (list of ticker, shares, avg_cost, price, sector) | Market value, cost basis, unrealized P&L (amount, %), weights, sector allocation. | Portfolio math is done by code, never by the LLM. |
| 20 | `pct_change` | read-only | Native (`finance_calc.py`) | old, new | Change and % change between two numbers. | Deterministic growth rates for comparisons. |
```

Replace the `### 2. read_query` section body with:

```markdown
### 2. `read_query`
- **File:** `app/agent/tools/mcp_clients/mcp_client.py` (selects from registry); prod: `prod/lambdas/sqlite_crm/handler.py`
- **What:** Runs the LLM-supplied SELECT/WITH query against `customers.db`, the wealth-management DB seeded by `create_db.py` (companies, clients, transactions, derived holdings, watchlists). Read-only.
- **Why:** The advisor's private data — who holds what, since when — combined by the agent with live prices (yfinance) and company reports (knowledge base) for multi-step portfolio questions.
```

Append before `## How to add a new tool`:

```markdown
### 17. `list_tables`
- **File:** `app/agent/tools/mcp_clients/mcp_client.py` (selects from registry); prod: `prod/lambdas/sqlite_crm/handler.py`
- **What:** Returns the table names of `customers.db`. Read-only; in `READ_ONLY_TOOLS`.
- **Why:** Schema discovery, so prompts don't have to hard-code every column as the DB evolves.

### 18. `describe_table`
- **File:** same as `list_tables`
- **What:** Returns `PRAGMA table_info` rows (column name, type, pk, …) for one table. The prod Lambda validates the name against `sqlite_master` and lists existing tables on an unknown name. Read-only; in `READ_ONLY_TOOLS`.
- **Why:** Lets the agent verify a column before writing SQL instead of guessing.

### 19. `portfolio_metrics`
- **File:** `app/agent/tools/finance_calc.py`
- **What:** Given every position (`ticker, shares, avg_cost, price, sector`), returns per-position market value, cost basis, unrealized P&L (amount and %), weight, the totals, and the sector allocation. Validates positive inputs and unique tickers. Read-only; in `READ_ONLY_TOOLS`.
- **Why:** LLMs make arithmetic mistakes on multi-position portfolios; all reported portfolio numbers come from this pure function.

### 20. `pct_change`
- **File:** `app/agent/tools/finance_calc.py`
- **What:** Returns `change` and `pct_change` from `old` to `new`; errors when `old` is 0. Read-only; in `READ_ONLY_TOOLS`.
- **Why:** Deterministic growth rates for comparisons (quarter-over-quarter revenue, price moves).
```

- [ ] **Step 7: Update `CLAUDE.md`**

- In `## Commands`, replace `# One-time setup: create the SQLite customer database` with `# (Re)build the wealth-management SQLite DB (customers.db) — commit the result`.
- In the tools table, replace the `read_query` row with:
  `| \`read_query\` | \`app/agent/tools/mcp_clients/mcp_client.py\` | read-only | MCP stdio client → \`mcp-server-sqlite\` → \`read_query\` against \`customers.db\` (wealth-management DB: companies, clients, transactions, holdings, watchlists; seeded by \`create_db.py\`). |`
  and add after it:
  `| \`list_tables\` / \`describe_table\` | same | read-only | Schema discovery on \`customers.db\`. |`
  `| \`portfolio_metrics\` / \`pct_change\` | \`app/agent/tools/finance_calc.py\` | read-only | Deterministic portfolio math (value, P&L, weights, sectors) and % change. |`
- In the `READ_ONLY_TOOLS = {...}` line, add `"list_tables", "describe_table", "portfolio_metrics", "pct_change"` after `"read_query"`.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest tests/ -q -p no:warnings`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add app/agent/tools/mcp_clients/mcp_client.py app/agent/tools/__init__.py docs/TOOLS.md CLAUDE.md tests/unit/test_wealth_tools_registration.py
git commit -m "feat(tools): register list_tables, describe_table, portfolio_metrics, pct_change"
```

---

### Task 4: Single-agent system prompt for the wealth DB

**Files:**
- Modify: `app/agent/prompts/system.py`
- Test: `tests/unit/test_system_prompt_wealth.py`

**Interfaces:**
- Consumes: tool names from Task 3.
- Produces: `SYSTEM_PROMPT` describing the 5 tables, the source roles, the portfolio recipe and the no-arithmetic rule.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_system_prompt_wealth.py`:

```python
from app.agent.prompts.system import SYSTEM_PROMPT


def test_legacy_customers_schema_removed():
    assert "total_spend" not in SYSTEM_PROMPT
    assert "table: `customers`" not in SYSTEM_PROMPT


def test_describes_wealth_tables_and_new_tools():
    for text in ("companies", "clients", "holdings", "transactions", "watchlists", "kb_document",
                 "list_tables", "describe_table", "portfolio_metrics", "pct_change"):
        assert text in SYSTEM_PROMPT


def test_portfolio_recipe_and_no_arithmetic_rule():
    assert "Portfolio recipe" in SYSTEM_PROMPT
    assert "Never do arithmetic" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_system_prompt_wealth.py -q -p no:warnings`
Expected: 3 failed.

- [ ] **Step 3: Edit `SYSTEM_PROMPT`**

a) First line: replace `CRM analysis` with `client portfolio analysis for a wealth-management advisor`.

b) Replace:
```
CRM (read-only):
1. `read_query` — run a SELECT query against the customer database.
```
with:
```
Client database (read-only, SQLite):
1. `read_query` — run a SELECT query against the wealth-management database (args: `query: str`).
2. `list_tables` — list the database tables.
3. `describe_table` — columns and types of one table (args: `table_name: str`). Call it whenever you are unsure about a column.

Portfolio calculations (read-only, deterministic):
4. `portfolio_metrics` — per-position and total market value, cost basis, unrealized P&L (amount and %), weights and sector allocation (args: `positions`: list of `{ticker, shares, avg_cost, price, sector}`).
5. `pct_change` — change and % change between two numbers (args: `old: float`, `new: float`).
```
then renumber every following tool entry sequentially from 6 (`yfinance_get_ticker_info`) to 20 (`send_email`) — numbers only, text unchanged.

c) Replace the whole `🗄️ CRM SCHEMA (table: \`customers\`)` block (header + 5 bullet lines) with:
```
🗄️ CLIENT DATABASE (wealth management — you assist a financial advisor)
- `companies` (ticker, name, sector, kb_document) — `kb_document` is the ingested report filename for that company, or NULL. Use it as `source_filter` for `search_knowledge_base`.
- `clients` (client_id, name, email, segment, risk_profile, advisor, city, joined_on) — segment: VIP / Premium / Standard; risk_profile: conservative / balanced / aggressive.
- `holdings` (client_id, ticker, shares, avg_cost) — current positions.
- `transactions` (txn_id, client_id, ticker, side, shares, price, trade_date) — full BUY/SELL history.
- `watchlists` (client_id, ticker, alert_price, direction) — price alerts (direction: above / below).
```

d) In `🧠 INSTRUCTIONS`, replace the three lines starting with `- You are autonomous`, `- To find a customer by name`, `- Before sending an email` with:
```
- You are autonomous: write valid `SELECT` SQL (JOINs, WHERE, GROUP BY, ORDER BY, aggregates). To find a client by name, use `LIKE '%Name%'`.
- Sources have distinct roles: the client database says WHO holds WHAT and since when; the knowledge base covers what is happening INSIDE a company (reports); Yahoo Finance gives the CURRENT price. Combine them for multi-step questions.
- Portfolio recipe: (1) read the client's `holdings` joined with `companies.sector`; (2) call `yfinance_get_ticker_info` for every ticker, in parallel; (3) pass shares, avg_cost, the current price and the sector of every position to `portfolio_metrics`.
- Never do arithmetic in your answer. Values, P&L, weights and growth rates must come from `portfolio_metrics` or `pct_change`; copy their numbers exactly.
- Before sending an email, make sure you have the recipient's address — fetch it from the client database if needed.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_system_prompt_wealth.py -q -p no:warnings`
Expected: 3 passed. Then `uv run pytest tests/ -q -p no:warnings` — all pass.

- [ ] **Step 5: Commit**

```bash
git add app/agent/prompts/system.py tests/unit/test_system_prompt_wealth.py
git commit -m "feat(prompt): single-agent prompt covers wealth DB, portfolio recipe, no mental math"
```

---

### Task 5: Multi-agent `portfolio_agent` replaces `crm_agent`

**Files:**
- Create: `app/agent/multi_agent/portfolio_agent.py`
- Delete: `app/agent/multi_agent/crm_agent.py`, `tests/unit/test_multi_agent_crm_agent.py`
- Modify: `app/agent/prompts/specialist_agent_prompts.py` (replace `CRM_SYSTEM_PROMPT` with `PORTFOLIO_SYSTEM_PROMPT`; routing prompt)
- Modify: `app/agent/multi_agent/supervisor.py`, `app/agent/multi_agent/graph.py`
- Modify: `tests/unit/test_multi_agent_graph_structure.py`, `tests/unit/test_multi_agent_supervisor_routing.py`
- Test: `tests/unit/test_multi_agent_portfolio_agent.py`

**Interfaces:**
- Consumes: `crm_tool`, `crm_list_tables_tool`, `crm_describe_table_tool`, `portfolio_metrics_tool`, `pct_change_tool`, `yf_quote_tool` from `app.agent.tools`; `with_today` from `app.agent.prompts`.
- Produces: `portfolio_agent_node(state) -> Command`, `build_portfolio_agent()`, module attr `_PORTFOLIO_TOOLS`, `_llm_with_tools`; supervisor node name `"portfolio_agent"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_multi_agent_portfolio_agent.py`:

```python
from datetime import date
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.multi_agent import portfolio_agent as portfolio_agent_mod
from app.agent.multi_agent.portfolio_agent import build_portfolio_agent, portfolio_agent_node


def _state():
    return {"question": "Which clients hold NVDA?", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0}


def test_portfolio_agent_has_every_tool_a_portfolio_computation_needs():
    names = {t.name.rsplit("___", 1)[-1] for t in portfolio_agent_mod._PORTFOLIO_TOOLS}
    assert names == {"read_query", "list_tables", "describe_table", "yfinance_get_ticker_info", "portfolio_metrics", "pct_change"}


def test_routes_to_approval_when_tool_calls_present():
    ai_msg = AIMessage(content="", tool_calls=[{"id": "1", "name": "read_query", "args": {"query": "SELECT 1"}}])
    with patch.object(portfolio_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = portfolio_agent_node(_state())
    assert result.goto == "approval"
    assert result.update["messages"] == [ai_msg]


def test_routes_to_supervisor_parent_when_no_tool_calls():
    ai_msg = AIMessage(content="Nine clients hold NVDA.")
    with patch.object(portfolio_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = ai_msg
        result = portfolio_agent_node(_state())
    assert result.goto == "supervisor"
    assert result.graph == Command.PARENT


def test_system_prompt_includes_todays_date():
    with patch.object(portfolio_agent_mod, "_llm_with_tools") as mock:
        mock.invoke.return_value = AIMessage(content="answer")
        portfolio_agent_node(_state())
    system_prompt = mock.invoke.call_args[0][0][0].content
    assert f"Today's date is {date.today().isoformat()}" in system_prompt
    assert "portfolio_metrics" in system_prompt


def test_build_portfolio_agent_compiles_with_expected_nodes():
    assert set(build_portfolio_agent().get_graph().nodes) >= {"agent", "approval", "tools"}


def test_all_portfolio_tools_bypass_interrupt():
    from app.agent.graph import approval_node

    pending = AIMessage(content="", tool_calls=[
        {"id": str(i), "name": n, "args": {}}
        for i, n in enumerate(["read_query", "list_tables", "describe_table", "yfinance_get_ticker_info", "portfolio_metrics", "pct_change"])
    ])
    with patch("app.agent.graph.interrupt") as mock_interrupt:
        result = approval_node({"messages": [pending], "question": "q", "documents": []})
    mock_interrupt.assert_not_called()
    assert result == {}
```

In `tests/unit/test_multi_agent_graph_structure.py`, replace `"crm_agent",` with `"portfolio_agent",`.

In `tests/unit/test_multi_agent_supervisor_routing.py`, replace `test_routes_to_crm_agent` with:

```python
def test_routes_to_portfolio_agent():
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="portfolio_agent", reasoning="client portfolio question")
        result = supervisor_node(_state())
    assert result.goto == "portfolio_agent"


def test_routing_prompt_describes_portfolio_agent_not_crm_agent():
    assert "portfolio_agent" in supervisor_mod.SUPERVISOR_ROUTING_PROMPT
    assert "crm_agent" not in supervisor_mod.SUPERVISOR_ROUTING_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_multi_agent_portfolio_agent.py tests/unit/test_multi_agent_graph_structure.py tests/unit/test_multi_agent_supervisor_routing.py -q -p no:warnings`
Expected: FAIL/ERROR — no module `portfolio_agent`, `portfolio_agent` not a valid `RoutingDecision` literal, node missing.

- [ ] **Step 3: Replace `CRM_SYSTEM_PROMPT` in `specialist_agent_prompts.py`**

Delete the whole `CRM_SYSTEM_PROMPT = """..."""` block and put in its place:

```python
PORTFOLIO_SYSTEM_PROMPT = """You are the Market Intelligence Agent's portfolio specialist, assisting a wealth-management advisor. Answer questions about clients, their holdings, transactions, watchlists and portfolio performance.

🛠️ YOUR TOOLS
1. `read_query` — run a SELECT query against the client database (args: `query: str`).
2. `list_tables` — list the database tables.
3. `describe_table` — columns and types of one table (args: `table_name: str`).
4. `yfinance_get_ticker_info` — current price for a ticker (args: `symbol: str`).
5. `portfolio_metrics` — market value, cost basis, unrealized P&L, weights and sector allocation (args: `positions`: list of `{ticker, shares, avg_cost, price, sector}`).
6. `pct_change` — change and % change between two numbers (args: `old: float`, `new: float`).

🗄️ DATABASE
- `companies` (ticker, name, sector, kb_document)
- `clients` (client_id, name, email, segment, risk_profile, advisor, city, joined_on)
- `holdings` (client_id, ticker, shares, avg_cost) — current positions
- `transactions` (txn_id, client_id, ticker, side, shares, price, trade_date)
- `watchlists` (client_id, ticker, alert_price, direction)
Call `describe_table` whenever you are unsure about a column.

🧠 INSTRUCTIONS
- Write valid `SELECT` SQL (JOINs, GROUP BY, aggregates). Find clients by name with `LIKE '%Name%'`.
- Portfolio recipe: read `holdings` joined with `companies.sector` → call `yfinance_get_ticker_info` for every ticker, in parallel → pass every position to `portfolio_metrics`.
- Never do arithmetic yourself. Values, P&L, weights and growth rates must come from `portfolio_metrics` or `pct_change`; copy their numbers exactly.
"""
```

In `SUPERVISOR_ROUTING_PROMPT`, replace the `- crm_agent — ...` line with:

```
- portfolio_agent — answers questions about the advisor's clients and their portfolios from the client database (clients, holdings, transactions, watchlists) and computes portfolio value, P&L and allocation with live prices. Use when the user asks about a client, who holds a stock, a client segment, or portfolio performance.
```

and in the `rag_agent` line replace `a customer record` with `a client or portfolio`.

- [ ] **Step 4: Create `app/agent/multi_agent/portfolio_agent.py`**

```python
from langgraph.types import Command
from langgraph.graph import StateGraph, START
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage

from app.core.config import settings
from app.agent.multi_agent.state import SupervisorState
from app.agent.prompts import with_today
from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT
from app.agent.tools import (
    crm_tool,
    crm_list_tables_tool,
    crm_describe_table_tool,
    yf_quote_tool,
    portfolio_metrics_tool,
    pct_change_tool,
)
from app.agent.graph import approval_node, route_after_approval
from app.agent.nodes.tool_utils import make_tool_runner

# Everything a portfolio computation needs lives in this one specialist: the
# supervisor finishes as soon as a specialist returns a plain answer, so
# chaining crm -> finance -> calc across specialists would not work.
_PORTFOLIO_TOOLS = [
    crm_tool,
    crm_list_tables_tool,
    crm_describe_table_tool,
    yf_quote_tool,
    portfolio_metrics_tool,
    pct_change_tool,
]
_llm_with_tools = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True).bind_tools(_PORTFOLIO_TOOLS)


def portfolio_agent_node(state: SupervisorState) -> Command:
    # See finance_agent.py for why this returns bare `Command` (no Literal
    # generic) instead of Command[Literal["approval", "supervisor"]].
    response = _llm_with_tools.invoke([SystemMessage(content=with_today(PORTFOLIO_SYSTEM_PROMPT)), *state["messages"]])
    if getattr(response, "tool_calls", None):
        return Command(goto="approval", update={"messages": [response]})
    return Command(goto="supervisor", graph=Command.PARENT, update={"messages": [response]})


workflow = StateGraph(SupervisorState)
workflow.add_node("agent", portfolio_agent_node)
workflow.add_node("approval", approval_node)
workflow.add_node("tools", make_tool_runner(_PORTFOLIO_TOOLS))
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("approval", route_after_approval, {"tools": "tools", "generate": "agent"})
workflow.add_edge("tools", "agent")


def build_portfolio_agent():
    return workflow.compile()
```

- [ ] **Step 5: Rewire supervisor and graph; delete crm_agent**

- `supervisor.py`: in both `Literal[...]` lists (the `RoutingDecision.next` field and the `supervisor_node` return annotation) replace `"crm_agent",` with `"portfolio_agent",`.
- `graph.py`: replace `from app.agent.multi_agent.crm_agent import build_crm_agent` with `from app.agent.multi_agent.portfolio_agent import build_portfolio_agent`; replace `workflow.add_node("crm_agent", build_crm_agent())` with `workflow.add_node("portfolio_agent", build_portfolio_agent())`; in the `record_question` comment replace `finance_agent/crm_agent` with `finance_agent/portfolio_agent`.
- Run: `git rm app/agent/multi_agent/crm_agent.py tests/unit/test_multi_agent_crm_agent.py`
- Run: `uv run python -c "import pathlib,re; hits=[str(p) for p in pathlib.Path('app').rglob('*.py') if 'crm_agent' in p.read_text(encoding='utf-8') or 'CRM_SYSTEM_PROMPT' in p.read_text(encoding='utf-8')]; print(hits)"`
  Expected: `[]`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -q -p no:warnings`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A app/agent/multi_agent app/agent/prompts/specialist_agent_prompts.py tests/unit/test_multi_agent_portfolio_agent.py tests/unit/test_multi_agent_graph_structure.py tests/unit/test_multi_agent_supervisor_routing.py
git commit -m "feat(multi-agent): portfolio_agent replaces crm_agent with SQL, prices and calc tools"
```

---

### Task 6: Prod Lambda `sqlite_crm` — `list_tables` and `describe_table`

**Files:**
- Modify: `../prod/lambdas/sqlite_crm/handler.py`
- Modify: `../prod/lambdas/sqlite_crm/tool_schema.json`
- Test: `tests/unit/test_sqlite_crm_lambda.py`

**Interfaces:**
- Consumes: `create_db.create_db(path)` (Task 1) to build a fixture DB.
- Produces: Lambda tools `list_tables` (no args → `[{"name": str}]`) and `describe_table` (`table_name` → list of `PRAGMA table_info` dicts); handler returns `{"ok": True, "result": ...}` or `{"ok": False, "error": str}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sqlite_crm_lambda.py`:

```python
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import create_db as seed

HANDLER = Path(__file__).resolve().parents[3] / "prod" / "lambdas" / "sqlite_crm" / "handler.py"


@pytest.fixture(scope="module")
def handler(tmp_path_factory):
    os.environ.setdefault("DATA_S3_BUCKET", "test-bucket")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    spec = importlib.util.spec_from_file_location("sqlite_crm_handler", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    db = tmp_path_factory.mktemp("lambda") / "customers.db"
    seed.create_db(db)
    with patch.object(mod, "_ensure_db", return_value=str(db)):
        yield mod


def _call(mod, tool, args=None):
    ctx = SimpleNamespace(client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": f"sqlite-crm___{tool}"}))
    return mod.lambda_handler(args or {}, ctx)


def test_list_tables(handler):
    out = _call(handler, "list_tables")
    assert out["ok"] is True
    assert {r["name"] for r in out["result"]} == {"companies", "clients", "transactions", "holdings", "watchlists"}


def test_describe_table(handler):
    out = _call(handler, "describe_table", {"table_name": "holdings"})
    assert out["ok"] is True
    assert [c["name"] for c in out["result"]] == ["client_id", "ticker", "shares", "avg_cost"]


def test_describe_unknown_table_lists_existing_tables(handler):
    out = _call(handler, "describe_table", {"table_name": "nope"})
    assert out["ok"] is False
    assert "unknown table" in out["error"] and "holdings" in out["error"]


def test_describe_table_rejects_injection(handler):
    out = _call(handler, "describe_table", {"table_name": 'clients"); DROP TABLE clients; --'})
    assert out["ok"] is False
    assert _call(handler, "read_query", {"query": "SELECT COUNT(*) AS n FROM clients"})["result"] == [{"n": 25}]


def test_read_query_still_works_and_stays_read_only(handler):
    assert _call(handler, "read_query", {"query": "SELECT COUNT(*) AS n FROM companies"})["result"] == [{"n": 14}]
    assert _call(handler, "read_query", {"query": "DELETE FROM clients"})["ok"] is False


def test_unknown_tool(handler):
    assert _call(handler, "write_query", {"query": "x"}) == {"ok": False, "error": "unknown tool: 'write_query'"}


def test_tool_schema_declares_the_three_tools():
    import json

    schema = json.loads((HANDLER.parent / "tool_schema.json").read_text(encoding="utf-8"))
    assert {t["name"] for t in schema} == {"read_query", "list_tables", "describe_table"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sqlite_crm_lambda.py -q -p no:warnings`
Expected: FAIL — `unknown tool: 'list_tables'` etc.

- [ ] **Step 3: Implement in `prod/lambdas/sqlite_crm/handler.py`**

Update the docstring's first line to `"""SQLite CRM MCP Lambda — read-only read_query, list_tables, describe_table over customers.db.` and replace `_read_query` + `_DISPATCH` with:

```python
def _connect() -> sqlite3.Connection:
    # Read-only mode is a second line of defense on top of IAM (GetObject only)
    # and the SELECT/WITH regex in _read_query.
    con = sqlite3.connect(f"file:{_ensure_db()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_names(con: sqlite3.Connection) -> list[str]:
    return [r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def _read_query(args: dict[str, Any]) -> list[dict[str, Any]]:
    sql = args["query"]
    if not _READ_ONLY_PATTERN.match(sql):
        raise ValueError("read_query only accepts SELECT or WITH statements")
    con = _connect()
    try:
        return [dict(r) for r in con.execute(sql).fetchall()]
    finally:
        con.close()


def _list_tables(args: dict[str, Any]) -> list[dict[str, Any]]:
    con = _connect()
    try:
        return [{"name": name} for name in _table_names(con)]
    finally:
        con.close()


def _describe_table(args: dict[str, Any]) -> list[dict[str, Any]]:
    name = args["table_name"]
    con = _connect()
    try:
        tables = _table_names(con)
        # Only names read back from sqlite_master reach the PRAGMA, so the
        # interpolation below cannot carry an injected statement.
        if name not in tables:
            raise ValueError(f"unknown table {name!r}; existing tables: {', '.join(tables)}")
        return [dict(r) for r in con.execute(f'PRAGMA table_info("{name}")').fetchall()]
    finally:
        con.close()


_DISPATCH = {
    "read_query": _read_query,
    "list_tables": _list_tables,
    "describe_table": _describe_table,
}
```

- [ ] **Step 4: Update `prod/lambdas/sqlite_crm/tool_schema.json`**

```json
[
  {
    "name": "read_query",
    "description": "Run a read-only SQL query (SELECT/WITH only) against the wealth-management database (companies, clients, transactions, holdings, watchlists).",
    "inputSchema": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "A SELECT or WITH SQL statement"}
      },
      "required": ["query"]
    }
  },
  {
    "name": "list_tables",
    "description": "List the tables of the wealth-management database.",
    "inputSchema": {"type": "object", "properties": {}}
  },
  {
    "name": "describe_table",
    "description": "Return the columns and types of one table of the wealth-management database.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "table_name": {"type": "string", "description": "Name of the table to describe"}
      },
      "required": ["table_name"]
    }
  }
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sqlite_crm_lambda.py -q -p no:warnings` → 7 passed; then `uv run pytest tests/ -q -p no:warnings` → all pass.

- [ ] **Step 6: Commit**

```bash
git add ../prod/lambdas/sqlite_crm/handler.py ../prod/lambdas/sqlite_crm/tool_schema.json tests/unit/test_sqlite_crm_lambda.py
git commit -m "feat(prod): sqlite-crm Lambda adds list_tables and describe_table"
```

---

### Task 7: CDK — sync `customers.db` to S3 on every deploy

**Files:**
- Modify: `../prod/iac/stacks/storage_stack.py`

**Interfaces:**
- Consumes: `market-intelligence-agent/customers.db` (Task 1), `self.data_bucket` in `MiaStorageStack`.
- Produces: a `BucketDeployment` construct `CrmDbDeployment` uploading `customers.db` to the data bucket root with `prune=False`.

- [ ] **Step 1: Implement**

In `prod/iac/stacks/storage_stack.py` add imports:

```python
import shutil
import tempfile
from pathlib import Path

from aws_cdk import aws_s3_deployment as s3deploy
```

Add a module constant after the imports:

```python
# market-intelligence-agent/customers.db — seeded by create_db.py and
# committed; the sqlite-crm Lambda downloads it from the data bucket.
CRM_DB_FILE = Path(__file__).resolve().parents[3] / "market-intelligence-agent" / "customers.db"
```

At the end of `__init__`, before the `CfnOutput`s, add:

```python
        # Keep S3 in sync with git: before this, customers.db was copied to
        # the bucket by hand and could silently drift from the repo.
        # Stage the single file in its own dir so the asset doesn't walk the
        # whole app folder. prune=False: the bucket also holds RAG PDFs.
        staging = Path(tempfile.mkdtemp(prefix="crm-db-"))
        shutil.copy2(CRM_DB_FILE, staging / "customers.db")
        s3deploy.BucketDeployment(
            self, "CrmDbDeployment",
            sources=[s3deploy.Source.asset(str(staging))],
            destination_bucket=self.data_bucket,
            prune=False,
        )
```

Update the module docstring's `mia-data` bullet to add: `customers.db is uploaded from the repo by a BucketDeployment on every deploy.`

- [ ] **Step 2: Verify synth locally**

Run (from repo root):
```bash
cd ../prod/iac && python -m venv .venv-synth && .venv-synth/Scripts/python -m pip install -q -r requirements.txt && CDK_DEFAULT_ACCOUNT=123456789012 CDK_DEFAULT_REGION=us-east-1 .venv-synth/Scripts/python app.py && ls cdk.out | grep -i storage
```
Expected: `app.py` exits 0 and `cdk.out` contains the storage stack template. Then check the template references the deployment:
```bash
grep -l "CrmDbDeployment" cdk.out/*.template.json
```
Expected: the storage stack template path. Remove `.venv-synth` afterwards (`rm -rf .venv-synth`); do not commit `cdk.out` changes.

If `app.py` requires other context/env to synth, read `prod/iac/app.py` and `.github/workflows/deploy.yml` for the exact variables the CI passes and reuse them; if synth still cannot run locally, stop and report instead of committing.

- [ ] **Step 3: Commit**

```bash
git add ../prod/iac/stacks/storage_stack.py
git commit -m "feat(iac): deploy customers.db to the data bucket from the repo"
```

---

### Task 8: Live grounded QA

**Files:**
- Create: `scripts/qa_wealth_db.py`

**Interfaces:**
- Consumes: everything above; real OpenAI, Pinecone, Tavily, yfinance (network), local `customers.db`.

- [ ] **Step 1: Write the QA script**

Create `scripts/qa_wealth_db.py`:

```python
"""Live grounded QA for the wealth-management DB (network + API keys).
Expected values come from customers.db and from the tool outputs of the
same run — never from the agent. Run: PYTHONPATH=. uv run python scripts/qa_wealth_db.py"""
import asyncio
import json
import re
import sqlite3
import uuid

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.agent.graph import build_agent_app
from app.agent.multi_agent import build_multi_agent_app

DB = sqlite3.connect("customers.db")
RESULTS = []


def holders(ticker):
    return {r[0] for r in DB.execute(
        "SELECT c.name FROM holdings h JOIN clients c USING (client_id) WHERE h.ticker = ?", (ticker,))}


def record(case, ok, detail):
    RESULTS.append((case, ok))
    print(f"{'PASS' if ok else 'FAIL'} | {case} | {detail}", flush=True)


def calls(msgs):
    return [tc for m in msgs if isinstance(m, AIMessage) for tc in (m.tool_calls or [])]


def answer(msgs):
    return next((m.content for m in reversed(msgs) if isinstance(m, AIMessage) and not m.tool_calls and m.content), "")


def tool_outputs(msgs, name):
    return [m.content if isinstance(m.content, str) else json.dumps(m.content)
            for m in msgs if isinstance(m, ToolMessage) and (m.name or "").endswith(name)]


def money_variants(x):
    return {f"{x:,.2f}", f"{x:.2f}", f"{x:,.0f}", f"{round(x):,}"}


async def single():
    app = build_agent_app(InMemorySaver(), InMemoryStore())

    async def ask(q):
        cfg = {"configurable": {"thread_id": str(uuid.uuid4()), "actor_id": "qa"}, "recursion_limit": 60}
        return (await app.ainvoke({"question": q}, cfg))["messages"]

    msgs = await ask("Which clients currently hold NVDA? List their full names.")
    a, expected = answer(msgs), holders("NVDA")
    missing = {n for n in expected if n not in a}
    record("W1 NVDA holders", not missing, f"expected={len(expected)} missing={missing}")

    msgs = await ask("How is Martin Levy's portfolio performing? Give the total market value and unrealized P&L.")
    a = answer(msgs)
    pm = tool_outputs(msgs, "portfolio_metrics")
    ok = bool(pm)
    if ok:
        totals = json.loads(pm[-1])["totals"] if pm[-1].startswith("{") else {}
        db_pos = {(t, s, c) for t, s, c in DB.execute(
            "SELECT h.ticker, h.shares, h.avg_cost FROM holdings h JOIN clients c USING (client_id) WHERE c.name = 'Martin Levy'")}
        sent = [tc["args"]["positions"] for tc in calls(msgs) if tc["name"].endswith("portfolio_metrics")][-1]
        sent_pos = {(p["ticker"], float(p["shares"]), float(p["avg_cost"])) for p in sent}
        ok = sent_pos == {(t, float(s), float(c)) for t, s, c in db_pos} and bool(totals) and \
            any(v in a.replace("$", "") for v in money_variants(totals["market_value"]))
    record("W2 Martin Levy portfolio grounded", ok, f"answer={a[:160]!r}")

    msgs = await ask("Which conservative clients have more than 30% of their portfolio in a single stock?")
    a = answer(msgs)
    record("W3 concentration fixture", "Margaret Collins" in a and "NVDA" in a.upper(), f"answer={a[:160]!r}")

    msgs = await ask("Tesla published its Q2 2026 update. Which of our clients hold TSLA, and how many vehicles did Tesla deliver in Q2 2026?")
    a, c = answer(msgs), {tc["name"].rsplit("___", 1)[-1] for tc in calls(msgs)}
    missing = {n for n in holders("TSLA") if n not in a}
    record("W4 RAG + SQL chain", {"search_knowledge_base", "read_query"} <= c and not missing and re.search(r"480[,.\s]?126", a) is not None,
           f"tools={sorted(c)} missing={missing}")


async def multi():
    app = build_multi_agent_app(InMemorySaver(), InMemoryStore())
    cfg = {"configurable": {"thread_id": str(uuid.uuid4()), "actor_id": "qa"}, "recursion_limit": 80}
    routed, used = [], set()
    async for ns, upd in app.astream({"question": "What is the total market value of Martin Levy's portfolio today?",
                                      "messages": [], "documents": [], "next_agent": None, "agent_hops": 0},
                                     cfg, stream_mode="updates", subgraphs=True):
        for node, val in upd.items():
            if not isinstance(val, dict):
                continue
            if node == "supervisor" and val.get("next_agent"):
                routed.append(val["next_agent"])
            used |= {tc["name"].rsplit("___", 1)[-1] for tc in calls(val.get("messages", []))}
    record("W5 multi: portfolio_agent computes value", routed[:1] == ["portfolio_agent"] and "portfolio_metrics" in used,
           f"routed={routed} tools={sorted(used)}")


async def main():
    await single()
    await multi()
    print(f"\nSUMMARY {sum(ok for _, ok in RESULTS)}/{len(RESULTS)} passed")


asyncio.run(main())
```

- [ ] **Step 2: Run it**

Run: `PYTHONPATH=. PYTHONIOENCODING=utf-8 uv run python scripts/qa_wealth_db.py`
Expected: `SUMMARY 5/5 passed`. On a FAIL, read the printed answer and tool calls, determine whether the defect is in the prompt, the tools or the check, fix the root cause with a test where it is code, and rerun. Do not loosen a check to make it pass unless the check itself is wrong (e.g. a legitimately different number format) — explain which in the commit message.

- [ ] **Step 3: Re-run the previous RAG/API QA battery** (session scratchpad `qa_battery.py`, `single multi api`) to confirm no regression. The old CRM cases (`S7`, `M5`) target the removed `customers` table and are superseded by W1–W5.

- [ ] **Step 4: Commit**

```bash
git add scripts/qa_wealth_db.py
git commit -m "test(qa): live grounded QA for wealth-management DB workflows"
```
