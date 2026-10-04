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
