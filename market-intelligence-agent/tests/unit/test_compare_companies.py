import asyncio

from app.agent.tools.compare_companies import compare_companies, parse_closes

INFO = {
    "NVDA": {"shortName": "NVIDIA Corporation", "sector": "Technology", "currency": "USD", "currentPrice": 200.0,
             "marketCap": 4.9e12, "trailingPE": 50.0, "forwardPE": 30.0, "fiftyTwoWeekLow": 100.0, "fiftyTwoWeekHigh": 300.0},
    "AMD": {"shortName": "Advanced Micro Devices, Inc.", "sector": "Technology", "currency": "USD", "regularMarketPrice": 150.0,
            "marketCap": 2.4e11, "trailingPE": None, "forwardPE": 25.0, "fiftyTwoWeekLow": 150.0, "fiftyTwoWeekHigh": 150.0},
}
CLOSES = {
    "NVDA": [("2026-04-01", 100.0), ("2026-07-01", 150.0), ("2026-10-01", 200.0)],
    "AMD": [("2026-04-01", 120.0), ("2026-10-01", 150.0)],
}


async def _info(symbol):
    if symbol not in INFO:
        raise ValueError("no data")
    return INFO[symbol]


async def _closes(symbol, period):
    if symbol not in CLOSES:
        raise ValueError("no data")
    return CLOSES[symbol]


def _run(symbols):
    return asyncio.run(compare_companies(symbols=symbols, period="6mo", get_info=_info, get_closes=_closes))


def test_metrics_and_rebased_series():
    out = _run([" nvda ", "AMD"])
    nvda, amd = out["companies"]
    assert nvda["symbol"] == "NVDA" and amd["symbol"] == "AMD"
    assert nvda["period_return_pct"] == 100.0
    assert nvda["points"] == [{"date": "2026-04-01", "value": 100.0}, {"date": "2026-07-01", "value": 150.0},
                              {"date": "2026-10-01", "value": 200.0}]
    assert nvda["range_position_pct"] == 50.0
    assert amd["price"] == 150.0
    assert amd["range_position_pct"] is None  # flat 52-week range: undefined, not a crash
    assert amd["trailing_pe"] is None
    assert out["missing"] == [] and out["period"] == "6mo"


def test_duplicate_symbols_collapse():
    assert [c["symbol"] for c in _run(["NVDA", "nvda", "AMD"])["companies"]] == ["NVDA", "AMD"]


def test_unknown_symbol_is_reported_missing():
    out = _run(["NVDA", "AMD", "ZZZZ"])
    assert out["missing"] == ["ZZZZ"]
    assert len(out["companies"]) == 2


def test_fewer_than_two_valid_is_an_error():
    assert "error" in _run(["NVDA", "ZZZZ"])


def test_more_than_four_is_an_error():
    assert "error" in _run(["A", "B", "C", "D", "E"])


def test_parse_closes_markdown_table_from_yfmcp():
    text = (
        "| Date | Open | High | Low | Close | Volume |\n"
        "|:--|--:|--:|--:|--:|--:|\n"
        "| 2026-09-14 00:00:00-04:00 | 1 | 2 | 0.5 | 493.41 | 10 |\n"
        "| 2026-09-15 00:00:00-04:00 | 1 | 2 | 0.5 | 504.2 | 10 |\n"
    )
    assert parse_closes([{"type": "text", "text": text}]) == [("2026-09-14", 493.41), ("2026-09-15", 504.2)]


def test_parse_closes_gateway_rows():
    rows = {"ok": True, "result": [{"date": "2026-09-14T00:00:00-04:00", "close": 493.41}]}
    assert parse_closes(rows) == [("2026-09-14", 493.41)]
