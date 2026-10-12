"""load_client_context derives which client is active straight from the
thread id (clients_<id>) rather than from a frontend-pushed context -- see
docs/superpowers/specs/2026-10-04-clients-workspace-design.md decision 4.
Runs every turn (not just the first) so edits via /data/import mid-
conversation show up immediately; it is never cached onto the checkpoint.
"""
import sqlite3

import app.agent.orchestration.graph as graph_module
from app.agent.orchestration.graph import load_client_context


def _seed(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE clients (
            client_id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            segment TEXT NOT NULL, risk_profile TEXT NOT NULL, advisor TEXT NOT NULL,
            city TEXT NOT NULL, joined_on DATE NOT NULL
        );
        CREATE TABLE companies (ticker TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL);
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

    assert result == {"client_context": "Active client: Jane Doe, segment VIP, risk balanced, advisor Sam."}


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
