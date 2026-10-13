import asyncio

from app.agent.tools.watchlist_alerts import build_watchlist_query, classify, watchlist_alerts

ROWS = [
    {"client": "Ann", "ticker": "TSLA", "company": "Tesla", "alert_price": 450.0, "direction": "above"},
    {"client": "Bob", "ticker": "NVDA", "company": "NVIDIA", "alert_price": 200.0, "direction": "below"},
    {"client": "Cid", "ticker": "AAPL", "company": "Apple", "alert_price": 300.0, "direction": "above"},
    {"client": "Dee", "ticker": "XXXX", "company": "Gone", "alert_price": 10.0, "direction": "below"},
]
PRICES = {"TSLA": 460.0, "NVDA": 205.0, "AAPL": 250.0}


async def run_sql(sql):
    return ROWS


async def get_price(t):
    if t not in PRICES:
        raise ValueError("no quote")
    return PRICES[t]


def test_classify_above_and_below():
    assert classify(460, 450, "above", 5) == ("triggered", 2.22)
    assert classify(440, 450, "above", 5) == ("near", -2.22)
    assert classify(300, 450, "above", 5) == ("watching", -33.33)
    assert classify(190, 200, "below", 5) == ("triggered", -5.0)
    assert classify(205, 200, "below", 5) == ("near", 2.5)


def test_rows_sorted_triggered_near_watching_and_unpriced_reported():
    out = asyncio.run(watchlist_alerts(run_sql=run_sql, get_price=get_price))
    assert [(r["client"], r["status"]) for r in out["rows"]] == [("Ann", "triggered"), ("Bob", "near"), ("Cid", "watching")]
    assert out["unpriced"] == ["XXXX"]
    assert out["near_pct"] == 5.0


def test_no_rows_is_empty_not_error():
    async def none(sql):
        return []
    out = asyncio.run(watchlist_alerts(run_sql=none, get_price=get_price, client_names=["Nobody"]))
    assert out["rows"] == [] and out["unpriced"] == []


def test_query_filters_names_and_escapes_quotes():
    sql = build_watchlist_query(["O'Neil"])
    assert "LIKE '%O''Neil%'" in sql and "FROM watchlists" in sql
    assert "WHERE" not in build_watchlist_query(None)
