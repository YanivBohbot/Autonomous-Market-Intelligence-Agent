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
#  - client 2 (Margaret Collins, conservative) is >30% in NVDA -- the ONLY
#    conservative client with a non-ETF position above 30%, with margin: every
#    other conservative client's largest non-ETF position stays <=~21% of its
#    portfolio at the 2026 anchor prices, so it cannot cross 30% even under a
#    +/-25% move in any single ticker's price (see
#    tests/unit/test_wealth_db_seed.py::test_only_margaret_collins_breaches_30pct_non_etf_concentration)
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
    (7, "2022-05-16", "KO", "BUY", 110), (7, "2022-05-16", "JNJ", "BUY", 40),
    (7, "2023-04-10", "BND", "BUY", 250), (7, "2024-02-01", "BND", "BUY", 100),
    (7, "2025-09-15", "XOM", "BUY", 40),
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
    (16, "2023-02-06", "KO", "BUY", 60), (16, "2023-02-06", "XOM", "BUY", 35),
    (16, "2024-03-18", "BND", "BUY", 100), (16, "2024-05-01", "BND", "BUY", 150),
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
    (22, "2023-10-09", "BND", "BUY", 150), (22, "2023-10-09", "KO", "BUY", 55),
    (22, "2025-02-24", "JNJ", "BUY", 20), (22, "2025-06-01", "BND", "BUY", 50),
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
