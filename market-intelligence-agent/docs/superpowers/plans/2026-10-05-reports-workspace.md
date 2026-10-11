# Reports Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/reports` into a client-scoped portfolio report dashboard (profile,
P&L, sector allocation, concentration alerts, price history, positions table,
generated-report list + generate button), replacing the `ComingSoonPage` stub.

**Architecture:** Two new deterministic endpoints under the existing `/data` router
(no new backend router — avoids a Vite proxy-prefix collision with the `/reports`
SPA route) compute everything from already-existing pure functions
(`compute_portfolio_metrics`, `compute_concentration_screen`) and already-existing
direct-call patterns for yfinance. The frontend adds a `/reports` list (reusing
chantier 2's `ClientsList` via a new `basePath` prop) and a `/reports/:id` dashboard
that assembles existing chat display components (`PortfolioPieChart`,
`PortfolioTable`, `ConcentrationAlert`, `PriceChart`, `ReportFileCard`) plus one new
one (`SectorAllocationChart`, no existing `DisplayPayload` variant covers it).

**Tech Stack:** FastAPI, sqlite3, Pydantic-free plain dicts (matches `data.py`'s
existing style), React, react-router-dom, Recharts, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-reports-workspace-design.md`

## Global Constraints

- No new backend router. Both new endpoints live in `app/api/routers/data.py`,
  under its existing `/data` prefix.
- `/reports` must NOT be added to `frontend/vite.config.ts`'s proxy list — the SPA
  route `/reports/:id` is client-side only; the API lives under `/data`, which is
  already proxied.
- `GET /data/clients/{id}/report` degrades on partial pricing: `sector_allocation`
  and `concentration` are computed over the priced subset even when some tickers
  are unpriced, same philosophy as `totals`.
- `POST /data/clients/{id}/report/generate` fails closed: any unpriced ticker is a
  502, not a partial file. This is the opposite philosophy from the GET endpoint,
  intentional (a generated document should never silently omit a holding).
- Report file listing matches the full filename prefix
  `f"{slugify(name)}-portfolio-brief-"`, never the bare slug.
- TDD throughout: write the failing test, watch it fail, then implement.

## Review Focus

- **Zero-holdings client opened in the dashboard**: must render totals-null state
  without crashing, not 500 — `get_client_with_holdings` returns `holdings: []`,
  which must flow all the way to an empty-but-valid JSON response (Task 3).
- **A ticker priced but with no `companies` row** (sector `None`): must not vanish
  from the holdings list (the `LEFT JOIN` choice, Task 1) and must not crash
  `compute_portfolio_metrics`'s `sector_allocation` computation (it already
  degrades to `None` when any position lacks a sector — unchanged behavior, but
  worth a direct test since this is the first caller to actually hit that branch
  from real nullable data instead of a fully-sectored fixture).
- **Generating a report for a client whose name is a substring of another client's
  name** (e.g. "Ann Lee" / "Ann Lee-Osei"): must not hit the chat tool's
  `LIKE '%name%'` ambiguity at all, because the new generate endpoint resolves by
  `client_id`, never by name matching — Task 4's test should include two clients
  with overlapping names to prove this.
- **Hard-reloading the browser at `/reports/12`** (not navigating in-app): must
  still load the SPA, not a backend 404 — this is the proxy-collision risk the
  spec's architecture section exists to avoid. Not unit-testable (it's a dev-server
  routing property), so it's called out explicitly in the Testing section as a
  live-QA step instead of silently assumed.
- **Two existing report files where one client's slug is a literal prefix of
  another's** (e.g. `jane-doe` vs `jane-doering`): the listing must not leak the
  other client's file — Task 3's test includes this decoy explicitly.

---

### Task 1: Sector-joined holdings query

**Files:**
- Modify: `app/data_import/db.py:42-61` (`get_client_with_holdings`)
- Test: `tests/unit/test_data_import_db.py:126-140`

**Interfaces:**
- Consumes: nothing new.
- Produces: `get_client_with_holdings(conn, client_id) -> dict | None`, where each
  item in `holdings` now has `{"ticker", "shares", "avg_cost", "sector"}` (was
  `{"ticker", "shares", "avg_cost"}`). `sector` is `None` when the ticker has no
  matching row in `companies`. Every later task that reads a holding's `sector`
  key relies on this.

- [ ] **Step 1: Write the failing test**

Update the existing test in `tests/unit/test_data_import_db.py` (around line 126)
to expect the new `sector` key, and add a new test right after it for the
`LEFT JOIN` behavior (a ticker missing from `companies`):

```python
def test_get_client_with_holdings_returns_the_client_and_their_holdings(conn):
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10.0, 150.0)")
    conn.commit()

    result = get_client_with_holdings(conn, 1)

    assert result == {
        "client_id": 1, "name": "Jane Doe", "email": "jane@x.com", "segment": "VIP",
        "risk_profile": "balanced", "advisor": "Sam", "city": "Paris",
        "holdings": [{"ticker": "AAPL", "shares": 10.0, "avg_cost": 150.0, "sector": "Technology"}],
    }


def test_get_client_with_holdings_returns_none_for_an_unknown_id(conn):
    assert get_client_with_holdings(conn, 999) is None


def test_get_client_with_holdings_keeps_a_holding_whose_ticker_has_no_companies_row(conn):
    # SQLite does not enforce the holdings.ticker REFERENCES companies.ticker
    # foreign key unless PRAGMA foreign_keys=ON (it isn't, here) -- this
    # INSERT is legal even though 'GHOST' is absent from companies. An INNER
    # JOIN would silently drop this holding; this test is the guard against
    # ever switching back to one.
    conn.execute("INSERT INTO holdings VALUES (1, 'GHOST', 5.0, 10.0)")
    conn.commit()

    result = get_client_with_holdings(conn, 1)

    assert result["holdings"] == [{"ticker": "GHOST", "shares": 5.0, "avg_cost": 10.0, "sector": None}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_data_import_db.py -v`
Expected: the updated test and the new test both FAIL — the updated one on a dict
mismatch (missing `"sector"` key in the actual result), the new one with a
`KeyError` or assertion mismatch, since `get_client_with_holdings` doesn't select
`sector` at all yet.

- [ ] **Step 3: Implement the LEFT JOIN**

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
        {"ticker": ticker, "shares": shares, "avg_cost": avg_cost, "sector": sector}
        for ticker, shares, avg_cost, sector in conn.execute(
            "SELECT h.ticker, h.shares, h.avg_cost, co.sector "
            "FROM holdings h LEFT JOIN companies co ON co.ticker = h.ticker "
            "WHERE h.client_id = ?",
            (cid,),
        )
    ]
    return {
        "client_id": cid, "name": name, "email": email, "segment": segment,
        "risk_profile": risk_profile, "advisor": advisor, "city": city,
        "holdings": holdings,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_data_import_db.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Run the full backend suite (this function has other callers)**

Run: `uv run pytest tests/ -q`
Expected: PASS. `build_client_summary` (chantier 2, `/data/clients/{id}/summary`)
calls this same function and ignores the new `sector` key — no change expected
there, but this confirms it.

- [ ] **Step 6: Commit**

```bash
git add app/data_import/db.py tests/unit/test_data_import_db.py
git commit -m "feat(reports): LEFT JOIN sector into get_client_with_holdings"
```

---

### Task 2: Export `slugify` from `portfolio_report.py`

**Files:**
- Modify: `app/agent/tools/portfolio_report.py:122,147` (`_slugify` → `slugify`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `slugify(name: str) -> str` (was `_slugify`, module-private). Task 3 and
  Task 4 import this.

No test file currently imports `_slugify` by name (confirmed: only
`build_portfolio_report_xlsx`'s own filename-assertion tests in
`tests/unit/test_portfolio_report.py` exercise it indirectly, via the filenames
`save_portfolio_report` produces). This is a pure rename with one internal call
site — not itself a new failing-test cycle, since no observable behavior changes.
Still runs through the full suite before committing, per the Global Constraints'
TDD line, because a rename that breaks its one call site is exactly the kind of
mistake a test run catches immediately.

- [ ] **Step 1: Rename**

```python
def slugify(name: str) -> str:
    # Lowercase, spaces to hyphens, drop anything that isn't alnum/hyphen --
    # a client name can contain an apostrophe (O'Brien) that must never
    # reach a filesystem path unescaped.
    cleaned = "".join(c if c.isalnum() or c in (" ", "-") else "" for c in name.lower())
    return "-".join(cleaned.split())
```

And update its one call site:

```python
    filename = f"{slugify(portfolio['client_name'])}-portfolio-brief-{today}.xlsx"
```

- [ ] **Step 2: Run the full backend suite**

Run: `uv run pytest tests/unit/test_portfolio_report.py -v`
Expected: PASS, all tests (apostrophe/partial-match/filename tests still pass —
they call `save_portfolio_report`/`save_portfolio_report_tool`, never `_slugify`
directly, so the rename is invisible to them).

- [ ] **Step 3: Commit**

```bash
git add app/agent/tools/portfolio_report.py
git commit -m "refactor(reports): rename _slugify to slugify, it's cross-module now"
```

---

### Task 3: `GET /data/clients/{client_id}/report`

**Files:**
- Modify: `app/api/routers/data.py`
- Test: `tests/unit/test_data_endpoints.py`

**Interfaces:**
- Consumes: `get_client_with_holdings` (Task 1, now sector-joined), `slugify`
  (Task 2), `app.agent.tools.finance_calc.{Position, LabeledPortfolio,
  compute_portfolio_metrics, compute_concentration_screen}`,
  `app.agent.multi_agent.display.normalize_price_history`,
  `app.agent.tools.mcp_clients.yfinance_client.yf_history_tool`, the existing
  `_live_price` helper (`app/api/routers/data.py:67-74`), `settings.WORKSPACE_ROOT`
  (`app.core.config.settings`).
- Produces: a new `_price_history(ticker: str) -> list[dict]` async helper
  (monkeypatchable the same way the existing `_live_price` is — tests patch
  `data_router_module._price_history`), and the endpoint itself. Task 9's frontend
  work consumes this endpoint's exact response shape, given below.

The yfinance price-history tool is markdown-text, not JSON — confirmed by reading
`app/agent/multi_agent/display.py`'s `normalize_price_history`, which parses a
pipe-delimited markdown table (`| Date | Open | High | Low | Close | ... |`) out of
the tool's raw text, not `concentration.py`'s `parse_tool_payload` (which assumes
JSON or a Python literal and would raise on markdown). This task reuses that exact
same normalizer instead of re-parsing the table, so it never disagrees with what
the chat already renders for the same tool.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_data_endpoints.py` (after the existing `/summary` tests,
before `test_get_documents_reads_the_manifest`). First, two helpers the tests
below share — a fake price-history payload and a way to point `WORKSPACE_ROOT` at
an isolated directory:

```python
PRICE_HISTORY_TEXT = (
    "| Date                      |   Open |   High |    Low |   Close |      Volume |\n"
    "|:--------------------------|-------:|-------:|-------:|--------:|------------:|\n"
    "| 2026-09-21 00:00:00-04:00 | 335.28 | 339.64 | 333.05 |  338.98 | 3.49992e+07 |\n"
)


@pytest.fixture
def reports_dir(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    monkeypatch.setattr("app.api.routers.data.settings.WORKSPACE_ROOT", root)
    return root / "reports"


def test_get_client_report_computes_totals_sector_and_concentration(client, monkeypatch, reports_dir):
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute("INSERT INTO companies VALUES ('NVDA', 'NVIDIA', 'Technology')")
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.execute("INSERT INTO holdings VALUES (1, 'NVDA', 5, 30.0)")
    conn.commit()
    conn.close()

    async def fake_price(ticker):
        return {"AAPL": 200.0, "NVDA": 2000.0}[ticker]

    async def fake_history(ticker):
        return [{"date": "2026-09-21", "close": 338.98}]

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)
    monkeypatch.setattr(data_router_module, "_price_history", fake_history)

    resp = client.get("/data/clients/1/report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["market_value"] == 12000.0
    assert body["sector_allocation"] == {"Technology": 100.0}
    assert body["concentration"]["breaches"][0]["ticker"] == "NVDA"
    assert set(body["price_history"].keys()) == {"AAPL", "NVDA"}
    assert body["price_history"]["NVDA"] == [{"date": "2026-09-21", "close": 338.98}]
    assert body["unpriced_tickers"] == []


def test_get_client_report_degrades_when_one_ticker_is_unpriced(client, monkeypatch, reports_dir):
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute("INSERT INTO companies VALUES ('NVDA', 'NVIDIA', 'Technology')")
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.execute("INSERT INTO holdings VALUES (1, 'NVDA', 5, 30.0)")
    conn.commit()
    conn.close()

    async def flaky_price(ticker):
        if ticker == "NVDA":
            raise ValueError("yfinance is down")
        return 200.0

    monkeypatch.setattr(data_router_module, "_live_price", flaky_price)
    monkeypatch.setattr(data_router_module, "_price_history", lambda ticker: [])

    resp = client.get("/data/clients/1/report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["unpriced_tickers"] == ["NVDA"]
    assert body["totals"]["market_value"] == 2000.0  # AAPL only
    assert all(b["ticker"] != "NVDA" for b in body["concentration"]["breaches"])


def test_get_client_report_degrades_sector_allocation_when_one_holding_has_no_sector(client, monkeypatch, reports_dir):
    # GHOST has no companies row (sector None) -- compute_portfolio_metrics's
    # existing all-sectors-present rule must take sector_allocation to None
    # for the whole portfolio, not crash and not silently drop GHOST.
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.execute("INSERT INTO holdings VALUES (1, 'GHOST', 5, 10.0)")
    conn.commit()
    conn.close()

    async def fake_price(ticker):
        return 200.0

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)
    monkeypatch.setattr(data_router_module, "_price_history", lambda ticker: [])

    resp = client.get("/data/clients/1/report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sector_allocation"] is None
    assert {p["ticker"] for p in body["positions"]} == {"AAPL", "GHOST"}
    assert body["unpriced_tickers"] == []


def test_get_client_report_with_no_holdings_returns_empty_payload_not_an_error(client, reports_dir):
    resp = client.get("/data/clients/1/report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"] is None
    assert body["positions"] == []
    assert body["sector_allocation"] is None
    assert body["concentration"] is None
    assert body["price_history"] == {}
    assert body["generated_reports"] == []


def test_get_client_report_404s_for_an_unknown_client(client, reports_dir):
    resp = client.get("/data/clients/999/report")
    assert resp.status_code == 404


def test_get_client_report_lists_this_clients_files_only(client, reports_dir):
    reports_dir.mkdir(parents=True)
    (reports_dir / "jane-doe-portfolio-brief-2026-01-01.xlsx").write_bytes(b"PK fake")
    # Decoy: a different client whose slug ("jane-doering") shares the bare
    # prefix "jane-doe" with ours, but not the full "jane-doe-portfolio-brief-"
    # prefix -- proves the listing matches the full prefix, not the bare slug.
    (reports_dir / "jane-doering-portfolio-brief-2026-01-01.xlsx").write_bytes(b"PK fake")

    resp = client.get("/data/clients/1/report")  # client 1 is "Jane Doe"
    assert resp.status_code == 200
    filenames = [r["filename"] for r in resp.json()["generated_reports"]]
    assert filenames == ["jane-doe-portfolio-brief-2026-01-01.xlsx"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k report -v`
Expected: every new test FAILs with a 404 (route doesn't exist yet) — FastAPI
returns 404 for an unmatched route, so `test_get_client_report_404s_for_an_unknown_client`
is the one test in this batch that needs a second look: it currently fails with
status 404 for the *wrong* reason (no such route at all, vs. "route exists, client
999 doesn't"). Confirm the others fail on `resp.status_code == 200` first (they
get the generic 404), which is the right failure for "the endpoint doesn't exist".

- [ ] **Step 3: Implement**

Add these imports to the top of `app/api/routers/data.py`:

```python
import asyncio
from datetime import datetime, timezone

from app.agent.tools.finance_calc import LabeledPortfolio, Position, compute_concentration_screen, compute_portfolio_metrics
from app.agent.tools.portfolio_report import slugify
from app.core.config import settings
```

Add these helpers and the endpoint, after the existing `_live_price` function:

```python
def _tool_content_text(result) -> str:
    # Same content-block-joining step parse_tool_payload does, stopped
    # before its JSON/literal_eval attempt -- yfinance_get_price_history's
    # raw text is a markdown table, not JSON, and would fail both.
    if isinstance(result, list) and result and all(isinstance(b, dict) and "type" in b for b in result):
        return "".join(b.get("text", "") for b in result if b.get("type") == "text")
    return str(result)


async def _price_history(ticker: str) -> list[dict]:
    from app.agent.multi_agent.display import normalize_price_history
    from app.agent.tools.mcp_clients.yfinance_client import yf_history_tool

    symbol_arg = "symbol" if "symbol" in yf_history_tool.args else "ticker"
    raw = await yf_history_tool.ainvoke({symbol_arg: ticker, "period": "3mo"})
    text = _tool_content_text(raw)
    displays = normalize_price_history(text, {symbol_arg: ticker})
    return displays[0]["points"] if displays else []


@router.get("/clients/{client_id}/report")
async def get_client_report(client_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        client = get_client_with_holdings(conn, client_id)
    finally:
        conn.close()
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")

    holdings = client["holdings"]
    tickers = [h["ticker"] for h in holdings]
    price_results = await asyncio.gather(*(_live_price(t) for t in tickers), return_exceptions=True)

    priced_positions: list[Position] = []
    unpriced_tickers: list[str] = []
    for holding, result in zip(holdings, price_results):
        if isinstance(result, BaseException):
            unpriced_tickers.append(holding["ticker"])
            continue
        priced_positions.append(Position(
            ticker=holding["ticker"], shares=holding["shares"], avg_cost=holding["avg_cost"],
            price=float(result), sector=holding.get("sector"),
        ))

    totals: dict | None = None
    positions: list[dict] = []
    sector_allocation: dict | None = None
    concentration: dict | None = None
    price_history: dict[str, list[dict]] = {}

    if priced_positions:
        metrics = compute_portfolio_metrics(priced_positions)
        totals = metrics["totals"]
        positions = metrics["positions"]
        sector_allocation = metrics["sector_allocation"]
        concentration = compute_concentration_screen(
            [LabeledPortfolio(label=client["name"], positions=priced_positions)],
            threshold_pct=30.0,
        )
        top = sorted(positions, key=lambda p: -p["weight_pct"])[:3]
        history_results = await asyncio.gather(
            *(_price_history(p["ticker"]) for p in top), return_exceptions=True,
        )
        for p, result in zip(top, history_results):
            if not isinstance(result, BaseException) and result:
                price_history[p["ticker"]] = result

    reports_dir = settings.WORKSPACE_ROOT.resolve() / "reports"
    prefix = f"{slugify(client['name'])}-portfolio-brief-"
    files = sorted(
        (f for f in reports_dir.glob(f"{prefix}*.xlsx") if f.is_file()),
        key=lambda f: f.stat().st_mtime, reverse=True,
    ) if reports_dir.is_dir() else []
    generated_reports = [
        {
            "filename": f.name,
            "generated_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
            "download_url": f"/workspace/files/{f.name}",
        }
        for f in files
    ]

    return {
        "client_id": client["client_id"], "name": client["name"], "email": client["email"],
        "segment": client["segment"], "risk_profile": client["risk_profile"],
        "advisor": client["advisor"], "city": client["city"],
        "totals": totals, "positions": positions, "sector_allocation": sector_allocation,
        "concentration": concentration, "price_history": price_history,
        "unpriced_tickers": unpriced_tickers, "generated_reports": generated_reports,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k report -v`
Expected: PASS, all 5 new tests.

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest tests/ -q`
Expected: PASS, no regressions (435 + the new tests from Tasks 1-3).

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/data.py tests/unit/test_data_endpoints.py
git commit -m "feat(reports): add GET /data/clients/{id}/report dashboard endpoint"
```

---

### Task 4: `POST /data/clients/{client_id}/report/generate`

**Files:**
- Modify: `app/api/routers/data.py`
- Test: `tests/unit/test_data_endpoints.py`

**Interfaces:**
- Consumes: `get_client_with_holdings`, `slugify`, `_live_price` (all from earlier
  tasks), `app.agent.tools.portfolio_report.build_portfolio_report_xlsx`,
  `app.agent.tools.finance_calc.{Position, compute_portfolio_metrics}`.
- Produces: the endpoint, returning `{"filename": str}` on success. Task 9's
  "Generate report" button calls this.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_data_endpoints.py`:

```python
def test_generate_client_report_writes_a_file_and_returns_its_name(client, monkeypatch, reports_dir):
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.commit()
    conn.close()

    async def fake_price(ticker):
        return 200.0

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)

    resp = client.post("/data/clients/1/report/generate")
    assert resp.status_code == 200
    filename = resp.json()["filename"]
    assert filename.startswith("jane-doe-portfolio-brief-")
    assert (reports_dir / filename).is_file()


def test_generate_client_report_fails_closed_on_an_unpriced_ticker(client, monkeypatch, reports_dir):
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.commit()
    conn.close()

    async def failing_price(ticker):
        raise ValueError("yfinance is down")

    monkeypatch.setattr(data_router_module, "_live_price", failing_price)

    resp = client.post("/data/clients/1/report/generate")
    assert resp.status_code == 502
    assert "AAPL" in resp.json()["detail"]
    assert not reports_dir.exists() or list(reports_dir.iterdir()) == []


def test_generate_client_report_400s_on_zero_holdings(client, reports_dir):
    resp = client.post("/data/clients/1/report/generate")
    assert resp.status_code == 400


def test_generate_client_report_404s_for_an_unknown_client(client, reports_dir):
    resp = client.post("/data/clients/999/report/generate")
    assert resp.status_code == 404


def test_generate_client_report_503s_in_gateway_mode(client, monkeypatch, reports_dir):
    monkeypatch.setattr("app.api.routers.data.settings.MCP_TRANSPORT", "gateway")
    resp = client.post("/data/clients/1/report/generate")
    assert resp.status_code == 503
    assert not reports_dir.exists()


def test_generate_client_report_resolves_by_id_not_name_even_with_overlapping_names(client, monkeypatch, reports_dir):
    # The chat tool (save_portfolio_report_tool) resolves by LIKE '%name%' and
    # would return an ambiguous-match error for two clients sharing a
    # substring. This endpoint must not go anywhere near that path.
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute(
        "INSERT INTO clients VALUES (2, 'Jane Doering', 'jane2@x.com', 'VIP', 'balanced', 'Sam', 'Paris', '2024-01-01')"
    )
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.execute("INSERT INTO holdings VALUES (2, 'AAPL', 5, 100.0)")
    conn.commit()
    conn.close()

    async def fake_price(ticker):
        return 200.0

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)

    resp1 = client.post("/data/clients/1/report/generate")
    resp2 = client.post("/data/clients/2/report/generate")
    assert resp1.status_code == 200 and resp2.status_code == 200
    assert resp1.json()["filename"].startswith("jane-doe-portfolio-brief-")
    assert resp2.json()["filename"].startswith("jane-doering-portfolio-brief-")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k generate -v`
Expected: FAIL, 404 (route doesn't exist) on every test.

- [ ] **Step 3: Implement**

Add this import alongside Task 3's:

```python
from app.agent.tools.portfolio_report import build_portfolio_report_xlsx, slugify
```

(This replaces Task 3's bare `from app.agent.tools.portfolio_report import slugify`
— both names come from the same module.)

```python
@router.post("/clients/{client_id}/report/generate")
async def generate_client_report(client_id: int) -> dict:
    if settings.MCP_TRANSPORT.lower() == "gateway":
        raise HTTPException(
            status_code=503,
            detail="save_portfolio_report is not available in this deployment "
            "(MCP_TRANSPORT=gateway has no S3 write path for this tool yet).",
        )
    conn = sqlite3.connect(DB_PATH)
    try:
        client = get_client_with_holdings(conn, client_id)
    finally:
        conn.close()
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")

    holdings = client["holdings"]
    if not holdings:
        raise HTTPException(status_code=400, detail="build_portfolio_report_xlsx needs at least one position")

    tickers = [h["ticker"] for h in holdings]
    price_results = await asyncio.gather(*(_live_price(t) for t in tickers), return_exceptions=True)
    failed = [t for t, r in zip(tickers, price_results) if isinstance(r, BaseException)]
    if failed:
        raise HTTPException(status_code=502, detail=f"could not price: {', '.join(failed)}")

    positions = [
        Position(ticker=h["ticker"], shares=h["shares"], avg_cost=h["avg_cost"], price=float(r))
        for h, r in zip(holdings, price_results)
    ]
    portfolio = compute_portfolio_metrics(positions)
    portfolio["client_name"] = client["name"]

    xlsx_bytes = await asyncio.to_thread(build_portfolio_report_xlsx, portfolio)
    today = datetime.now(timezone.utc).date().isoformat()
    filename = f"{slugify(client['name'])}-portfolio-brief-{today}.xlsx"
    reports_dir = settings.WORKSPACE_ROOT.resolve() / "reports"

    def _write() -> None:
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / filename).write_bytes(xlsx_bytes)

    await asyncio.to_thread(_write)
    return {"filename": filename}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k "report or generate" -v`
Expected: PASS, all tests from Tasks 3 and 4.

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest tests/ -q`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/data.py tests/unit/test_data_endpoints.py
git commit -m "feat(reports): add POST /data/clients/{id}/report/generate"
```

---

### Task 5: Frontend API client functions

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Consumes: the exact response shapes Tasks 3 and 4 produce.
- Produces: `ClientReport` type, `GeneratedReportFile` type,
  `getClientReport(clientId, base=API_BASE): Promise<ClientReport>`,
  `generateClientReport(clientId, base=API_BASE): Promise<{filename: string}>`.
  Task 8 (`ReportWorkspace.tsx`) imports all four.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/lib/api.test.ts` (import line gains
`getClientReport, generateClientReport`):

```typescript
import {
  uploadToWorkspace, getClients, getClientSummary, getDocuments, getThreadHistory,
  importPdf, previewImport, confirmImport, getClientReport, generateClientReport,
} from "./api";
```

```typescript
describe("reports API", () => {
  it("getClientReport fetches /data/clients/:id/report", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 1, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: null, positions: [], sector_allocation: null, concentration: null,
        price_history: {}, unpriced_tickers: [], generated_reports: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const result = await getClientReport(1);
    expect(fetchMock).toHaveBeenCalledWith("/data/clients/1/report");
    expect(result.name).toBe("Jane Doe");
  });

  it("generateClientReport posts to /data/clients/:id/report/generate", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ filename: "jane-doe-portfolio-brief-2026-01-01.xlsx" }) });
    vi.stubGlobal("fetch", fetchMock);
    const result = await generateClientReport(1);
    expect(fetchMock).toHaveBeenCalledWith("/data/clients/1/report/generate", { method: "POST" });
    expect(result.filename).toBe("jane-doe-portfolio-brief-2026-01-01.xlsx");
  });

  it("generateClientReport throws the backend's detail message on failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 502, json: async () => ({ detail: "could not price: AAPL" }),
    }));
    await expect(generateClientReport(1)).rejects.toThrow("could not price: AAPL");
  });

  it("generateClientReport falls back to a generic message when the body isn't JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 500, json: async () => { throw new Error("not json"); },
    }));
    await expect(generateClientReport(1)).rejects.toThrow("500");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/api.test.ts`
Expected: FAIL — `getClientReport`/`generateClientReport` are not exported yet
(import error / `undefined is not a function`).

- [ ] **Step 3: Implement**

Add to `frontend/src/lib/api.ts`, after `ClientSummary`/`getClientSummary`:

```typescript
export interface GeneratedReportFile {
  filename: string;
  generated_at: string;
  download_url: string;
}

export interface ClientReport {
  client_id: number;
  name: string;
  email: string;
  segment: string;
  risk_profile: string;
  advisor: string;
  city: string;
  totals: { market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number } | null;
  positions: {
    ticker: string; shares: number; price: number; sector: string | null;
    market_value: number; cost_basis: number; unrealized_pnl: number;
    unrealized_pnl_pct: number; weight_pct: number;
  }[];
  sector_allocation: Record<string, number> | null;
  concentration: { threshold_pct: number; breach_count: number; breaches: { label: string; ticker: string; weight_pct: number; market_value: number }[] } | null;
  price_history: Record<string, { date: string; close: number }[]>;
  unpriced_tickers: string[];
  generated_reports: GeneratedReportFile[];
}

export async function getClientReport(clientId: number, base = API_BASE): Promise<ClientReport> {
  const res = await fetch(`${base}/data/clients/${clientId}/report`);
  if (!res.ok) throw new Error(`client report ${res.status}`);
  return res.json();
}

async function _detailOrStatus(res: Response, fallbackLabel: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // body wasn't JSON -- fall through to the generic message
  }
  return `${fallbackLabel} ${res.status}`;
}

export async function generateClientReport(clientId: number, base = API_BASE): Promise<{ filename: string }> {
  const res = await fetch(`${base}/data/clients/${clientId}/report/generate`, { method: "POST" });
  if (!res.ok) throw new Error(await _detailOrStatus(res, "generate report"));
  return res.json();
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/api.test.ts`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts
git commit -m "feat(reports): add getClientReport/generateClientReport API functions"
```

---

### Task 6: `ClientsList` basePath prop + `ReportsPage`

**Files:**
- Modify: `frontend/src/clients/ClientsList.tsx`
- Test: `frontend/src/clients/ClientsList.test.tsx`
- Create: `frontend/src/reports/ReportsPage.tsx`
- Test: `frontend/src/reports/ReportsPage.test.tsx`

**Interfaces:**
- Consumes: `getClients` (`frontend/src/lib/api.ts`, unchanged).
- Produces: `ClientsList({ basePath = "/clients" }: { basePath?: string })`,
  `ReportsPage()`. Task 9's App.tsx wiring consumes `ReportsPage`.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/clients/ClientsList.test.tsx`, right after the existing
`"clicking a client row navigates to /clients/:id"` test:

```typescript
  it("clicking a client row navigates under a custom basePath when given one", async () => {
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
      <MemoryRouter initialEntries={["/reports"]}>
        <Routes>
          <Route path="/reports" element={<ClientsList basePath="/reports" />} />
          <Route path="/reports/:id" element={<div data-testid="navigated-to">arrived</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await user.click(await screen.findByText("Jane Doe"));
    expect(await screen.findByTestId("navigated-to")).toBeInTheDocument();
  });
```

Create `frontend/src/reports/ReportsPage.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ReportsPage } from "./ReportsPage";

describe("ReportsPage", () => {
  it("renders the client list, and a row click navigates to /reports/:id", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris", holdings: [],
      }],
    }));
    render(
      <MemoryRouter initialEntries={["/reports"]}>
        <Routes>
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/reports/:id" element={<div data-testid="navigated-to">arrived</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    await user.click(screen.getByText("Jane Doe"));
    expect(await screen.findByTestId("navigated-to")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/clients/ClientsList.test.tsx src/reports/ReportsPage.test.tsx`
Expected: FAIL — the new `ClientsList` test fails because `basePath` is ignored
(navigates to `/clients/12`, which has no matching `Route` in that test's tree, so
`navigated-to` never appears); `ReportsPage.test.tsx` fails because the module
doesn't exist.

- [ ] **Step 3: Implement**

In `frontend/src/clients/ClientsList.tsx`, change the component signature and the
one `navigate` call:

```typescript
export function ClientsList({ basePath = "/clients" }: { basePath?: string } = {}) {
  const navigate = useNavigate();
  ...
          onClick={() => navigate(`${basePath}/${c.client_id}`)}
```

(Only those two lines change — everything else in the file is unchanged.)

Create `frontend/src/reports/ReportsPage.tsx`:

```typescript
import { ClientsList } from "../clients/ClientsList";

export function ReportsPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto p-4">
      <ClientsList basePath="/reports" />
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/clients/ClientsList.test.tsx src/clients/ClientsPage.test.tsx src/reports/ReportsPage.test.tsx`
Expected: PASS, all tests — including the pre-existing `ClientsPage.test.tsx`
(which renders `<ClientsList />` with no `basePath`, proving the default still
navigates to `/clients/:id`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/clients/ClientsList.tsx frontend/src/clients/ClientsList.test.tsx frontend/src/reports/ReportsPage.tsx frontend/src/reports/ReportsPage.test.tsx
git commit -m "feat(reports): add ReportsPage, basePath prop on ClientsList"
```

---

### Task 7: `SectorAllocationChart`

**Files:**
- Create: `frontend/src/reports/SectorAllocationChart.tsx`
- Test: `frontend/src/reports/SectorAllocationChart.test.tsx`

**Interfaces:**
- Consumes: nothing project-specific (Recharts only).
- Produces: `SectorAllocationChart({ sectorAllocation }: { sectorAllocation: Record<string, number> | null })`.
  Task 8 imports this.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/reports/SectorAllocationChart.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SectorAllocationChart } from "./SectorAllocationChart";

describe("SectorAllocationChart", () => {
  it("renders a bar per sector", () => {
    render(<SectorAllocationChart sectorAllocation={{ Technology: 58.5, ETF: 13.4 }} />);
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("ETF")).toBeInTheDocument();
  });

  it("renders nothing when sectorAllocation is null", () => {
    const { container } = render(<SectorAllocationChart sectorAllocation={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/reports/SectorAllocationChart.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/reports/SectorAllocationChart.tsx`:

```typescript
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

// Same palette the other display components use (desk/displays/PortfolioPieChart.tsx).
const COLORS = ["#34d399", "#fbbf24", "#f87171", "#6b7a8d", "#1e3a5f", "#2563eb"];

export function SectorAllocationChart({ sectorAllocation }: { sectorAllocation: Record<string, number> | null }) {
  if (!sectorAllocation) return null;
  const data = Object.entries(sectorAllocation).map(([sector, weight_pct]) => ({ sector, weight_pct }));
  return (
    <div className="h-56 w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-2">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" stroke="#1c2733" />
          <XAxis type="number" tick={{ fill: "#6b7a8d", fontSize: 10 }} />
          <YAxis type="category" dataKey="sector" tick={{ fill: "#6b7a8d", fontSize: 10 }} width={90} />
          <Tooltip contentStyle={{ background: "#0f1620", border: "1px solid #1c2733", fontSize: 11 }} />
          <Bar dataKey="weight_pct">
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/reports/SectorAllocationChart.test.tsx`
Expected: PASS, both tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/reports/SectorAllocationChart.tsx frontend/src/reports/SectorAllocationChart.test.tsx
git commit -m "feat(reports): add SectorAllocationChart"
```

---

### Task 8: `ReportWorkspace`

**Files:**
- Create: `frontend/src/reports/ReportWorkspace.tsx`
- Test: `frontend/src/reports/ReportWorkspace.test.tsx`

**Interfaces:**
- Consumes: `getClientReport`, `generateClientReport`, `ClientReport` (Task 5),
  `SectorAllocationChart` (Task 7), and the existing
  `PortfolioPieChart`/`PortfolioTable`/`ConcentrationAlert`/`PriceChart`/`ReportFileCard`
  from `frontend/src/desk/displays/`.
- Produces: `ReportWorkspace()` (reads `:id` via `useParams`, same pattern as
  `ClientWorkspace`). Task 9's App.tsx wiring consumes this.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/reports/ReportWorkspace.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ReportWorkspace } from "./ReportWorkspace";

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/reports/${id}`]}>
      <Routes>
        <Route path="/reports/:id" element={<ReportWorkspace />} />
      </Routes>
    </MemoryRouter>,
  );
}

const FULL_REPORT = {
  client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
  risk_profile: "balanced", advisor: "Sam", city: "Paris",
  totals: { market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33 },
  positions: [
    { ticker: "AAPL", shares: 10, price: 200, sector: "Technology", market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33, weight_pct: 100 },
  ],
  sector_allocation: { Technology: 100 },
  concentration: { threshold_pct: 30, breach_count: 1, breaches: [{ label: "Jane Doe", ticker: "AAPL", weight_pct: 100, market_value: 2000 }] },
  price_history: { AAPL: [{ date: "2026-09-21", close: 338.98 }] },
  unpriced_tickers: [],
  generated_reports: [{ filename: "jane-doe-portfolio-brief-2026-01-01.xlsx", generated_at: "2026-01-01T00:00:00+00:00", download_url: "/workspace/files/jane-doe-portfolio-brief-2026-01-01.xlsx" }],
};

describe("ReportWorkspace", () => {
  it("renders every section when every field is populated", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => FULL_REPORT }));
    renderAt("12");
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument(); // SectorAllocationChart
    expect(screen.getByText(/Concentration/)).toBeInTheDocument(); // ConcentrationAlert
    expect(screen.getByText("AAPL")).toBeInTheDocument(); // PortfolioTable
    expect(screen.getByText("jane-doe-portfolio-brief-2026-01-01.xlsx")).toBeInTheDocument(); // ReportFileCard
    expect(screen.getByRole("link", { name: /back/i })).toHaveAttribute("href", "/reports");
  });

  it("omits the sector chart and concentration alert when both are null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...FULL_REPORT, sector_allocation: null, concentration: null }),
    }));
    renderAt("12");
    await screen.findByText("Jane Doe");
    expect(screen.queryByText("Technology")).not.toBeInTheDocument();
    expect(screen.queryByText(/Concentration/)).not.toBeInTheDocument();
  });

  it("shows 'No position.' when totals is null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...FULL_REPORT, totals: null, positions: [], sector_allocation: null,
        concentration: null, price_history: {},
      }),
    }));
    renderAt("12");
    expect(await screen.findByText(/no position/i)).toBeInTheDocument();
  });

  it("clicking Generate report calls generateClientReport and re-fetches on success", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    let generateCalled = false;
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        generateCalled = true;
        return Promise.resolve({ ok: true, json: async () => ({ filename: "new-file.xlsx" }) });
      }
      return Promise.resolve({ ok: true, json: async () => FULL_REPORT });
    }));
    renderAt("12");
    await screen.findByText("Jane Doe");
    await user.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(generateCalled).toBe(true));
  });

  it("shows the thrown error message inline when Generate report fails", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve({ ok: false, status: 502, json: async () => ({ detail: "could not price: AAPL" }) });
      }
      return Promise.resolve({ ok: true, json: async () => FULL_REPORT });
    }));
    renderAt("12");
    await screen.findByText("Jane Doe");
    await user.click(screen.getByRole("button", { name: /generate report/i }));
    expect(await screen.findByText(/could not price: AAPL/i)).toBeInTheDocument();
  });

  it("shows an error banner with a link back to /reports when the report fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }));
    renderAt("999");
    expect(await screen.findByText(/failed to load/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back/i })).toHaveAttribute("href", "/reports");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/reports/ReportWorkspace.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/reports/ReportWorkspace.tsx`:

```typescript
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ConcentrationAlert } from "../desk/displays/ConcentrationAlert";
import { PortfolioPieChart } from "../desk/displays/PortfolioPieChart";
import { PortfolioTable } from "../desk/displays/PortfolioTable";
import { PriceChart } from "../desk/displays/PriceChart";
import { ReportFileCard } from "../desk/displays/ReportFileCard";
import { generateClientReport, getClientReport, type ClientReport } from "../lib/api";
import { SectorAllocationChart } from "./SectorAllocationChart";

function ReportWorkspaceBody({ clientId }: { clientId: number }) {
  const [report, setReport] = useState<ClientReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  function load() {
    getClientReport(clientId)
      .then(setReport)
      .catch(() => setError("Failed to load this client's report."));
  }

  useEffect(() => {
    let active = true;
    setReport(null);
    setError(null);
    getClientReport(clientId)
      .then((r) => {
        if (active) setReport(r);
      })
      .catch(() => {
        if (active) setError("Failed to load this client's report.");
      });
    return () => {
      active = false;
    };
  }, [clientId]);

  async function onGenerate() {
    setGenerating(true);
    setGenerateError(null);
    try {
      await generateClientReport(clientId);
      load();
    } catch (err) {
      setGenerateError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  if (error) {
    return (
      <main className="flex min-h-0 min-w-0 flex-1 flex-col items-center justify-center gap-3 font-mono text-sm">
        <div className="text-terminal-danger">{error}</div>
        <Link to="/reports" className="text-terminal-accent underline">
          Back to list
        </Link>
      </main>
    );
  }

  if (!report) return null;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-auto p-4 font-mono text-sm text-terminal-text">
      <div>
        <Link to="/reports" className="mb-2 inline-block text-xs text-terminal-muted hover:text-terminal-accent">
          ← Back to list
        </Link>
        <div className="flex items-center justify-between">
          <div>
            <span className="font-semibold">{report.name}</span>
            <span className="ml-2 text-xs text-terminal-muted">
              {report.segment} · {report.risk_profile} · {report.advisor}
            </span>
          </div>
          {report.totals && (
            <span className="text-xs text-terminal-accent">
              ${report.totals.market_value.toFixed(2)} ({report.totals.unrealized_pnl_pct.toFixed(1)}%)
              {report.unpriced_tickers.length > 0 && (
                <span className="ml-1 text-terminal-muted">(excl. {report.unpriced_tickers.join(", ")})</span>
              )}
            </span>
          )}
        </div>
      </div>

      {report.positions.length > 0 && (
        <PortfolioPieChart
          display={{ type: "portfolio_chart", slices: report.positions.map((p) => ({ ticker: p.ticker, weight_pct: p.weight_pct })) }}
        />
      )}

      <SectorAllocationChart sectorAllocation={report.sector_allocation} />

      {Object.entries(report.price_history).map(([ticker, points]) => (
        <PriceChart key={ticker} display={{ type: "price_chart", ticker, points }} />
      ))}

      {report.concentration && (
        <ConcentrationAlert
          display={{ type: "concentration_alert", threshold_pct: report.concentration.threshold_pct, breaches: report.concentration.breaches }}
        />
      )}

      {report.totals ? (
        <PortfolioTable display={{ type: "portfolio_table", positions: report.positions, totals: report.totals }} />
      ) : (
        <div className="text-xs text-terminal-muted">No position.</div>
      )}

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-terminal-muted">Generated reports</span>
          <button
            type="button"
            onClick={onGenerate}
            disabled={generating}
            className="rounded-xl bg-terminal-accent px-3 py-1.5 font-mono text-xs font-semibold text-terminal-bg transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {generating ? "Generating…" : "Generate report"}
          </button>
        </div>
        {generateError && <div className="text-xs text-terminal-danger">{generateError}</div>}
        {report.generated_reports.map((f) => (
          <ReportFileCard key={f.filename} display={{ type: "report_file", filename: f.filename, url: f.download_url }} />
        ))}
      </div>
    </div>
  );
}

export function ReportWorkspace() {
  const { id } = useParams<{ id: string }>();
  return <ReportWorkspaceBody key={id} clientId={Number(id)} />;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/reports/ReportWorkspace.test.tsx`
Expected: PASS, all 6 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/reports/ReportWorkspace.tsx frontend/src/reports/ReportWorkspace.test.tsx
git commit -m "feat(reports): add ReportWorkspace dashboard"
```

---

### Task 9: Wire `/reports` routes, full regression

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `ReportsPage` (Task 6), `ReportWorkspace` (Task 8).
- Produces: nothing further downstream — this is the final integration task.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/App.test.tsx`, add the `ReportWorkspace` mock next to the existing
`ClientWorkspace` mock:

```typescript
vi.mock("./reports/ReportWorkspace", () => ({
  ReportWorkspace: () => <div data-testid="report-workspace" />,
}));
```

Replace the `"the two not-yet-built sections render ComingSoonPage without crashing"`
test (only `/briefing` is still a stub) and add routing assertions for `/reports`:

```typescript
  it("the one not-yet-built section renders ComingSoonPage without crashing", () => {
    renderAt("/briefing");
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });

  it("/reports renders the report client list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/data/clients") {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => ({ status: "ok", version: "1.2.3" }) });
      }),
    );
    renderAt("/reports");
    expect(screen.queryByTestId("report-workspace")).not.toBeInTheDocument();
  });

  it("/reports/:id renders the report workspace", () => {
    renderAt("/reports/12");
    expect(screen.getByTestId("report-workspace")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL — `/reports` and `/reports/:id` still render the `ComingSoonPage`
stub, not `ReportsPage`/`ReportWorkspace`; `report-workspace` testid never appears.

- [ ] **Step 3: Implement**

In `frontend/src/App.tsx`:

```typescript
import { ReportsPage } from "./reports/ReportsPage";
import { ReportWorkspace } from "./reports/ReportWorkspace";
```

Replace the `/reports` `ComingSoonPage` route:

```typescript
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/reports/:id" element={<ReportWorkspace />} />
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS, all tests.

- [ ] **Step 5: Run the full frontend and backend suites**

Run: `cd frontend && npx vitest run`
Expected: PASS, all tests (140 existing + every test added in Tasks 5-9).

Run: `uv run pytest tests/ -q`
Expected: PASS, all tests (435 existing + every test added in Tasks 1, 3, 4).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(reports): wire /reports and /reports/:id to the real dashboard"
```

---

## Live QA (after all tasks, before finishing the branch)

Per the spec's Testing section — restart the backend first (it runs without
`--reload`):

1. Open a client with holdings from `/reports`; confirm pie chart, sector chart,
   price history, concentration alerts (if any), positions table all render with
   real numbers.
2. Click "Generate report"; confirm the new file appears in the list and downloads.
3. Hard-reload the browser at `/reports/12` directly (type the URL, not an in-app
   click) — confirm the SPA still loads, not a JSON 404. This is the specific
   check for the proxy-collision risk the spec's architecture avoided by design.
4. Open a client with zero holdings; confirm the dashboard renders "No position."
   without crashing.
5. Confirm `/clients` (chantier 2) still works unaffected (regression check on the
   shared `ClientsList` component).
