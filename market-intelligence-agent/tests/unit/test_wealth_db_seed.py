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


def test_only_margaret_collins_breaches_30pct_non_etf_concentration(db):
    """Margaret Collins is the ONLY conservative client with a non-ETF
    position above 30% of her portfolio (at 2026 anchor prices), with margin:
    every other conservative client's largest non-ETF position stays well
    under 30%, so a single ticker's price would have to move implausibly far
    to create a second breach. Regression for I-1: non-unique fixture (Susan
    Grant/Christopher Lee/George Palmer used to also breach at live prices)."""
    sectors = {r["ticker"]: r["sector"] for r in db.execute("SELECT ticker, sector FROM companies")}
    conservative = db.execute("SELECT client_id, name FROM clients WHERE risk_profile = 'conservative'").fetchall()
    anchor = date(2026, 7, 1)
    breaching = []
    for row in conservative:
        holdings = db.execute(
            "SELECT ticker, shares FROM holdings WHERE client_id = ?", (row["client_id"],)
        ).fetchall()
        values = {h["ticker"]: h["shares"] * seed.price_at(h["ticker"], anchor) for h in holdings}
        total = sum(values.values())
        for ticker, mv in values.items():
            if sectors[ticker] != "ETF" and mv / total > 0.30:
                breaching.append(row["name"])
                break
    assert breaching == ["Margaret Collins"]


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
