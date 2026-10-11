"""_live_price caches each ticker's quote for a short TTL -- live QA found
a single yfinance MCP call taking ~5-6s, and the summary/report endpoints
each fetch the same tickers independently (clicking a client then "View
full report" moments later re-fetched every ticker from scratch). The
underlying yfinance latency is out of this app's control, but re-fetching
a price that was just fetched seconds ago is not."""

import asyncio
import time

import pytest

from app.api.routers import data as data_router_module


@pytest.fixture(autouse=True)
def _clear_cache():
    data_router_module._price_cache.clear()
    yield
    data_router_module._price_cache.clear()


def test_second_call_for_the_same_ticker_within_the_ttl_skips_the_real_fetch(monkeypatch):
    calls = []

    async def fake_fetch(ticker):
        calls.append(ticker)
        return 200.0

    monkeypatch.setattr(data_router_module, "_fetch_live_price", fake_fetch)

    first = asyncio.run(data_router_module._live_price("AAPL"))
    second = asyncio.run(data_router_module._live_price("AAPL"))

    assert first == 200.0
    assert second == 200.0
    assert calls == ["AAPL"]


def test_a_different_ticker_is_fetched_independently(monkeypatch):
    calls = []

    async def fake_fetch(ticker):
        calls.append(ticker)
        return {"AAPL": 200.0, "NVDA": 2000.0}[ticker]

    monkeypatch.setattr(data_router_module, "_fetch_live_price", fake_fetch)

    asyncio.run(data_router_module._live_price("AAPL"))
    asyncio.run(data_router_module._live_price("NVDA"))

    assert calls == ["AAPL", "NVDA"]


def test_an_expired_cache_entry_is_refetched(monkeypatch):
    calls = []

    async def fake_fetch(ticker):
        calls.append(ticker)
        return 200.0

    monkeypatch.setattr(data_router_module, "_fetch_live_price", fake_fetch)
    monkeypatch.setattr(data_router_module, "_PRICE_CACHE_TTL_S", 0.05)

    asyncio.run(data_router_module._live_price("AAPL"))
    time.sleep(0.1)
    asyncio.run(data_router_module._live_price("AAPL"))

    assert calls == ["AAPL", "AAPL"]
