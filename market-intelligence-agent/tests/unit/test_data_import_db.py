import sqlite3

import pytest

from app.data_import.db import (
    client_id_by_email,
    existing_client_emails,
    get_client_with_holdings,
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
