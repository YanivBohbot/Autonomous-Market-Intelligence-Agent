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
