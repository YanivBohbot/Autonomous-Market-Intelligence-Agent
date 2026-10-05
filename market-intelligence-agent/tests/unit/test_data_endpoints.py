import asyncio
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

    # Every report test gets a fast, deterministic narrative by default --
    # tests that care about the real wiring (test_price_history_... style)
    # override this themselves. Without this, every GET .../report test
    # would attempt a real OpenAI call.
    async def fake_narrative(report):
        return "stub narrative"

    monkeypatch.setattr(data_router_module, "_generate_narrative", fake_narrative)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_get_clients_lists_the_seeded_client(client):
    resp = client.get("/data/clients")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["email"] == "jane@x.com"
    assert body[0]["holdings"] == []


def test_get_client_summary_computes_totals_from_a_mocked_price(client, monkeypatch):
    conn = sqlite3.connect(data_router_module.DB_PATH)
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


PRICE_HISTORY_TEXT = (
    "| Date                      |   Open |   High |    Low |   Close |      Volume |\n"
    "|:--------------------------|-------:|-------:|-------:|--------:|------------:|\n"
    "| 2026-09-21 00:00:00-04:00 | 335.28 | 339.64 | 333.05 |  338.98 | 3.49992e+07 |\n"
)


def test_price_history_parses_the_real_mcp_content_block_shape(monkeypatch):
    # Regression (final review finding 4): every report test replaces
    # _price_history with a fake, so this function's own body --
    # _tool_content_text's block-joining, the symbol/ticker arg detection,
    # and the hand-off to normalize_price_history -- never actually ran.
    # yfinance_get_price_history's raw output is a markdown table (unlike
    # the quote tool's JSON), wrapped in local-stdio content blocks.
    import app.agent.tools.mcp_clients.yfinance_client as yf_client_module

    class FakeHistoryTool:
        args = {"symbol": {}, "period": {}}

        async def ainvoke(self, call_args):
            assert call_args == {"symbol": "AAPL", "period": "3mo"}
            return [{"type": "text", "text": PRICE_HISTORY_TEXT}]

    monkeypatch.setattr(yf_client_module, "yf_history_tool", FakeHistoryTool())

    result = asyncio.run(data_router_module._price_history("AAPL"))
    assert result == [{"date": "2026-09-21", "close": 338.98}]


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
    assert body["narrative"] == "stub narrative"


def test_get_client_report_calls_the_real_narrative_generator_with_the_full_response(client, monkeypatch, reports_dir):
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.commit()
    conn.close()

    async def fake_price(ticker):
        return 200.0

    captured = {}

    async def fake_generate(report):
        captured["report"] = report
        return "a real analysis paragraph"

    async def no_history(ticker):
        return []

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)
    monkeypatch.setattr(data_router_module, "_price_history", no_history)
    monkeypatch.setattr(data_router_module, "_generate_narrative", fake_generate)

    resp = client.get("/data/clients/1/report")
    assert resp.status_code == 200
    assert resp.json()["narrative"] == "a real analysis paragraph"
    assert captured["report"]["totals"]["market_value"] == 2000.0
    assert captured["report"]["name"] == "Jane Doe"


def test_get_client_report_with_no_holdings_skips_the_llm_call_via_the_real_narrative_function(client, monkeypatch, reports_dir):
    # Uses the REAL _generate_narrative (not the fixture's stub) to prove
    # the zero-holdings path never reaches the LLM end to end -- the skip
    # happens inside generate_portfolio_narrative itself (unit-tested in
    # test_portfolio_narrative.py), this just confirms data.py wires the
    # real function through rather than always using a canned string.
    from app.agent.tools.portfolio_narrative import generate_portfolio_narrative

    monkeypatch.setattr(data_router_module, "_generate_narrative", generate_portfolio_narrative)
    resp = client.get("/data/clients/1/report")
    assert resp.status_code == 200
    assert resp.json()["narrative"] == "No priced positions to analyze."


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

    async def no_history(ticker):
        return []

    monkeypatch.setattr(data_router_module, "_live_price", flaky_price)
    monkeypatch.setattr(data_router_module, "_price_history", no_history)

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

    async def no_history(ticker):
        return []

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)
    monkeypatch.setattr(data_router_module, "_price_history", no_history)

    resp = client.get("/data/clients/1/report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sector_allocation"] is None
    assert {p["ticker"] for p in body["positions"]} == {"AAPL", "GHOST"}
    assert body["unpriced_tickers"] == []


def test_get_client_report_runs_price_history_and_narrative_concurrently(client, monkeypatch, reports_dir):
    # Perf fix (live QA): both used to run sequentially after each other.
    # If they're genuinely concurrent, two 0.2s-sleeping fakes together
    # take ~0.2s, not ~0.4s.
    import time

    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.commit()
    conn.close()

    async def fake_price(ticker):
        return 200.0

    async def slow_history(ticker):
        await asyncio.sleep(0.2)
        return []

    async def slow_narrative(report):
        await asyncio.sleep(0.2)
        return "narrative"

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)
    monkeypatch.setattr(data_router_module, "_price_history", slow_history)
    monkeypatch.setattr(data_router_module, "_generate_narrative", slow_narrative)

    start = time.monotonic()
    resp = client.get("/data/clients/1/report")
    elapsed = time.monotonic() - start

    assert resp.status_code == 200
    assert elapsed < 0.35


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


def test_generate_client_report_passes_sector_so_etfs_are_not_flagged(client, monkeypatch, reports_dir):
    # Regression (final review finding 1): the Position built here had no
    # sector, so build_portfolio_report_xlsx's own ETF exclusion
    # (sector != "ETF") never matched, and a >30% ETF position got written
    # into the file's "Concentration note" -- disagreeing with the
    # dashboard's own (sector-aware) ConcentrationAlert for the same client.
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute("INSERT INTO companies VALUES ('BND', 'Vanguard Bond ETF', 'ETF')")
    conn.execute("INSERT INTO holdings VALUES (1, 'BND', 100, 70.0)")
    conn.commit()
    conn.close()

    async def fake_price(ticker):
        return 70.0

    captured = {}

    def fake_build(portfolio, **kwargs):
        captured["portfolio"] = portfolio
        return b"PK fake"

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)
    monkeypatch.setattr(data_router_module, "build_portfolio_report_xlsx", fake_build)

    resp = client.post("/data/clients/1/report/generate")
    assert resp.status_code == 200
    assert captured["portfolio"]["positions"][0]["sector"] == "ETF"


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


def test_import_pdf_rejects_a_non_pdf_extension_even_with_a_valid_magic_number(client):
    resp = client.post(
        "/data/import/pdf",
        files={"file": ("report.exe", io.BytesIO(b"%PDF-1.4 fake"), "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_import_pdf_sanitizes_a_path_like_filename(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.api.routers.data.ingest_single_pdf",
        lambda file_bytes, filename: calls.append(filename) or 1,
    )
    resp = client.post(
        "/data/import/pdf",
        files={"file": ("../../etc/passwd.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["filename"] == "passwd.pdf"
    assert calls == ["passwd.pdf"]


def test_import_pdf_returns_500_when_ingestion_itself_fails(client, monkeypatch):
    def _boom(file_bytes, filename):
        raise RuntimeError("Pinecone is down")

    monkeypatch.setattr("app.api.routers.data.ingest_single_pdf", _boom)
    resp = client.post(
        "/data/import/pdf",
        files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert resp.status_code == 500
