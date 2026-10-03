# Data Import & View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/data` section to the React console with a read-only clients/holdings/documents view, PDF→Pinecone ingestion, and Excel→validated-preview→DB import.

**Architecture:** A new, non-agentic backend router (`app/api/routers/data.py`) backed by a framework-free `app/data_import/` module (pure validation + sqlite3 writes + a refactored single-file PDF ingester). A new frontend `/data` route (`frontend/src/data/`) with a tab view; Excel is parsed client-side (new `xlsx` dependency) into raw rows and validated server-side twice (preview, then confirm). `react-router-dom` replaces the existing `mode`-toggle pattern in `App.tsx`/`Header.tsx` so this and future nav sections get real URLs.

**Tech Stack:** FastAPI, sqlite3 (stdlib), LangChain/Pinecone (existing `app/ingest.py` pipeline, reused), React, `react-router-dom` (new), `xlsx`/SheetJS (new), Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-data-import-and-view-design.md`

## Global Constraints

- No LLM, no agent graph, anywhere in this feature's backend path (spec Decision 9).
- Excel import column names, verbatim, case-insensitive on the header match: clients = `name, email, segment, risk_profile, advisor, city` (required) + `joined_on` (optional, defaults to today's ISO date); holdings = `client_email, ticker, shares, avg_cost` (all required).
- `segment` ∈ `{VIP, Premium, Standard}`, `risk_profile` ∈ `{conservative, balanced, aggressive}` — exact values, matching `create_db.py`'s `CHECK` constraints.
- Any invalid row blocks the entire file — no partial import (spec Decision 6).
- Holdings import is upsert-only on `(client_id, ticker)` — never deletes a holding absent from the file (spec Decision 7).
- `/confirm` must re-run validation from scratch before writing — never trust the `/preview` result alone (spec Decision 10).
- One global approve/reject (the `/confirm` call itself is the approval) — no per-row editing UI (spec Decision 5).
- Data view (clients/holdings/documents) is read-only — no edit/delete endpoints or UI in this plan (spec Decision 8 / Out of scope).
- `customers.db` is opened via the bare relative path `"customers.db"` — same convention as `create_db.py`'s `DB_PATH = Path(__file__).with_name("customers.db")` and the MCP sqlite server's `--db-path customers.db` (both assume cwd = `market-intelligence-agent/`, where every `uv run` command in this repo is invoked from).
- `app/ingest.py`'s existing bulk CLI behavior (scans all of `data/`, overwrites the manifest with the full filename list) must not change — only its internals are refactored to share code with the new single-file path.

## Review Focus

- **Re-uploading the same PDF twice.** Deterministic chunk IDs make this an idempotent upsert, not an error — a task's test must prove ingesting twice doesn't duplicate manifest entries or error out.
- **An Excel file with the holdings columns but a `client_email` that doesn't exist.** Must block the whole file with a clear per-row error, not a generic 500 or a silently-skipped row.
- **A `/confirm` call where the data is stale (e.g. a referenced client was removed between `/preview` and `/confirm`).** Must return 409 and write nothing — not succeed on half-valid data.
- **Switching URL from `/classic` to `/` and back** must preserve each side's own in-memory chat state only for the current session (no requirement to survive a full page reload — that's what `App.test.tsx`'s old "remembers it" test checked under localStorage; with routes, the browser's own history/back-button is the persistence, not app code) — a task's test must assert navigating between routes renders the right view, not that it survives a reload.
- **An Excel file with neither clients nor holdings columns** (e.g. a totally unrelated spreadsheet) must return a clear "unrecognized format" error from `/preview`, not a crash from code assuming one shape or the other.

---

### Task 1: Excel import validation (pure functions)

**Files:**
- Create: `app/data_import/__init__.py` (empty)
- Create: `app/data_import/validation.py`
- Test: `tests/unit/test_data_import_validation.py`

**Interfaces:**
- Consumes: nothing (pure functions, no DB, no network).
- Produces:
  - `detect_import_type(rows: list[dict]) -> Literal["clients", "holdings"] | None`
  - `ValidationError` — `TypedDict` with `row: int, field: str, message: str}`
  - `ValidationResult` — `TypedDict` with `{valid: bool, rows: list[dict], errors: list[ValidationError]}`
  - `validate_clients_rows(rows: list[dict], existing_emails: set[str]) -> ValidationResult`
  - `validate_holdings_rows(rows: list[dict], client_id_by_email: dict[str, int], known_tickers: set[str]) -> ValidationResult`

Both validate functions take the DB-dependent lookup data (`existing_emails`, `client_id_by_email`, `known_tickers`) as plain arguments instead of querying the DB themselves — keeps this module framework-free and independently testable; Task 2's router glue fetches these sets/dicts from sqlite and passes them in.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_data_import_validation.py
from app.data_import.validation import (
    detect_import_type,
    validate_clients_rows,
    validate_holdings_rows,
)


def test_detects_clients_file_by_its_columns():
    rows = [{"name": "Jane Doe", "email": "jane@x.com", "segment": "VIP",
              "risk_profile": "balanced", "advisor": "Sam", "city": "Paris"}]
    assert detect_import_type(rows) == "clients"


def test_detects_holdings_file_by_its_columns():
    rows = [{"client_email": "jane@x.com", "ticker": "AAPL", "shares": 10, "avg_cost": 150.0}]
    assert detect_import_type(rows) == "holdings"


def test_detects_neither_for_an_unrelated_file():
    rows = [{"foo": "bar"}]
    assert detect_import_type(rows) is None


def test_detects_nothing_for_an_empty_file():
    assert detect_import_type([]) is None


def _valid_client_row(**overrides):
    row = {"name": "Jane Doe", "email": "jane@x.com", "segment": "VIP",
           "risk_profile": "balanced", "advisor": "Sam", "city": "Paris"}
    row.update(overrides)
    return row


def test_valid_clients_rows_pass():
    result = validate_clients_rows([_valid_client_row()], existing_emails=set())
    assert result["valid"] is True
    assert result["errors"] == []
    assert result["rows"][0]["email"] == "jane@x.com"


def test_clients_rows_default_joined_on_to_today():
    import datetime
    result = validate_clients_rows([_valid_client_row()], existing_emails=set())
    assert result["rows"][0]["joined_on"] == datetime.date.today().isoformat()


def test_clients_row_missing_a_required_field_is_rejected():
    row = _valid_client_row()
    del row["advisor"]
    result = validate_clients_rows([row], existing_emails=set())
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "advisor"


def test_clients_row_with_a_bad_segment_is_rejected():
    result = validate_clients_rows([_valid_client_row(segment="Gold")], existing_emails=set())
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "segment"


def test_clients_row_with_a_bad_risk_profile_is_rejected():
    result = validate_clients_rows([_valid_client_row(risk_profile="risky")], existing_emails=set())
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "risk_profile"


def test_clients_row_whose_email_already_exists_is_rejected():
    result = validate_clients_rows([_valid_client_row()], existing_emails={"jane@x.com"})
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "email"


def test_clients_file_with_a_duplicate_email_in_itself_is_rejected():
    rows = [_valid_client_row(), _valid_client_row(name="Jane Two")]
    result = validate_clients_rows(rows, existing_emails=set())
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "email"


def test_one_bad_clients_row_blocks_the_whole_file():
    rows = [_valid_client_row(), _valid_client_row(email="other@x.com", segment="Gold")]
    result = validate_clients_rows(rows, existing_emails=set())
    assert result["valid"] is False
    # the good row is not silently imported
    assert len(result["errors"]) == 1


def _valid_holding_row(**overrides):
    row = {"client_email": "jane@x.com", "ticker": "AAPL", "shares": 10, "avg_cost": 150.0}
    row.update(overrides)
    return row


def test_valid_holdings_row_resolves_to_a_client_id():
    result = validate_holdings_rows(
        [_valid_holding_row()],
        client_id_by_email={"jane@x.com": 7},
        known_tickers={"AAPL"},
    )
    assert result["valid"] is True
    assert result["rows"][0]["client_id"] == 7
    assert result["rows"][0]["ticker"] == "AAPL"


def test_holdings_row_with_unknown_client_email_is_rejected():
    result = validate_holdings_rows(
        [_valid_holding_row(client_email="ghost@x.com")],
        client_id_by_email={"jane@x.com": 7},
        known_tickers={"AAPL"},
    )
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "client_email"


def test_holdings_row_with_unknown_ticker_is_rejected():
    result = validate_holdings_rows(
        [_valid_holding_row(ticker="ZZZZ")],
        client_id_by_email={"jane@x.com": 7},
        known_tickers={"AAPL"},
    )
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "ticker"


def test_holdings_row_with_non_positive_shares_is_rejected():
    result = validate_holdings_rows(
        [_valid_holding_row(shares=0)],
        client_id_by_email={"jane@x.com": 7},
        known_tickers={"AAPL"},
    )
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "shares"


def test_holdings_row_with_non_positive_avg_cost_is_rejected():
    result = validate_holdings_rows(
        [_valid_holding_row(avg_cost=-1)],
        client_id_by_email={"jane@x.com": 7},
        known_tickers={"AAPL"},
    )
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "avg_cost"


def test_holdings_file_with_a_duplicate_client_ticker_pair_is_rejected():
    rows = [_valid_holding_row(), _valid_holding_row(shares=20)]
    result = validate_holdings_rows(
        rows, client_id_by_email={"jane@x.com": 7}, known_tickers={"AAPL"}
    )
    assert result["valid"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_data_import_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.data_import'`

- [ ] **Step 3: Implement**

```python
# app/data_import/validation.py
"""Pure, framework-free validation for the Data section's two Excel import
shapes (new clients, or holdings upserts for existing clients). No DB, no
network -- the caller (app/api/routers/data.py) fetches the DB-dependent
lookup sets and passes them in, so this stays independently testable and
has nothing to mock."""

from __future__ import annotations

import datetime
from typing import Literal, TypedDict

CLIENT_COLUMNS = {"name", "email", "segment", "risk_profile", "advisor", "city"}
HOLDING_COLUMNS = {"client_email", "ticker", "shares", "avg_cost"}
SEGMENTS = {"VIP", "Premium", "Standard"}
RISK_PROFILES = {"conservative", "balanced", "aggressive"}


class ValidationError(TypedDict):
    row: int
    field: str
    message: str


class ValidationResult(TypedDict):
    valid: bool
    rows: list[dict]
    errors: list[ValidationError]


def _normalize_keys(row: dict) -> dict:
    return {str(k).strip().lower(): v for k, v in row.items()}


def detect_import_type(rows: list[dict]) -> Literal["clients", "holdings"] | None:
    if not rows:
        return None
    keys = set(_normalize_keys(rows[0]).keys())
    if keys >= CLIENT_COLUMNS:
        return "clients"
    if keys >= HOLDING_COLUMNS:
        return "holdings"
    return None


def validate_clients_rows(rows: list[dict], *, existing_emails: set[str]) -> ValidationResult:
    errors: list[ValidationError] = []
    out_rows: list[dict] = []
    seen_emails: set[str] = set()

    for i, raw in enumerate(rows):
        row = _normalize_keys(raw)
        for field in ("name", "email", "segment", "risk_profile", "advisor", "city"):
            if not row.get(field):
                errors.append({"row": i, "field": field, "message": f"{field} is required"})
        if errors and errors[-1]["row"] == i:
            continue
        if row["segment"] not in SEGMENTS:
            errors.append({"row": i, "field": "segment", "message": f"must be one of {sorted(SEGMENTS)}"})
            continue
        if row["risk_profile"] not in RISK_PROFILES:
            errors.append({"row": i, "field": "risk_profile", "message": f"must be one of {sorted(RISK_PROFILES)}"})
            continue
        email = row["email"]
        if email in existing_emails:
            errors.append({"row": i, "field": "email", "message": "a client with this email already exists"})
            continue
        if email in seen_emails:
            errors.append({"row": i, "field": "email", "message": "duplicate email in this file"})
            continue
        seen_emails.add(email)
        out_rows.append({
            "name": row["name"],
            "email": email,
            "segment": row["segment"],
            "risk_profile": row["risk_profile"],
            "advisor": row["advisor"],
            "city": row["city"],
            "joined_on": row.get("joined_on") or datetime.date.today().isoformat(),
        })

    return {"valid": not errors, "rows": out_rows if not errors else [], "errors": errors}


def validate_holdings_rows(
    rows: list[dict],
    *,
    client_id_by_email: dict[str, int],
    known_tickers: set[str],
) -> ValidationResult:
    errors: list[ValidationError] = []
    out_rows: list[dict] = []
    seen_pairs: set[tuple[int, str]] = set()

    for i, raw in enumerate(rows):
        row = _normalize_keys(raw)
        for field in ("client_email", "ticker", "shares", "avg_cost"):
            if row.get(field) in (None, ""):
                errors.append({"row": i, "field": field, "message": f"{field} is required"})
        if errors and errors[-1]["row"] == i:
            continue
        email = row["client_email"]
        if email not in client_id_by_email:
            errors.append({"row": i, "field": "client_email", "message": "no client with this email"})
            continue
        ticker = str(row["ticker"]).upper()
        if ticker not in known_tickers:
            errors.append({"row": i, "field": "ticker", "message": "unknown ticker"})
            continue
        try:
            shares = float(row["shares"])
            avg_cost = float(row["avg_cost"])
        except (TypeError, ValueError):
            errors.append({"row": i, "field": "shares", "message": "shares/avg_cost must be numeric"})
            continue
        if shares <= 0:
            errors.append({"row": i, "field": "shares", "message": "must be > 0"})
            continue
        if avg_cost <= 0:
            errors.append({"row": i, "field": "avg_cost", "message": "must be > 0"})
            continue
        client_id = client_id_by_email[email]
        pair = (client_id, ticker)
        if pair in seen_pairs:
            errors.append({"row": i, "field": "ticker", "message": "duplicate client/ticker in this file"})
            continue
        seen_pairs.add(pair)
        out_rows.append({"client_id": client_id, "ticker": ticker, "shares": shares, "avg_cost": avg_cost})

    return {"valid": not errors, "rows": out_rows if not errors else [], "errors": errors}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_data_import_validation.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app/data_import/__init__.py app/data_import/validation.py tests/unit/test_data_import_validation.py
git commit -m "feat(data-import): pure validation for clients/holdings Excel imports"
```

---

### Task 2: DB read/write module

**Files:**
- Create: `app/data_import/db.py`
- Test: `tests/unit/test_data_import_db.py`

**Interfaces:**
- Consumes: `sqlite3.Connection` (caller opens it); the validated row shapes from Task 1 (`{name, email, segment, risk_profile, advisor, city, joined_on}` for clients, `{client_id, ticker, shares, avg_cost}` for holdings).
- Produces:
  - `DB_PATH = "customers.db"` (module-level constant, the same bare relative path `create_db.py` and the MCP sqlite server use)
  - `existing_client_emails(conn) -> set[str]`
  - `client_id_by_email(conn) -> dict[str, int]`
  - `known_tickers(conn) -> set[str]`
  - `write_clients(conn, rows: list[dict]) -> None`
  - `write_holdings(conn, rows: list[dict]) -> None`
  - `list_clients_with_holdings(conn) -> list[dict]` — `[{client_id, name, email, segment, risk_profile, advisor, city, holdings: [{ticker, shares, avg_cost}]}]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_data_import_db.py
import sqlite3

import pytest

from app.data_import.db import (
    client_id_by_email,
    existing_client_emails,
    known_tickers,
    list_clients_with_holdings,
    write_clients,
    write_holdings,
)

_SCHEMA = """
CREATE TABLE companies (
    ticker TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sector TEXT NOT NULL
);
CREATE TABLE clients (
    client_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    segment TEXT NOT NULL CHECK (segment IN ('VIP','Premium','Standard')),
    risk_profile TEXT NOT NULL CHECK (risk_profile IN ('conservative','balanced','aggressive')),
    advisor TEXT NOT NULL,
    city TEXT NOT NULL,
    joined_on DATE NOT NULL
);
CREATE TABLE holdings (
    client_id INTEGER NOT NULL REFERENCES clients(client_id),
    ticker TEXT NOT NULL REFERENCES companies(ticker),
    shares REAL NOT NULL CHECK (shares > 0),
    avg_cost REAL NOT NULL CHECK (avg_cost > 0),
    PRIMARY KEY (client_id, ticker)
);
"""


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(_SCHEMA)
    c.execute("INSERT INTO companies VALUES ('AAPL', 'Apple Inc.', 'Technology')")
    c.execute(
        "INSERT INTO clients VALUES (1, 'Jane Doe', 'jane@x.com', 'VIP', 'balanced', 'Sam', 'Paris', '2024-01-01')"
    )
    c.commit()
    yield c
    c.close()


def test_existing_client_emails_reflects_the_db(conn):
    assert existing_client_emails(conn) == {"jane@x.com"}


def test_client_id_by_email_maps_correctly(conn):
    assert client_id_by_email(conn) == {"jane@x.com": 1}


def test_known_tickers_reflects_companies_table(conn):
    assert known_tickers(conn) == {"AAPL"}


def test_write_clients_inserts_a_new_row(conn):
    write_clients(conn, [{
        "name": "New Client", "email": "new@x.com", "segment": "Standard",
        "risk_profile": "conservative", "advisor": "Sam", "city": "Lyon", "joined_on": "2026-10-03",
    }])
    conn.commit()
    assert existing_client_emails(conn) == {"jane@x.com", "new@x.com"}


def test_write_holdings_inserts_a_new_position(conn):
    write_holdings(conn, [{"client_id": 1, "ticker": "AAPL", "shares": 10.0, "avg_cost": 150.0}])
    conn.commit()
    rows = conn.execute("SELECT shares, avg_cost FROM holdings WHERE client_id=1 AND ticker='AAPL'").fetchall()
    assert rows == [(10.0, 150.0)]


def test_write_holdings_upserts_an_existing_position(conn):
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 5.0, 100.0)")
    conn.commit()
    write_holdings(conn, [{"client_id": 1, "ticker": "AAPL", "shares": 10.0, "avg_cost": 150.0}])
    conn.commit()
    rows = conn.execute("SELECT shares, avg_cost FROM holdings WHERE client_id=1 AND ticker='AAPL'").fetchall()
    assert rows == [(10.0, 150.0)]


def test_write_holdings_never_touches_positions_absent_from_the_file(conn):
    conn.execute("INSERT INTO companies VALUES ('MSFT', 'Microsoft', 'Technology')")
    conn.execute("INSERT INTO holdings VALUES (1, 'MSFT', 3.0, 200.0)")
    conn.commit()
    write_holdings(conn, [{"client_id": 1, "ticker": "AAPL", "shares": 10.0, "avg_cost": 150.0}])
    conn.commit()
    msft = conn.execute("SELECT shares FROM holdings WHERE client_id=1 AND ticker='MSFT'").fetchone()
    assert msft == (3.0,)


def test_write_holdings_rolls_back_entirely_on_a_constraint_violation(conn):
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            write_holdings(conn, [
                {"client_id": 1, "ticker": "AAPL", "shares": 10.0, "avg_cost": 150.0},
                {"client_id": 1, "ticker": "AAPL", "shares": -5.0, "avg_cost": 150.0},  # violates CHECK
            ])
    rows = conn.execute("SELECT * FROM holdings").fetchall()
    assert rows == []  # the first row's insert was rolled back too


def test_list_clients_with_holdings_nests_holdings_under_each_client(conn):
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10.0, 150.0)")
    conn.commit()
    result = list_clients_with_holdings(conn)
    assert len(result) == 1
    assert result[0]["email"] == "jane@x.com"
    assert result[0]["holdings"] == [{"ticker": "AAPL", "shares": 10.0, "avg_cost": 150.0}]


def test_list_clients_with_holdings_includes_a_client_with_no_holdings(conn):
    result = list_clients_with_holdings(conn)
    assert result[0]["holdings"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_data_import_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.data_import.db'`

- [ ] **Step 3: Implement**

```python
# app/data_import/db.py
"""Direct sqlite3 access for the Data section -- deliberately NOT the MCP
sqlite-crm server the agent uses: this is plain CRUD for a UI, not an agent
tool, so it skips that indirection. Same DB file, same bare relative path
convention as create_db.py's DB_PATH and the MCP server's --db-path."""

from __future__ import annotations

import sqlite3

DB_PATH = "customers.db"


def existing_client_emails(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT email FROM clients")}


def client_id_by_email(conn: sqlite3.Connection) -> dict[str, int]:
    return {email: client_id for client_id, email in conn.execute("SELECT client_id, email FROM clients")}


def known_tickers(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT ticker FROM companies")}


def write_clients(conn: sqlite3.Connection, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO clients (name, email, segment, risk_profile, advisor, city, joined_on) "
        "VALUES (:name, :email, :segment, :risk_profile, :advisor, :city, :joined_on)",
        rows,
    )


def write_holdings(conn: sqlite3.Connection, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO holdings (client_id, ticker, shares, avg_cost) "
        "VALUES (:client_id, :ticker, :shares, :avg_cost) "
        "ON CONFLICT (client_id, ticker) DO UPDATE SET shares=excluded.shares, avg_cost=excluded.avg_cost",
        rows,
    )


def list_clients_with_holdings(conn: sqlite3.Connection) -> list[dict]:
    clients = conn.execute(
        "SELECT client_id, name, email, segment, risk_profile, advisor, city FROM clients ORDER BY name"
    ).fetchall()
    holdings_by_client: dict[int, list[dict]] = {}
    for client_id, ticker, shares, avg_cost in conn.execute(
        "SELECT client_id, ticker, shares, avg_cost FROM holdings"
    ):
        holdings_by_client.setdefault(client_id, []).append(
            {"ticker": ticker, "shares": shares, "avg_cost": avg_cost}
        )
    return [
        {
            "client_id": cid, "name": name, "email": email, "segment": segment,
            "risk_profile": risk_profile, "advisor": advisor, "city": city,
            "holdings": holdings_by_client.get(cid, []),
        }
        for cid, name, email, segment, risk_profile, advisor, city in clients
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_data_import_db.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app/data_import/db.py tests/unit/test_data_import_db.py
git commit -m "feat(data-import): sqlite3 read/write helpers for clients and holdings"
```

---

### Task 3: Single-file PDF ingestion (refactor `app/ingest.py`, add `ingest_single_pdf`)

**Files:**
- Modify: `app/ingest.py`
- Create: `app/data_import/pdf_ingest.py`
- Test: `tests/unit/test_data_import_pdf_ingest.py`

**Interfaces:**
- Consumes: `app.ingest._chunk_id`, `app.ingest._assign_chunk_ids` (existing, untouched — `tests/unit/test_ingest_chunk_ids.py` keeps passing unmodified), `app.agent.tools.knowledge_base.KB_MANIFEST_PATH` (existing).
- Produces:
  - `app.ingest.embed_and_upsert_pdf_documents(documents: list[Document], filename: str) -> list[str]` (new function in the existing file; returns the chunk ids it upserted) — `ingest_document()`'s loop body is refactored to call this per file instead of inlining the split/embed/upsert logic, with no behavior change to the bulk path (same `_write_manifest` full-overwrite call at the end, untouched).
  - `app.data_import.pdf_ingest.ingest_single_pdf(file_bytes: bytes, filename: str) -> int` — returns the number of chunks added.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_data_import_pdf_ingest.py
import json

from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.data_import.pdf_ingest import ingest_single_pdf

_FAKE_PAGES = [{"page_content": "Some extracted text about Acme Corp.", "metadata": {"page": 0}}]


class _FakeDoc:
    def __init__(self, page_content, metadata):
        self.page_content = page_content
        self.metadata = metadata


def _fake_loader(_path):
    class _Loader:
        def load(self):
            return [_FakeDoc(p["page_content"], dict(p["metadata"])) for p in _FAKE_PAGES]
    return _Loader()


def _fake_vectorstore_from_documents(**kwargs):
    _fake_vectorstore_from_documents.calls.append(kwargs)


_fake_vectorstore_from_documents.calls = []


def test_ingest_single_pdf_upserts_chunks_and_returns_their_count(tmp_path, monkeypatch):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text(json.dumps(["existing-report.pdf"]))
    monkeypatch.setattr("app.data_import.pdf_ingest.KB_MANIFEST_PATH", manifest)
    monkeypatch.setattr("app.ingest.PyPDFLoader", _fake_loader)
    monkeypatch.setattr("app.ingest.OpenAIEmbeddings", lambda **kw: object())
    monkeypatch.setattr(
        "app.ingest.PineconeVectorStore.from_documents",
        staticmethod(lambda **kw: _fake_vectorstore_from_documents(**kw)),
    )

    chunk_count = ingest_single_pdf(b"%PDF-1.4 fake bytes", "new-report.pdf")

    assert chunk_count >= 1
    assert _fake_vectorstore_from_documents.calls, "Pinecone upsert was not called"


def test_ingest_single_pdf_adds_to_the_manifest_without_removing_existing_entries(tmp_path, monkeypatch):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text(json.dumps(["existing-report.pdf"]))
    monkeypatch.setattr("app.data_import.pdf_ingest.KB_MANIFEST_PATH", manifest)
    monkeypatch.setattr("app.ingest.PyPDFLoader", _fake_loader)
    monkeypatch.setattr("app.ingest.OpenAIEmbeddings", lambda **kw: object())
    monkeypatch.setattr(
        "app.ingest.PineconeVectorStore.from_documents",
        staticmethod(lambda **kw: None),
    )

    ingest_single_pdf(b"%PDF-1.4 fake bytes", "new-report.pdf")

    assert set(json.loads(manifest.read_text())) == {"existing-report.pdf", "new-report.pdf"}


def test_ingesting_the_same_pdf_twice_does_not_duplicate_the_manifest_entry(tmp_path, monkeypatch):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text(json.dumps([]))
    monkeypatch.setattr("app.data_import.pdf_ingest.KB_MANIFEST_PATH", manifest)
    monkeypatch.setattr("app.ingest.PyPDFLoader", _fake_loader)
    monkeypatch.setattr("app.ingest.OpenAIEmbeddings", lambda **kw: object())
    monkeypatch.setattr(
        "app.ingest.PineconeVectorStore.from_documents",
        staticmethod(lambda **kw: None),
    )

    ingest_single_pdf(b"%PDF-1.4 fake bytes", "same-report.pdf")
    ingest_single_pdf(b"%PDF-1.4 fake bytes", "same-report.pdf")

    assert json.loads(manifest.read_text()) == ["same-report.pdf"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_data_import_pdf_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.data_import.pdf_ingest'`

- [ ] **Step 3: Refactor `app/ingest.py`**

Add this function (after `_assign_chunk_ids`, before `_write_manifest`), and change `ingest_document()`'s body to call it:

```python
def embed_and_upsert_pdf_documents(documents, filename: str) -> list[str]:
    """Split, embed, and upsert one PDF's already-loaded pages into
    Pinecone. Shared by the bulk CLI ingest below and
    app/data_import/pdf_ingest.py's single-file path, so both go through
    the exact same chunking/ID/embedding logic."""
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents(documents)
    for doc in splits:
        doc.metadata["filename"] = filename
    ids = _assign_chunk_ids(splits)
    embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
    PineconeVectorStore.from_documents(
        documents=splits, embedding=embeddings, index_name=settings.PINECONE_INDEX_NAME, ids=ids
    )
    return ids
```

`ingest_document()` currently loads ALL pdfs into one `documents` list before splitting (it doesn't track per-file boundaries). Restructure it to call `PyPDFLoader(pdf_path).load()` and `embed_and_upsert_pdf_documents(file_documents, file)` once per file instead, so each file goes through the exact same per-file path the new single-upload function uses. Replace the whole function body with:

```python
def ingest_document():
    """Read PDF from data folder et index in pinecone"""
    print(" Starting to ingest to pinecone....")

    data_folder = "data"
    if not os.path.exists(data_folder):
        os.makedirs(data_folder)
        print(f"⚠️ Folder '{data_folder}' created. Put some PDFs and restar.")
        return

    pdf_files = [f for f in os.listdir(data_folder) if f.endswith(".pdf")]
    if not pdf_files:
        print("❌ No document PDF found.")
        return

    print("cw Stockage dans Pinecone (cela peut prendre quelques secondes)...")
    for file in pdf_files:
        pdf_path = os.path.join(data_folder, file)
        print(f" Charging the {file}..")
        documents = PyPDFLoader(pdf_path).load()
        embed_and_upsert_pdf_documents(documents, file)

    _write_manifest(pdf_files)
    print("✅ Ingestion  finish ! Base Knowledge ready .")
```

- [ ] **Step 4: Run the existing ingest test to confirm no regression**

Run: `uv run pytest tests/unit/test_ingest_chunk_ids.py -v`
Expected: all PASS (untouched functions)

- [ ] **Step 5: Implement `app/data_import/pdf_ingest.py`**

```python
# app/data_import/pdf_ingest.py
"""Single-file PDF -> Pinecone ingestion for the Data section's upload
flow. Shares its chunk/embed/upsert mechanics with app/ingest.py's bulk CLI
path via embed_and_upsert_pdf_documents(); unlike the bulk path, this
function ADDS to the existing manifest instead of overwriting it, since one
upload is never "the whole corpus"."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader

from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.ingest import embed_and_upsert_pdf_documents


def ingest_single_pdf(file_bytes: bytes, filename: str) -> int:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(file_bytes)
        tmp.flush()
        documents = PyPDFLoader(tmp.name).load()

    chunk_ids = embed_and_upsert_pdf_documents(documents, filename)

    existing = json.loads(KB_MANIFEST_PATH.read_text()) if KB_MANIFEST_PATH.exists() else []
    KB_MANIFEST_PATH.write_text(json.dumps(sorted(set(existing) | {filename}), indent=2) + "\n")

    return len(chunk_ids)
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `uv run pytest tests/unit/test_data_import_pdf_ingest.py tests/unit/test_ingest_chunk_ids.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add app/ingest.py app/data_import/pdf_ingest.py tests/unit/test_data_import_pdf_ingest.py
git commit -m "feat(data-import): single-file PDF ingestion, sharing app/ingest.py's pipeline"
```

---

### Task 4: Backend router (`app/api/routers/data.py`) + wiring

**Files:**
- Create: `app/api/routers/data.py`
- Modify: `app/api/server.py:1-14,66` (import + `app.include_router`)
- Test: `tests/unit/test_data_endpoints.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3 (`app.data_import.validation`, `app.data_import.db`, `app.data_import.pdf_ingest.ingest_single_pdf`).
- Produces: the 5 HTTP endpoints from the spec, mounted with no prefix conflict alongside the existing routers in `server.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_data_endpoints.py
import io
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import data as data_router_module
from app.api.routers.data import router

_SCHEMA = """
CREATE TABLE companies (ticker TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL);
CREATE TABLE clients (
    client_id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
    segment TEXT NOT NULL CHECK (segment IN ('VIP','Premium','Standard')),
    risk_profile TEXT NOT NULL CHECK (risk_profile IN ('conservative','balanced','aggressive')),
    advisor TEXT NOT NULL, city TEXT NOT NULL, joined_on DATE NOT NULL
);
CREATE TABLE holdings (
    client_id INTEGER NOT NULL REFERENCES clients(client_id), ticker TEXT NOT NULL REFERENCES companies(ticker),
    shares REAL NOT NULL CHECK (shares > 0), avg_cost REAL NOT NULL CHECK (avg_cost > 0),
    PRIMARY KEY (client_id, ticker)
);
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "customers.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO companies VALUES ('AAPL', 'Apple Inc.', 'Technology')")
    conn.execute(
        "INSERT INTO clients VALUES (1, 'Jane Doe', 'jane@x.com', 'VIP', 'balanced', 'Sam', 'Paris', '2024-01-01')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(data_router_module, "DB_PATH", str(db_path))

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_get_clients_lists_the_seeded_client(client):
    resp = client.get("/data/clients")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["email"] == "jane@x.com"
    assert body[0]["holdings"] == []


def test_get_documents_reads_the_manifest(tmp_path, monkeypatch, client):
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text('["report-a.pdf", "report-b.pdf"]')
    monkeypatch.setattr("app.api.routers.data.KB_MANIFEST_PATH", manifest)
    resp = client.get("/data/documents")
    assert resp.status_code == 200
    assert set(resp.json()) == {"report-a.pdf", "report-b.pdf"}


def test_import_preview_accepts_a_valid_holdings_file(client):
    resp = client.post("/data/import/preview", json={
        "rows": [{"client_email": "jane@x.com", "ticker": "AAPL", "shares": 10, "avg_cost": 150.0}]
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "holdings"
    assert body["valid"] is True


def test_import_preview_rejects_an_unrecognized_file(client):
    resp = client.post("/data/import/preview", json={"rows": [{"foo": "bar"}]})
    assert resp.status_code == 400


def test_import_preview_returns_row_errors_for_an_invalid_file(client):
    resp = client.post("/data/import/preview", json={
        "rows": [{"client_email": "ghost@x.com", "ticker": "AAPL", "shares": 10, "avg_cost": 150.0}]
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["errors"][0]["field"] == "client_email"


def test_import_confirm_writes_a_valid_holdings_file(client):
    resp = client.post("/data/import/confirm", json={
        "type": "holdings",
        "rows": [{"client_email": "jane@x.com", "ticker": "AAPL", "shares": 10, "avg_cost": 150.0}],
    })
    assert resp.status_code == 200
    assert resp.json() == {"written": 1}

    listed = client.get("/data/clients").json()
    assert listed[0]["holdings"] == [{"ticker": "AAPL", "shares": 10.0, "avg_cost": 150.0}]


def test_import_confirm_returns_409_if_revalidation_fails(client):
    resp = client.post("/data/import/confirm", json={
        "type": "holdings",
        "rows": [{"client_email": "ghost@x.com", "ticker": "AAPL", "shares": 10, "avg_cost": 150.0}],
    })
    assert resp.status_code == 409


def test_import_pdf_calls_ingest_single_pdf(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.api.routers.data.ingest_single_pdf",
        lambda file_bytes, filename: calls.append((filename, len(file_bytes))) or 3,
    )
    resp = client.post(
        "/data/import/pdf",
        files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json() == {"filename": "report.pdf", "chunks_added": 3}
    assert calls == [("report.pdf", len(b"%PDF-1.4 fake"))]


def test_import_pdf_rejects_bytes_without_a_pdf_magic_number(client):
    resp = client.post(
        "/data/import/pdf",
        files={"file": ("not-a-pdf.pdf", io.BytesIO(b"hello world"), "application/pdf")},
    )
    assert resp.status_code == 400


def test_import_pdf_returns_500_when_ingestion_itself_fails(client, monkeypatch):
    def _boom(file_bytes, filename):
        raise RuntimeError("Pinecone is down")

    monkeypatch.setattr("app.api.routers.data.ingest_single_pdf", _boom)
    resp = client.post(
        "/data/import/pdf",
        files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert resp.status_code == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_data_endpoints.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.routers.data'`

- [ ] **Step 3: Implement**

```python
# app/api/routers/data.py
"""Read-only clients/holdings/documents view, plus PDF->RAG and
Excel->DB imports, for the React console's /data section. Deliberately
NOT wired into the agent graph: this is deterministic CRUD and ingestion,
not an agent capability -- see docs/superpowers/specs/
2026-10-03-data-import-and-view-design.md Decision 9."""

import json
import sqlite3

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.data_import.db import (
    DB_PATH,
    client_id_by_email,
    existing_client_emails,
    known_tickers,
    list_clients_with_holdings,
    write_clients,
    write_holdings,
)
from app.data_import.pdf_ingest import ingest_single_pdf
from app.data_import.validation import (
    detect_import_type,
    validate_clients_rows,
    validate_holdings_rows,
)

router = APIRouter(prefix="/data")


class ImportRowsRequest(BaseModel):
    rows: list[dict]


class ImportConfirmRequest(BaseModel):
    type: str
    rows: list[dict]


def _validate(conn: sqlite3.Connection, rows: list[dict]):
    kind = detect_import_type(rows)
    if kind is None:
        return None, None
    if kind == "clients":
        return kind, validate_clients_rows(rows, existing_emails=existing_client_emails(conn))
    return kind, validate_holdings_rows(
        rows, client_id_by_email=client_id_by_email(conn), known_tickers=known_tickers(conn)
    )


@router.get("/clients")
async def get_clients() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        return list_clients_with_holdings(conn)
    finally:
        conn.close()


@router.get("/documents")
async def get_documents() -> list[str]:
    if not KB_MANIFEST_PATH.exists():
        return []
    return json.loads(KB_MANIFEST_PATH.read_text())


@router.post("/import/preview")
async def import_preview(payload: ImportRowsRequest) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        kind, result = _validate(conn, payload.rows)
    finally:
        conn.close()
    if kind is None:
        raise HTTPException(status_code=400, detail="unrecognized file format")
    return {"type": kind, **result}


@router.post("/import/confirm")
async def import_confirm(payload: ImportConfirmRequest) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        kind, result = _validate(conn, payload.rows)
        if kind != payload.type or not result["valid"]:
            raise HTTPException(status_code=409, detail="validation changed since preview, please re-upload")
        try:
            with conn:
                if kind == "clients":
                    write_clients(conn, result["rows"])
                else:
                    write_holdings(conn, result["rows"])
        except sqlite3.DatabaseError as exc:
            raise HTTPException(status_code=500, detail=f"write failed: {exc}") from exc
        return {"written": len(result["rows"])}
    finally:
        conn.close()


@router.post("/import/pdf")
async def import_pdf(file: UploadFile = File(...)) -> dict:
    body = await file.read()
    filename = file.filename or "upload.pdf"
    if not body.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="invalid PDF")
    # Any failure past this point (a real PDF that OpenAI/Pinecone fails to
    # embed/upsert) is a 500, not a 400 -- it's not the user's input that's
    # wrong. No try/except: FastAPI's default handler returns 500.
    chunk_count = ingest_single_pdf(body, filename)
    return {"filename": filename, "chunks_added": chunk_count}
```

Wire it into `app/api/server.py`:

```python
# add to the import block (after workspace_router)
from app.api.routers.data import router as data_router
...
# add after app.include_router(workspace_router)
app.include_router(data_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_data_endpoints.py -v`
Expected: all PASS

- [ ] **Step 5: Run the full backend regression**

Run: `uv run pytest tests/ -q`
Expected: all PASS (no regressions in existing routers/tests)

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/data.py app/api/server.py tests/unit/test_data_endpoints.py
git commit -m "feat(data-import): wire the /data router (clients, documents, import endpoints)"
```

---

### Task 5: Frontend routing migration (`react-router-dom` replaces the mode toggle)

**Files:**
- Modify: `frontend/package.json` (add `react-router-dom`)
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Header.tsx`
- Delete: `frontend/src/desk/mode.ts`
- Delete: `frontend/src/desk/mode.test.ts`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: nothing new from this plan yet (Task 6 adds the `/data` page content; this task only adds the route and a placeholder).
- Produces: routes `/` (Desk), `/classic` (Classic chat), `/data` (placeholder `<div>Data</div>` until Task 7 fills it in) — `<Link>`s in `Header.tsx` instead of the old toggle buttons.

- [ ] **Step 1: Add the dependency**

Run (from `frontend/`): `npm install react-router-dom@^7.18.4`

- [ ] **Step 2: Rewrite the failing tests first**

```tsx
// frontend/src/App.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("./desk/DeskView", () => ({
  DeskView: ({ threadId }: { threadId: string }) => <div data-testid="desk-view">{threadId}</div>,
}));

import App from "./App";

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}>{<App />}</MemoryRouter>);
}

describe("App routing", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "ok", version: "1.2.3" }),
    }));
  });

  it("/ renders Market Desk", () => {
    renderAt("/");
    expect(screen.getByTestId("desk-view")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/ask the agent/i)).not.toBeInTheDocument();
  });

  it("/classic renders the classic chat", () => {
    renderAt("/classic");
    expect(screen.getByPlaceholderText(/ask the agent/i)).toBeInTheDocument();
    expect(screen.queryByTestId("desk-view")).not.toBeInTheDocument();
  });

  it("the nav link to Classic has the right href", () => {
    renderAt("/");
    expect(screen.getByRole("link", { name: "Classic" })).toHaveAttribute("href", "/classic");
  });

  it("New session gives the desk a new thread id", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderAt("/");
    const before = screen.getByTestId("desk-view").textContent;
    await user.click(screen.getByRole("button", { name: /new session/i }));
    expect(screen.getByTestId("desk-view").textContent).not.toBe(before);
  });

  it("Market Desk runs on its own thread, never Classic's", () => {
    renderAt("/classic");
    const classicThread = screen.getByText(/^web_session_/).textContent;
    renderAt("/");
    expect(screen.getByTestId("desk-view").textContent).not.toBe(classicThread);
  });
});
```

Delete `frontend/src/desk/mode.ts` and `frontend/src/desk/mode.test.ts` entirely — their behavior (localStorage-persisted mode) no longer exists; the URL is the persisted state now.

- [ ] **Step 3: Run tests to verify they fail**

Run (from `frontend/`): `npm test -- App.test.tsx`
Expected: FAIL — `App.tsx` doesn't use routing yet, `mode.ts` import still present.

- [ ] **Step 4: Implement `App.tsx`**

Replace the `mode` state and the `mode === "desk" ? ... : ...` branch with `react-router-dom`'s `Routes`/`Route`/`useParams`-free split (each route renders its own layout; the shared `Header` and shell stay outside `<Routes>`):

```tsx
import { useState, useRef, type FormEvent, type KeyboardEvent } from "react";
import { Routes, Route } from "react-router-dom";
import { Header } from "./components/Header";
import { ChatPane } from "./components/ChatPane";
import { ActivityRail } from "./components/ActivityRail";
import { ApprovalCard } from "./components/ApprovalCard";
import { VoicePanel } from "./components/VoicePanel";
import { useChatStream } from "./hooks/useChatStream";
import { newThreadId } from "./lib/api";
import { DeskView } from "./desk/DeskView";

function ClassicChat({ threadId }: { threadId: string }) {
  const [input, setInput] = useState("");
  const [voiceOpen, setVoiceOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { messages, activity, streaming, pending, send, resolvePending } = useChatStream(threadId);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    submitQuery();
  }
  function submitQuery() {
    const q = input.trim();
    if (!q || streaming || pending) return;
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    void send(q);
  }
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitQuery();
    }
  }
  function onTextareaChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }
  const inputDisabled = streaming || !!pending;

  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-hidden">
          <ChatPane messages={messages} streaming={streaming} />
        </div>
        {pending && (
          <div className="border-t border-terminal-border px-4 py-3">
            <ApprovalCard threadId={threadId} pending={pending} onResolved={(text, still) => resolvePending(text, still)} />
          </div>
        )}
        <div className="border-t border-terminal-border bg-terminal-panel">
          <form onSubmit={onSubmit} className="flex items-end gap-2 px-3 py-3">
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={onTextareaChange}
              onKeyDown={onKeyDown}
              disabled={inputDisabled}
              placeholder="Ask the agent…"
              className="flex-1 resize-none overflow-hidden rounded-xl border border-terminal-border bg-terminal-bg px-3.5 py-2.5 font-mono text-sm text-terminal-text placeholder-terminal-muted outline-none transition-colors focus:border-terminal-accent/60 disabled:cursor-not-allowed disabled:opacity-50"
            />
            <div className="flex flex-none items-center gap-1.5 pb-0.5">
              <button type="submit" disabled={inputDisabled || !input.trim()} className="rounded-xl bg-terminal-accent px-4 py-2.5 font-mono text-sm font-semibold text-terminal-bg shadow-glow-green transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none">
                {streaming ? <span className="animate-pulse">…</span> : "Send"}
              </button>
              <button type="button" onClick={() => setVoiceOpen((v) => !v)} className={`rounded-xl border px-3 py-2.5 font-mono text-sm transition-all ${voiceOpen ? "border-terminal-accent/50 bg-terminal-accent/10 text-terminal-accent" : "border-terminal-border text-terminal-muted hover:border-terminal-accent/40 hover:text-terminal-text"}`} title="Toggle voice">
                🎤
              </button>
            </div>
          </form>
          <div className="px-4 pb-2">
            <span className="font-mono text-[10px] text-terminal-muted">Enter to send · Shift+Enter for newline</span>
          </div>
        </div>
        {voiceOpen && <VoicePanel threadId={threadId} />}
      </main>
      <ActivityRail activity={activity} />
    </div>
  );
}

export default function App() {
  const [threadId, setThreadId] = useState(newThreadId);

  function onNewSession() {
    setThreadId(newThreadId());
  }

  return (
    <div className="flex h-full flex-col bg-terminal-bg">
      <Header threadId={threadId} onNewSession={onNewSession} />
      <Routes>
        <Route path="/" element={<DeskView key={threadId} threadId={`desk_${threadId}`} />} />
        <Route path="/classic" element={<ClassicChat threadId={threadId} />} />
        <Route path="/data" element={<div>Data</div>} />
      </Routes>
    </div>
  );
}
```

`main.tsx` (or wherever `<App />` is rendered at the top level — check this file before editing) must wrap it in `<BrowserRouter>`:

```tsx
import { BrowserRouter } from "react-router-dom";
// ...
<BrowserRouter>
  <App />
</BrowserRouter>
```

- [ ] **Step 5: Implement `Header.tsx`**

Replace the `mode`/`onModeChange` props and the toggle buttons with `<Link>`s:

```tsx
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { getHealth } from "../lib/api";

interface HeaderProps {
  threadId: string;
  onNewSession: () => void;
}

export function Header({ threadId, onNewSession }: HeaderProps) {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [version, setVersion] = useState<string>("");
  const location = useLocation();

  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const h = await getHealth();
        if (active) {
          setHealthy(h.status === "ok" || h.status === "healthy");
          setVersion(h.version);
        }
      } catch {
        if (active) setHealthy(false);
      }
    };
    check();
    const id = setInterval(check, 10000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const dotClass =
    healthy === null ? "bg-terminal-muted" : healthy ? "bg-terminal-accent animate-pulse-dot shadow-glow-green" : "bg-terminal-danger shadow-glow-red";

  const navLink = (to: string, label: string) => (
    <Link
      to={to}
      className={`px-2.5 py-1 font-mono text-xs transition-colors ${
        location.pathname === to ? "bg-terminal-accent/15 text-terminal-accent" : "bg-terminal-bg text-terminal-muted hover:text-terminal-text"
      }`}
    >
      {label}
    </Link>
  );

  return (
    <header className="scan-lines flex items-center justify-between border-b border-terminal-border bg-terminal-panel px-4 py-2.5 shadow-inner-glow">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${dotClass}`} />
          <span className="font-mono text-sm font-semibold text-terminal-muted">MIA · Dev Console</span>
        </div>
        {version && <span className="rounded border border-terminal-border px-1.5 py-0.5 font-mono text-[10px] text-terminal-muted">v{version}</span>}
        {healthy === false && <span className="rounded bg-terminal-danger/10 px-2 py-0.5 font-mono text-[10px] text-terminal-danger">backend offline</span>}
      </div>
      <div className="flex items-center gap-3">
        <div className="flex overflow-hidden rounded border border-terminal-border">
          {navLink("/", "Market Desk")}
          {navLink("/classic", "Classic")}
          {navLink("/data", "Data")}
        </div>
        <div className="flex items-center gap-1.5 rounded border border-terminal-border bg-terminal-bg px-2.5 py-1">
          <span className="font-mono text-[10px] text-terminal-muted">session</span>
          <span className="font-mono text-[10px] text-terminal-accent">{threadId}</span>
        </div>
        <button onClick={onNewSession} className="rounded border border-terminal-border bg-terminal-bg px-3 py-1 font-mono text-xs text-terminal-muted transition-all hover:border-terminal-accent hover:text-terminal-accent">
          + New session
        </button>
      </div>
    </header>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run (from `frontend/`): `npm test`
Expected: all PASS (no remaining references to `desk/mode`)

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/components/Header.tsx frontend/src/main.tsx
git rm frontend/src/desk/mode.ts frontend/src/desk/mode.test.ts
git commit -m "feat(data-import): react-router-dom replaces the mode-toggle pattern"
```

---

### Task 6: Frontend API client additions + Vite proxy

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/api.test.ts`
- Modify: `frontend/vite.config.ts`

**Interfaces:**
- Consumes: the 5 backend endpoints from Task 4.
- Produces: `getClients()`, `getDocuments()`, `importPdf(file)`, `previewImport(rows)`, `confirmImport(type, rows)` — used by Task 7/8's components.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/api.test.ts` (read the existing file first to match its exact mocking style before adding):

```ts
import { getClients, getDocuments, importPdf, previewImport, confirmImport } from "./api";

describe("data section API", () => {
  it("getClients fetches /data/clients", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [{ email: "jane@x.com" }] });
    vi.stubGlobal("fetch", fetchMock);
    const result = await getClients();
    expect(fetchMock).toHaveBeenCalledWith("/data/clients");
    expect(result).toEqual([{ email: "jane@x.com" }]);
  });

  it("getDocuments fetches /data/documents", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ["a.pdf"] }));
    expect(await getDocuments()).toEqual(["a.pdf"]);
  });

  it("importPdf posts multipart to /data/import/pdf", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ filename: "a.pdf", chunks_added: 2 }) });
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
    const result = await importPdf(file);
    expect(fetchMock.mock.calls[0][0]).toBe("/data/import/pdf");
    expect(result).toEqual({ filename: "a.pdf", chunks_added: 2 });
  });

  it("previewImport posts rows to /data/import/preview", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ type: "holdings", valid: true, rows: [], errors: [] }) });
    vi.stubGlobal("fetch", fetchMock);
    const rows = [{ ticker: "AAPL" }];
    const result = await previewImport(rows);
    expect(fetchMock).toHaveBeenCalledWith("/data/import/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows }),
    });
    expect(result.valid).toBe(true);
  });

  it("confirmImport posts type and rows to /data/import/confirm", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ written: 1 }) });
    vi.stubGlobal("fetch", fetchMock);
    const rows = [{ ticker: "AAPL" }];
    const result = await confirmImport("holdings", rows);
    expect(fetchMock).toHaveBeenCalledWith("/data/import/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "holdings", rows }),
    });
    expect(result).toEqual({ written: 1 });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm test -- api.test.ts`
Expected: FAIL — the new functions don't exist yet.

- [ ] **Step 3: Implement**

Append to `frontend/src/lib/api.ts`:

```ts
export interface ClientWithHoldings {
  client_id: number;
  name: string;
  email: string;
  segment: string;
  risk_profile: string;
  advisor: string;
  city: string;
  holdings: { ticker: string; shares: number; avg_cost: number }[];
}

export interface ImportPreviewResult {
  type: "clients" | "holdings";
  valid: boolean;
  rows: Record<string, unknown>[];
  errors: { row: number; field: string; message: string }[];
}

export async function getClients(base = API_BASE): Promise<ClientWithHoldings[]> {
  const res = await fetch(`${base}/data/clients`);
  if (!res.ok) throw new Error(`clients ${res.status}`);
  return res.json();
}

export async function getDocuments(base = API_BASE): Promise<string[]> {
  const res = await fetch(`${base}/data/documents`);
  if (!res.ok) throw new Error(`documents ${res.status}`);
  return res.json();
}

export async function importPdf(file: File, base = API_BASE): Promise<{ filename: string; chunks_added: number }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${base}/data/import/pdf`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`import pdf ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function previewImport(rows: Record<string, unknown>[], base = API_BASE): Promise<ImportPreviewResult> {
  const res = await fetch(`${base}/data/import/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows }),
  });
  if (res.status === 400) throw new Error("unrecognized file format");
  if (!res.ok) throw new Error(`preview ${res.status}`);
  return res.json();
}

export async function confirmImport(
  type: "clients" | "holdings",
  rows: Record<string, unknown>[],
  base = API_BASE,
): Promise<{ written: number }> {
  const res = await fetch(`${base}/data/import/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, rows }),
  });
  if (!res.ok) throw new Error(`confirm ${res.status}: ${await res.text()}`);
  return res.json();
}
```

Add `/data` to `frontend/vite.config.ts`'s proxy map (alongside the existing entries):

```ts
      "/data": { target: API_TARGET, changeOrigin: true },
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npm test -- api.test.ts`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts frontend/vite.config.ts
git commit -m "feat(data-import): frontend API client for the /data endpoints"
```

---

### Task 7: Read-only views — `ClientsList`, `DocumentsList`, `DataPage`

**Files:**
- Create: `frontend/src/data/ClientsList.tsx`
- Create: `frontend/src/data/ClientsList.test.tsx`
- Create: `frontend/src/data/DocumentsList.tsx`
- Create: `frontend/src/data/DocumentsList.test.tsx`
- Create: `frontend/src/data/DataPage.tsx`
- Modify: `frontend/src/App.tsx:` the `/data` route (`<Route path="/data" element={<div>Data</div>} />` → `<DataPage />`)

**Interfaces:**
- Consumes: `getClients`, `getDocuments` from Task 6.
- Produces: `<ClientsList />`, `<DocumentsList />`, `<DataPage />` (tab switch between Clients / Documents / Import — the Import tab is wired up in Task 8).

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/data/ClientsList.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ClientsList } from "./ClientsList";

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
    render(<ClientsList />);
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
    render(<ClientsList />);
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
  });
});
```

```tsx
// frontend/src/data/DocumentsList.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DocumentsList } from "./DocumentsList";

describe("DocumentsList", () => {
  it("renders each ingested filename", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ["report-a.pdf", "report-b.pdf"] }));
    render(<DocumentsList />);
    expect(await screen.findByText("report-a.pdf")).toBeInTheDocument();
    expect(screen.getByText("report-b.pdf")).toBeInTheDocument();
  });

  it("renders a message when no documents are ingested yet", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    render(<DocumentsList />);
    expect(await screen.findByText(/no documents/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm test -- ClientsList DocumentsList`
Expected: FAIL — components don't exist yet.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/data/ClientsList.tsx
import { useEffect, useState } from "react";
import { getClients, type ClientWithHoldings } from "../lib/api";

export function ClientsList() {
  const [clients, setClients] = useState<ClientWithHoldings[]>([]);

  useEffect(() => {
    void getClients().then(setClients);
  }, []);

  return (
    <div className="space-y-3 font-mono text-sm text-terminal-text">
      {clients.map((c) => (
        <div key={c.client_id} className="rounded-xl border border-terminal-border bg-terminal-panel p-3">
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
        </div>
      ))}
    </div>
  );
}
```

```tsx
// frontend/src/data/DocumentsList.tsx
import { useEffect, useState } from "react";
import { getDocuments } from "../lib/api";

export function DocumentsList() {
  const [documents, setDocuments] = useState<string[]>([]);

  useEffect(() => {
    void getDocuments().then(setDocuments);
  }, []);

  if (documents.length === 0) {
    return <div className="font-mono text-sm text-terminal-muted">No documents ingested yet.</div>;
  }

  return (
    <ul className="space-y-1 font-mono text-sm text-terminal-text">
      {documents.map((d) => (
        <li key={d} className="rounded border border-terminal-border bg-terminal-panel px-3 py-1.5">{d}</li>
      ))}
    </ul>
  );
}
```

```tsx
// frontend/src/data/DataPage.tsx
import { useState } from "react";
import { ClientsList } from "./ClientsList";
import { DocumentsList } from "./DocumentsList";
import { ImportPanel } from "./ImportPanel";

type Tab = "clients" | "documents" | "import";

export function DataPage() {
  const [tab, setTab] = useState<Tab>("clients");

  const tabs: { id: Tab; label: string }[] = [
    { id: "clients", label: "Clients" },
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
        {tab === "clients" && <ClientsList />}
        {tab === "documents" && <DocumentsList />}
        {tab === "import" && <ImportPanel />}
      </div>
    </div>
  );
}
```

Update `App.tsx`'s `/data` route: `import { DataPage } from "./data/DataPage";` and `<Route path="/data" element={<DataPage />} />`.

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npm test`
Expected: all PASS (note: `DataPage.tsx` imports `ImportPanel` from Task 8 — this task's tests don't exercise `DataPage` directly, only `ClientsList`/`DocumentsList`; `App.test.tsx` doesn't render `/data`, so this forward reference compiles but isn't tested until Task 8 exists — create a stub `ImportPanel.tsx` in this task if `npm test` fails to build without it: `export function ImportPanel() { return null; }`, overwritten by Task 8)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/data/ClientsList.tsx frontend/src/data/ClientsList.test.tsx frontend/src/data/DocumentsList.tsx frontend/src/data/DocumentsList.test.tsx frontend/src/data/DataPage.tsx frontend/src/App.tsx
git commit -m "feat(data-import): read-only Clients and Documents views"
```

---

### Task 8: `ImportPanel` — PDF and Excel upload flows

**Files:**
- Create (overwrite the Task 7 stub): `frontend/src/data/ImportPanel.tsx`
- Create: `frontend/src/data/ImportPanel.test.tsx`
- Modify: `frontend/package.json` (add `xlsx`)

**Interfaces:**
- Consumes: `importPdf`, `previewImport`, `confirmImport` from Task 6.
- Produces: `<ImportPanel />`, wired into `DataPage.tsx`'s "Import" tab (already done in Task 7).

- [ ] **Step 1: Add the dependency**

Run (from `frontend/`): `npm install xlsx@^0.18.5`

- [ ] **Step 2: Write the failing tests**

```tsx
// frontend/src/data/ImportPanel.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as api from "../lib/api";
import { ImportPanel } from "./ImportPanel";

vi.mock("xlsx", () => ({
  read: vi.fn(() => ({ SheetNames: ["Sheet1"], Sheets: { Sheet1: {} } })),
  utils: { sheet_to_json: vi.fn(() => [{ client_email: "jane@x.com", ticker: "AAPL", shares: 10, avg_cost: 150 }]) },
}));

function selectFile(input: HTMLElement, file: File) {
  Object.defineProperty(input, "files", { value: [file] });
  fireEvent.change(input);
}

describe("ImportPanel", () => {
  it("uploads a .pdf directly and shows success", async () => {
    vi.spyOn(api, "importPdf").mockResolvedValue({ filename: "report.pdf", chunks_added: 5 });
    render(<ImportPanel />);
    const input = screen.getByLabelText(/choose a file/i);
    selectFile(input, new File(["%PDF"], "report.pdf", { type: "application/pdf" }));
    expect(await screen.findByText(/5 chunks/i)).toBeInTheDocument();
  });

  it("parses a .xlsx, shows a valid preview, and the Confirm button is enabled", async () => {
    vi.spyOn(api, "previewImport").mockResolvedValue({
      type: "holdings", valid: true,
      rows: [{ client_id: 1, ticker: "AAPL", shares: 10, avg_cost: 150 }], errors: [],
    });
    render(<ImportPanel />);
    const input = screen.getByLabelText(/choose a file/i);
    selectFile(input, new File(["ignored"], "holdings.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /confirmer/i })).not.toBeDisabled());
  });

  it("disables Confirm and shows row errors for an invalid file", async () => {
    vi.spyOn(api, "previewImport").mockResolvedValue({
      type: "holdings", valid: false, rows: [],
      errors: [{ row: 0, field: "client_email", message: "no client with this email" }],
    });
    render(<ImportPanel />);
    const input = screen.getByLabelText(/choose a file/i);
    selectFile(input, new File(["ignored"], "holdings.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    expect(await screen.findByText(/no client with this email/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirmer/i })).toBeDisabled();
  });

  it("clicking Confirm calls confirmImport with the previewed rows and type", async () => {
    vi.spyOn(api, "previewImport").mockResolvedValue({
      type: "holdings", valid: true,
      rows: [{ client_id: 1, ticker: "AAPL", shares: 10, avg_cost: 150 }], errors: [],
    });
    const confirmSpy = vi.spyOn(api, "confirmImport").mockResolvedValue({ written: 1 });
    render(<ImportPanel />);
    const input = screen.getByLabelText(/choose a file/i);
    selectFile(input, new File(["ignored"], "holdings.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    const confirmButton = await screen.findByRole("button", { name: /confirmer/i });
    await waitFor(() => expect(confirmButton).not.toBeDisabled());
    fireEvent.click(confirmButton);
    await waitFor(() => expect(confirmSpy).toHaveBeenCalledWith("holdings", [{ client_id: 1, ticker: "AAPL", shares: 10, avg_cost: 150 }]));
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `frontend/`): `npm test -- ImportPanel`
Expected: FAIL — the stub `ImportPanel` renders `null`.

- [ ] **Step 4: Implement**

```tsx
// frontend/src/data/ImportPanel.tsx
import { useState, type ChangeEvent } from "react";
import * as XLSX from "xlsx";
import { confirmImport, importPdf, previewImport, type ImportPreviewResult } from "../lib/api";

export function ImportPanel() {
  const [status, setStatus] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreviewResult | null>(null);
  const [confirming, setConfirming] = useState(false);

  async function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setStatus(null);
    setPreview(null);

    if (file.name.toLowerCase().endsWith(".pdf")) {
      try {
        const result = await importPdf(file);
        setStatus(`Ingested ${result.filename}: ${result.chunks_added} chunks added.`);
      } catch (err) {
        setStatus(`Error: ${(err as Error).message}`);
      }
      return;
    }

    const buffer = await file.arrayBuffer();
    const workbook = XLSX.read(buffer, { type: "array" });
    const sheet = workbook.Sheets[workbook.SheetNames[0]];
    const rows = XLSX.utils.sheet_to_json(sheet) as Record<string, unknown>[];

    try {
      const result = await previewImport(rows);
      setPreview(result);
    } catch (err) {
      setStatus(`Error: ${(err as Error).message}`);
    }
  }

  async function onConfirm() {
    if (!preview || !preview.valid) return;
    setConfirming(true);
    try {
      const result = await confirmImport(preview.type, preview.rows);
      setStatus(`Imported ${result.written} row(s).`);
      setPreview(null);
    } catch (err) {
      setStatus(`Error: ${(err as Error).message}`);
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="space-y-3 font-mono text-sm text-terminal-text">
      <label className="block">
        <span className="mb-1 block text-xs text-terminal-muted">Choose a file (.pdf, .xlsx)</span>
        <input type="file" accept=".pdf,.xlsx,.xls" onChange={onFileChange} className="text-xs" />
      </label>

      {status && <div className="rounded border border-terminal-border bg-terminal-panel p-2 text-xs">{status}</div>}

      {preview && (
        <div className="rounded-xl border border-terminal-border bg-terminal-panel p-3">
          <div className="mb-2 text-xs text-terminal-muted">Type detected: {preview.type}</div>
          {preview.valid ? (
            <div className="text-xs text-terminal-accent">{preview.rows.length} row(s) ready to import.</div>
          ) : (
            <ul className="space-y-1 text-xs text-terminal-danger">
              {preview.errors.map((e, i) => (
                <li key={i}>Row {e.row + 1}, {e.field}: {e.message}</li>
              ))}
            </ul>
          )}
          <button
            type="button"
            onClick={onConfirm}
            disabled={!preview.valid || confirming}
            className="mt-3 rounded-xl bg-terminal-accent px-4 py-2 font-mono text-sm font-semibold text-terminal-bg disabled:cursor-not-allowed disabled:opacity-40"
          >
            Confirmer
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run (from `frontend/`): `npm test`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/data/ImportPanel.tsx frontend/src/data/ImportPanel.test.tsx
git commit -m "feat(data-import): ImportPanel for PDF and Excel uploads"
```

---

### Task 9: Docs + final verification

**Files:**
- Modify: `CLAUDE.md` (API routers section + architecture notes)
- No code changes beyond documentation.

- [ ] **Step 1: Update `CLAUDE.md`**

In the "API routers (`app/api/routers/`)" section, add a line:

```markdown
- `data.py` — `/data/clients` (GET), `/data/documents` (GET), `/data/import/pdf` (POST), `/data/import/preview` (POST), `/data/import/confirm` (POST). Deterministic, non-agentic CRUD + import for the React console's `/data` section — no LLM, not wired into either graph. Direct sqlite3 access to `customers.db` (bare relative path, same convention as `create_db.py` and the MCP sqlite server), not the MCP indirection the agent uses. See `docs/superpowers/specs/2026-10-03-data-import-and-view-design.md`.
```

Near the React console description, add a line noting the routing change:

```markdown
The console uses `react-router-dom` (`/` Desk, `/classic` Classic chat, `/data` the Data section) — not a `localStorage`-persisted mode toggle.
```

- [ ] **Step 2: Full backend regression**

Run: `uv run pytest tests/ -q`
Expected: all PASS

- [ ] **Step 3: Full frontend regression**

Run (from `frontend/`): `npm test`
Expected: all PASS

- [ ] **Step 4: Live QA (one grounded pass, per project convention)**

Start the backend (`uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload`) and the frontend (`npm run dev` from `frontend/`). In the browser:
1. Navigate to `/data`, confirm the Clients tab lists real clients from `customers.db` with their real holdings.
2. Confirm the Documents tab lists the real current `kb_documents.json` entries.
3. In the Import tab, upload a small real PDF (anything in `./data/` works) — confirm the success message shows a chunk count, and that `search_knowledge_base` (via the chat, either mode) can find content from it afterward.
4. Build a tiny real holdings `.xlsx` (one valid row for an existing client+ticker, e.g. via Excel or `python -c` with `openpyxl`) — upload it, confirm the preview shows "ready to import", click Confirmer, confirm the Clients tab now reflects the new/updated holding.
5. Build a tiny invalid `.xlsx` (unknown ticker) — upload it, confirm the preview shows the row error and Confirmer stays disabled.
6. Confirm `/`, `/classic`, and `/data` are all reachable directly by URL (paste the URL, reload) and the browser back/forward buttons move between them correctly.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document the /data router and the react-router-dom migration"
```
