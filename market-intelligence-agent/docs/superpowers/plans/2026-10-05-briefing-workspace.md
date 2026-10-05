# Briefing Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `/briefing` `ComingSoonPage` stub with a market dashboard: US indices, sector performance, a 6-ticker megacap watchlist with sparklines, a macro/micro market narrative, news, and cabinet-wide concentration alerts.

**Architecture:** One new backend endpoint (`GET /data/briefing`) on the existing `/data` router (no new router — avoids the Vite-proxy-prefix collision chantier 3 already worked around), backed by a new direct-LLM narrative module (`market_narrative.py`, parallel to `portfolio_narrative.py`) and a handful of helper functions in `data.py` (quote snapshot + its own 10-minute cache, Tavily news fetch, a cabinet-wide concentration scan over the local sqlite3 connection). One new frontend page (`BriefingPage.tsx`) plus a small `Sparkline.tsx` component, wired into `App.tsx` in place of the last `ComingSoonPage` usage.

**Tech Stack:** FastAPI, yfinance MCP (`yf_quote_tool`, reused `_price_history`), Tavily (direct `TavilyClient`, not `web_search_tool`), `ChatOpenAI` (direct, no agent loop), React, Recharts.

**Spec:** `docs/superpowers/specs/2026-10-05-briefing-design.md` (approved, committed through `6d332e6`)

## Global Constraints

- No new backend router. The endpoint is `GET /data/briefing` on the existing `/data` router in `app/api/routers/data.py`.
- `/briefing` must NOT be added to `frontend/vite.config.ts`'s proxy list (it already proxies the whole `/data` prefix).
- Client alerts query the local sqlite3 connection directly (`conn.execute(build_holdings_query(...))`), never the MCP CRM tool. `screen_clients` (which routes through MCP) must not be called from `data.py`.
- News uses a direct `TavilyClient.search(...)` call, not `web_search_tool` (whose output is a single pre-formatted string for an LLM, not structured `{title, url}` entries).
- `TavilyClient.search` is **synchronous** — any call to it must be wrapped in `asyncio.to_thread`, or it blocks the event loop for every other request this process is serving.
- Briefing's own index/sector/watchlist quote cache uses a 600-second TTL (user: "ca peut etre meme au dela 10 min"), separate from the existing 30-second `_price_cache` used by Reports/Clients/the cabinet scan — these are different value shapes ({symbol, name, price, change_pct} vs a bare float) and different freshness needs.
- The narrative section heading must read exactly **"Résumé du marché macro-économique et micro-économique"** (user's explicit phrasing — not a generic "Market summary").
- Every list in the response (indices, sectors, watchlist, news) degrades per-item on failure — one bad ticker/call never 500s the whole page. `client_alerts.available` is `false` only when the holdings query itself fails or zero clients end up with any priced holding.
- The watchlist is the fixed 6 megacaps: `AAPL`, `NVDA`, `MSFT`, `GOOGL`, `AMZN`, `META`. Sparklines render on watchlist cards only (not indices, not sectors — explicit user decision).
- Sector performance is 8 GICS-sector ETF proxies (`XLK`, `XLF`, `XLV`, `XLE`, `XLY`, `XLP`, `XLI`, `XLC`) via the existing reliable quote tool — `yfinance_get_top` is confirmed broken (15/15 real calls returned HTTP 404 from Yahoo's own backend) and must not be used.

## Review Focus

- **Two clients sharing the exact same name** in the cabinet-wide concentration scan: `compute_concentration_screen` raises `ValueError` on a duplicate `LabeledPortfolio.label` — a reasonable advisor expects the alerts section to just omit or dedupe, not crash the whole Briefing page. Pinned in Task 4's tests.
- **A client whose only holding is an ETF** reaching the cabinet scan: chantier 3 shipped this exact false positive once already (final review finding 1 — ETF sector missing on the single-client report path caused a >30% ETF position to be wrongly flagged). `compute_concentration_screen`'s default `exclude_sectors=["ETF"]` only works if `sector` is actually passed through — this is a fresh code path (the cabinet-wide scan) reusing that same function, and nothing yet proves it inherited the fix rather than the bug. Pinned in Task 4's tests.
- **All three of indices/sectors/watchlist quotes failing at once**: a reasonable person expects an empty dashboard, not a 500 — and the narrative must still render its own "unavailable" fallback rather than erroring on an empty `market` dict. Pinned in Task 5's tests.
- **The watchlist quote succeeding but that ticker's 90-day history failing**: the user still wants to see the price/name/%, just without a sparkline — not have the whole watchlist card disappear. Pinned in Task 5's tests.
- **The Tavily news call raising** (network/quota error): the rest of the Briefing page (which has nothing to do with news) must still render — this is explicitly required by the Global Constraints but easy to lose if `_fetch_market_news` is called inside the same `return_exceptions=False` gather as other work. Pinned in Task 3 and Task 5's tests.

---

## Task 1: Market narrative generator

**Files:**
- Create: `app/agent/tools/market_narrative.py`
- Test: `tests/unit/test_market_narrative.py`

**Interfaces:**
- Produces: `async def generate_market_narrative(market: dict) -> str` where `market = {"indices": [{"name": str, "price": float, "change_pct": float}, ...], "sectors": [{"name": str, "change_pct": float}, ...]}`. Returns the fixed string `"Market data unavailable right now."` without calling the LLM when both `market["indices"]` and `market["sectors"]` are empty lists.

- [ ] **Step 1: Write the failing tests**

```python
"""generate_market_narrative -- same lightweight, direct-ChatOpenAI pattern
as portfolio_narrative.py (no tool-calling loop, no agent graph), grounded
only in index/sector quotes the Briefing endpoint already computed."""

import asyncio
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from app.agent.tools import market_narrative as narrative_mod
from app.agent.tools.market_narrative import generate_market_narrative

_MARKET = {
    "indices": [
        {"name": "S&P 500", "price": 5800.0, "change_pct": 0.73},
        {"name": "VIX", "price": 14.2, "change_pct": -3.1},
    ],
    "sectors": [
        {"name": "Technology", "change_pct": 1.2},
        {"name": "Energy", "change_pct": -0.8},
    ],
}


def test_generate_market_narrative_grounds_the_prompt_in_computed_numbers():
    with patch.object(narrative_mod, "_llm") as mock:
        mock.ainvoke = AsyncMock(return_value=AIMessage(content="Markets edged higher today..."))
        result = asyncio.run(generate_market_narrative(_MARKET))

    prompt_messages = mock.ainvoke.call_args[0][0]
    prompt_text = " ".join(m.content for m in prompt_messages)
    assert "S&P 500" in prompt_text
    assert "5800" in prompt_text
    assert "0.73" in prompt_text
    assert "Technology" in prompt_text
    assert "1.2" in prompt_text
    assert result == "Markets edged higher today..."


def test_generate_market_narrative_skips_the_llm_call_with_no_data():
    empty_market = {"indices": [], "sectors": []}
    with patch.object(narrative_mod, "_llm") as mock:
        result = asyncio.run(generate_market_narrative(empty_market))

    mock.ainvoke.assert_not_called()
    assert result == "Market data unavailable right now."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_market_narrative.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agent.tools.market_narrative'`

- [ ] **Step 3: Write the implementation**

```python
"""generate_market_narrative -- same lightweight direct-ChatOpenAI pattern
as portfolio_narrative.py, grounded only in index/sector quotes the
Briefing endpoint already computed. Kept as its own file rather than
generalizing portfolio_narrative.py: each stays focused on one grounding
shape (one client's portfolio vs. the whole market)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings

_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0.3)

_SYSTEM_PROMPT = (
    "You are a financial analyst writing a short market summary for an "
    "advisor's daily briefing dashboard. You are given index and sector "
    "numbers that have already been computed exactly -- never recalculate "
    "or restate them differently than given. Write 2-3 short paragraphs "
    "covering both macro movement (overall index levels, what VIX implies "
    "about market fear/complacency) and micro movement (which sectors "
    "moved and by how much, and what that dispersion suggests). Do not "
    "invent numbers, companies, or events not in the data below."
)


def _format_market_for_prompt(market: dict) -> str:
    lines = ["Indices:"]
    for idx in market["indices"]:
        lines.append(f"  - {idx['name']}: {idx['price']} ({idx['change_pct']}%)")
    lines.append("Sectors:")
    for sec in market["sectors"]:
        lines.append(f"  - {sec['name']}: {sec['change_pct']}%")
    return "\n".join(lines)


async def generate_market_narrative(market: dict) -> str:
    if not market.get("indices") and not market.get("sectors"):
        return "Market data unavailable right now."
    prompt = _format_market_for_prompt(market)
    response = await _llm.ainvoke([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)])
    return response.content
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_market_narrative.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools/market_narrative.py tests/unit/test_market_narrative.py
git commit -m "feat(briefing): add generate_market_narrative

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjgaMZZ37PufvHKBSTqrWF"
```

---

## Task 2: Quote snapshot helpers + curated ticker lists

**Files:**
- Modify: `app/api/routers/data.py` (add imports, constants, and two new functions near the existing `_live_price` block, around line 107)
- Test: `tests/unit/test_data_endpoints.py` (add tests to the existing file)

**Interfaces:**
- Consumes: `parse_tool_payload`, `price_from_quote` (already imported in `data.py` from `app.agent.tools.concentration`); `yf_quote_tool` from `app.agent.tools.mcp_clients.yfinance_client` (deferred import, same convention as `_fetch_live_price`).
- Produces:
  - `_INDEX_TICKERS: list[tuple[str, str]]`, `_SECTOR_ETFS: list[tuple[str, str]]`, `_WATCHLIST_TICKERS: list[str]` (module-level constants).
  - `_change_pct_from_quote(info: dict) -> float`
  - `async def _quote_snapshot(symbol: str, *, name: str | None = None) -> dict` returning `{"symbol": str, "name": str, "price": float, "change_pct": float}`.
  - `_quote_cache: dict[str, tuple[dict, float]]`, `_BRIEFING_CACHE_TTL_S: float = 600.0`
  - `async def _cached_quote_snapshot(symbol: str, *, name: str | None = None) -> dict` — same return shape as `_quote_snapshot`, cached for `_BRIEFING_CACHE_TTL_S` seconds per symbol.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_data_endpoints.py`:

```python
def test_quote_snapshot_builds_symbol_name_price_change_pct(monkeypatch):
    async def fake_tool(args):
        assert args == {"symbol": "AAPL"}
        return [{"type": "text", "text": '{"currentPrice": 258.0, "shortName": "Apple Inc.", "regularMarketChangePercent": 0.73}'}]

    class FakeQuoteTool:
        args = {"symbol": {}}
        ainvoke = staticmethod(fake_tool)

    import app.agent.tools.mcp_clients.yfinance_client as yf_client_module
    monkeypatch.setattr(yf_client_module, "yf_quote_tool", FakeQuoteTool())

    result = asyncio.run(data_router_module._quote_snapshot("AAPL"))
    assert result == {"symbol": "AAPL", "name": "Apple Inc.", "price": 258.0, "change_pct": 0.73}


def test_quote_snapshot_uses_the_given_name_override(monkeypatch):
    async def fake_tool(args):
        return [{"type": "text", "text": '{"currentPrice": 5800.0, "shortName": "ignored", "regularMarketChangePercent": 0.1}'}]

    class FakeQuoteTool:
        args = {"symbol": {}}
        ainvoke = staticmethod(fake_tool)

    import app.agent.tools.mcp_clients.yfinance_client as yf_client_module
    monkeypatch.setattr(yf_client_module, "yf_quote_tool", FakeQuoteTool())

    result = asyncio.run(data_router_module._quote_snapshot("^GSPC", name="S&P 500"))
    assert result["name"] == "S&P 500"


def test_quote_snapshot_falls_back_to_fulldaychangepercent(monkeypatch):
    async def fake_tool(args):
        return [{"type": "text", "text": '{"currentPrice": 100.0, "shortName": "X", "fulldayChangePercent": -1.5}'}]

    class FakeQuoteTool:
        args = {"symbol": {}}
        ainvoke = staticmethod(fake_tool)

    import app.agent.tools.mcp_clients.yfinance_client as yf_client_module
    monkeypatch.setattr(yf_client_module, "yf_quote_tool", FakeQuoteTool())

    result = asyncio.run(data_router_module._quote_snapshot("X"))
    assert result["change_pct"] == -1.5


def test_cached_quote_snapshot_reuses_the_cached_value_within_the_600s_ttl(monkeypatch):
    data_router_module._quote_cache.clear()
    calls = []

    async def fake_snapshot(symbol, *, name=None):
        calls.append(symbol)
        return {"symbol": symbol, "name": name or symbol, "price": 1.0, "change_pct": 0.0}

    monkeypatch.setattr(data_router_module, "_quote_snapshot", fake_snapshot)

    asyncio.run(data_router_module._cached_quote_snapshot("AAPL"))
    asyncio.run(data_router_module._cached_quote_snapshot("AAPL"))

    assert calls == ["AAPL"]
    data_router_module._quote_cache.clear()


def test_cached_quote_snapshot_expires_after_its_own_longer_ttl(monkeypatch):
    # Regression: Briefing's quote cache must use its own 600s constant,
    # not accidentally share Reports/Clients' 30s _PRICE_CACHE_TTL_S.
    import time

    data_router_module._quote_cache.clear()
    calls = []

    async def fake_snapshot(symbol, *, name=None):
        calls.append(symbol)
        return {"symbol": symbol, "name": name or symbol, "price": 1.0, "change_pct": 0.0}

    monkeypatch.setattr(data_router_module, "_quote_snapshot", fake_snapshot)
    monkeypatch.setattr(data_router_module, "_BRIEFING_CACHE_TTL_S", 0.05)

    asyncio.run(data_router_module._cached_quote_snapshot("AAPL"))
    time.sleep(0.1)
    asyncio.run(data_router_module._cached_quote_snapshot("AAPL"))

    assert calls == ["AAPL", "AAPL"]
    data_router_module._quote_cache.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k quote_snapshot -v`
Expected: FAIL with `AttributeError: module 'app.api.routers.data' has no attribute '_quote_snapshot'`

- [ ] **Step 3: Write the implementation**

In `app/api/routers/data.py`, change the import on line 18 from:

```python
from app.agent.tools.concentration import parse_tool_payload, price_from_quote
```

to:

```python
from app.agent.tools.concentration import build_holdings_query, parse_tool_payload, price_from_quote
```

Then add, directly after the existing `_live_price` function (after line 106):

```python
_INDEX_TICKERS = [("S&P 500", "^GSPC"), ("Dow Jones", "^DJI"), ("Nasdaq", "^IXIC"), ("VIX", "^VIX")]
_SECTOR_ETFS = [
    ("Technology", "XLK"), ("Financial Services", "XLF"), ("Healthcare", "XLV"),
    ("Energy", "XLE"), ("Consumer Cyclical", "XLY"), ("Consumer Defensive", "XLP"),
    ("Industrials", "XLI"), ("Communication Services", "XLC"),
]
_WATCHLIST_TICKERS = ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META"]


def _change_pct_from_quote(info: dict) -> float:
    for key in ("regularMarketChangePercent", "fulldayChangePercent"):
        value = info.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    raise ValueError("no change percent in quote")


async def _quote_snapshot(symbol: str, *, name: str | None = None) -> dict:
    from app.agent.tools.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"
    info = parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: symbol}))
    return {
        "symbol": symbol,
        "name": name or info.get("shortName") or info.get("longName") or symbol,
        "price": price_from_quote(info),
        "change_pct": _change_pct_from_quote(info),
    }


# Briefing is a "daily summary", not a live ticker -- 600s, not the 30s
# Reports/Clients use. Separate cache from _price_cache: this stores a
# full snapshot dict (symbol/name/price/change_pct), not a bare float.
_quote_cache: dict[str, tuple[dict, float]] = {}
_BRIEFING_CACHE_TTL_S = 600.0


async def _cached_quote_snapshot(symbol: str, *, name: str | None = None) -> dict:
    now = time.monotonic()
    cached = _quote_cache.get(symbol)
    if cached is not None and now - cached[1] < _BRIEFING_CACHE_TTL_S:
        return cached[0]
    snapshot = await _quote_snapshot(symbol, name=name)
    _quote_cache[symbol] = (snapshot, now)
    return snapshot
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k quote_snapshot -v`
Expected: PASS (5/5)

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/data.py tests/unit/test_data_endpoints.py
git commit -m "feat(briefing): add quote snapshot helpers with a 600s cache

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjgaMZZ37PufvHKBSTqrWF"
```

---

## Task 3: Market news fetch (direct Tavily, no agent)

**Files:**
- Modify: `app/api/routers/data.py` (add one function, near `_generate_narrative` around line 128)
- Test: `tests/unit/test_data_endpoints.py`

**Interfaces:**
- Produces: `async def _fetch_market_news() -> list[dict]` where each item is `{"title": str, "url": str}`. Returns `[]` if the Tavily call raises (network/quota failure) — never propagates.

- [ ] **Step 1: Write the failing tests**

```python
def test_fetch_market_news_returns_title_and_url(monkeypatch):
    import app.api.routers.data as data_module

    class FakeTavilyClient:
        def __init__(self, api_key):
            pass

        def search(self, query, max_results, search_depth):
            assert query == "US stock market today"
            assert max_results == 5
            assert search_depth == "advanced"
            return {"results": [
                {"title": "Markets rally", "url": "https://example.com/a", "content": "ignored"},
                {"title": "Fed holds rates", "url": "https://example.com/b", "content": "ignored"},
            ]}

    monkeypatch.setattr("tavily.TavilyClient", FakeTavilyClient)
    result = asyncio.run(data_module._fetch_market_news())
    assert result == [
        {"title": "Markets rally", "url": "https://example.com/a"},
        {"title": "Fed holds rates", "url": "https://example.com/b"},
    ]


def test_fetch_market_news_returns_empty_list_when_tavily_raises(monkeypatch):
    import app.api.routers.data as data_module

    class FailingTavilyClient:
        def __init__(self, api_key):
            pass

        def search(self, query, max_results, search_depth):
            raise RuntimeError("Tavily is down")

    monkeypatch.setattr("tavily.TavilyClient", FailingTavilyClient)
    result = asyncio.run(data_module._fetch_market_news())
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k fetch_market_news -v`
Expected: FAIL with `AttributeError: module 'app.api.routers.data' has no attribute '_fetch_market_news'`

- [ ] **Step 3: Write the implementation**

Add to `app/api/routers/data.py`, after `_generate_narrative`:

```python
async def _fetch_market_news() -> list[dict]:
    # TavilyClient.search is SYNCHRONOUS -- must run in a thread or it
    # blocks the event loop for every other request this process serves.
    from tavily import TavilyClient

    try:
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = await asyncio.to_thread(
            client.search, query="US stock market today", max_results=5, search_depth="advanced",
        )
    except Exception:
        return []
    return [{"title": r.get("title", ""), "url": r["url"]} for r in response.get("results", [])]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k fetch_market_news -v`
Expected: PASS (2/2)

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/data.py tests/unit/test_data_endpoints.py
git commit -m "feat(briefing): add direct Tavily market news fetch

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjgaMZZ37PufvHKBSTqrWF"
```

---

## Task 4: Cabinet-wide concentration scan

**Files:**
- Modify: `app/api/routers/data.py` (add one function, after `_fetch_market_news`)
- Test: `tests/unit/test_data_endpoints.py`

**Interfaces:**
- Consumes: `build_holdings_query(risk_profile, client_names)` (imported in Task 2) returning rows shaped `(name: str, ticker: str, shares: float, avg_cost: float, sector: str | None)`; `_live_price(ticker) -> float` (existing, unchanged, 30s TTL); `Position`, `LabeledPortfolio`, `compute_concentration_screen` (already imported at the top of `data.py`).
- Produces: `async def _cabinet_concentration_scan() -> dict` returning `{"available": bool, "threshold_pct": float, "breaches": [{"label": str, "ticker": str, "weight_pct": float, "market_value": float}, ...]}`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_data_endpoints.py` (reuses the `client` fixture's seeded DB — add a second client with holdings per test):

```python
def test_cabinet_scan_flags_a_breach_across_two_clients(client, monkeypatch):
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute("INSERT INTO companies VALUES ('NVDA', 'NVIDIA', 'Technology')")
    conn.execute(
        "INSERT INTO clients VALUES (2, 'Bob Lee', 'bob@x.com', 'VIP', 'aggressive', 'Sam', 'Paris', '2024-01-01')"
    )
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")  # diversified, no breach alone
    conn.execute("INSERT INTO holdings VALUES (2, 'NVDA', 100, 30.0)")  # 100% in one stock
    conn.commit()
    conn.close()

    async def fake_price(ticker):
        return {"AAPL": 200.0, "NVDA": 2000.0}[ticker]

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)

    result = asyncio.run(data_router_module._cabinet_concentration_scan())
    assert result["available"] is True
    assert result["threshold_pct"] == 30.0
    assert any(b["label"] == "Bob Lee" and b["ticker"] == "NVDA" for b in result["breaches"])
    assert all(b["label"] != "Jane Doe" for b in result["breaches"])


def test_cabinet_scan_excludes_a_holding_whose_price_fetch_fails(client, monkeypatch):
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

    monkeypatch.setattr(data_router_module, "_live_price", flaky_price)

    result = asyncio.run(data_router_module._cabinet_concentration_scan())
    assert result["available"] is True  # one bad ticker never flips this to False


def test_cabinet_scan_unavailable_when_no_client_has_any_holding(client):
    result = asyncio.run(data_router_module._cabinet_concentration_scan())
    assert result == {"available": False, "threshold_pct": 30.0, "breaches": []}


def test_cabinet_scan_unavailable_when_the_query_itself_fails(client, monkeypatch):
    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("db is locked")

    monkeypatch.setattr(data_router_module.sqlite3, "connect", boom)
    result = asyncio.run(data_router_module._cabinet_concentration_scan())
    assert result == {"available": False, "threshold_pct": 30.0, "breaches": []}


def test_cabinet_scan_does_not_flag_a_client_whose_only_holding_is_an_etf(client, monkeypatch):
    # Regression (chantier 3 final review finding 1, reused here): a
    # 100%-ETF position must not be flagged, same as the single-client
    # report path already guarantees.
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute("INSERT INTO companies VALUES ('BND', 'Vanguard Bond ETF', 'ETF')")
    conn.execute("INSERT INTO holdings VALUES (1, 'BND', 100, 70.0)")
    conn.commit()
    conn.close()

    async def fake_price(ticker):
        return 70.0

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)

    result = asyncio.run(data_router_module._cabinet_concentration_scan())
    assert result["available"] is True
    assert result["breaches"] == []


def test_cabinet_scan_does_not_crash_on_two_clients_sharing_a_name(client, monkeypatch):
    # compute_concentration_screen raises ValueError on a duplicate label --
    # a reasonable advisor expects the alerts section to degrade, not 500
    # the whole Briefing page, over two same-named clients.
    conn = sqlite3.connect(data_router_module.DB_PATH)
    conn.execute(
        "INSERT INTO clients VALUES (2, 'Jane Doe', 'jane2@x.com', 'VIP', 'balanced', 'Sam', 'Paris', '2024-01-01')"
    )
    conn.execute("INSERT INTO holdings VALUES (1, 'AAPL', 10, 150.0)")
    conn.execute("INSERT INTO holdings VALUES (2, 'AAPL', 5, 100.0)")
    conn.commit()
    conn.close()

    async def fake_price(ticker):
        return 200.0

    monkeypatch.setattr(data_router_module, "_live_price", fake_price)

    result = asyncio.run(data_router_module._cabinet_concentration_scan())
    assert result == {"available": False, "threshold_pct": 30.0, "breaches": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k cabinet_scan -v`
Expected: FAIL with `AttributeError: module 'app.api.routers.data' has no attribute '_cabinet_concentration_scan'`

- [ ] **Step 3: Write the implementation**

Add to `app/api/routers/data.py`, after `_fetch_market_news`:

```python
async def _cabinet_concentration_scan() -> dict:
    unavailable = {"available": False, "threshold_pct": 30.0, "breaches": []}
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            rows = list(conn.execute(build_holdings_query(risk_profile=None, client_names=None)))
        finally:
            conn.close()
    except sqlite3.Error:
        return unavailable
    if not rows:
        return unavailable

    tickers = sorted({r[1] for r in rows})
    price_results = await asyncio.gather(*(_live_price(t) for t in tickers), return_exceptions=True)
    prices = {t: p for t, p in zip(tickers, price_results) if not isinstance(p, BaseException)}

    by_client: dict[str, list[Position]] = {}
    for name, ticker, shares, avg_cost, sector in rows:
        if ticker not in prices:
            continue
        by_client.setdefault(name, []).append(Position(
            ticker=ticker, shares=shares, avg_cost=avg_cost, price=prices[ticker], sector=sector,
        ))

    portfolios = [LabeledPortfolio(label=name, positions=pos) for name, pos in by_client.items() if pos]
    if not portfolios:
        return unavailable

    try:
        screen = compute_concentration_screen(portfolios, threshold_pct=30.0)
    except ValueError:
        # Duplicate client name, or another portfolio-shape issue
        # compute_concentration_screen rejects outright -- degrade rather
        # than 500 the whole Briefing page over it.
        return unavailable
    return {"available": True, "threshold_pct": screen["threshold_pct"], "breaches": screen["breaches"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k cabinet_scan -v`
Expected: PASS (6/6)

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/data.py tests/unit/test_data_endpoints.py
git commit -m "feat(briefing): add cabinet-wide concentration scan

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjgaMZZ37PufvHKBSTqrWF"
```

---

## Task 5: `GET /data/briefing` endpoint

**Files:**
- Modify: `app/api/routers/data.py` (add one new wrapper function + the route, after `_cabinet_concentration_scan`)
- Test: `tests/unit/test_data_endpoints.py`

**Interfaces:**
- Consumes: `_cached_quote_snapshot`, `_price_history` (existing, line 139), `_fetch_market_news`, `_cabinet_concentration_scan` (all from earlier tasks), plus a new `_generate_market_narrative` wrapper (same deferred-import convention as `_generate_narrative`).
- Produces: `GET /data/briefing` returning
  `{"indices": [...], "sectors": [...], "watchlist": [{"symbol", "name", "price", "change_pct", "points": [{"date", "close"}, ...]}, ...], "narrative": str, "news": [...], "client_alerts": {...}}`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_data_endpoints.py`:

```python
def _fake_quote(symbol, *, name=None):
    return {"symbol": symbol, "name": name or symbol, "price": 100.0, "change_pct": 1.0}


def test_get_briefing_happy_path_returns_all_sections(client, monkeypatch):
    async def fake_snapshot(symbol, *, name=None):
        return _fake_quote(symbol, name=name)

    async def fake_history(ticker):
        return [{"date": "2026-09-21", "close": 338.98}]

    async def fake_narrative(market):
        return "stub market narrative"

    async def fake_news():
        return [{"title": "Markets rally", "url": "https://example.com/a"}]

    async def fake_cabinet_scan():
        return {"available": True, "threshold_pct": 30.0, "breaches": []}

    monkeypatch.setattr(data_router_module, "_cached_quote_snapshot", fake_snapshot)
    monkeypatch.setattr(data_router_module, "_price_history", fake_history)
    monkeypatch.setattr(data_router_module, "_generate_market_narrative", fake_narrative)
    monkeypatch.setattr(data_router_module, "_fetch_market_news", fake_news)
    monkeypatch.setattr(data_router_module, "_cabinet_concentration_scan", fake_cabinet_scan)

    resp = client.get("/data/briefing")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["indices"]) == 4
    assert len(body["sectors"]) == 8
    assert len(body["watchlist"]) == 6
    assert all(w["points"] == [{"date": "2026-09-21", "close": 338.98}] for w in body["watchlist"])
    assert body["narrative"] == "stub market narrative"
    assert body["news"] == [{"title": "Markets rally", "url": "https://example.com/a"}]
    assert body["client_alerts"] == {"available": True, "threshold_pct": 30.0, "breaches": []}


def test_get_briefing_omits_one_failed_index_and_keeps_the_rest(client, monkeypatch):
    async def flaky_snapshot(symbol, *, name=None):
        if symbol == "^VIX":
            raise ValueError("yfinance is down")
        return _fake_quote(symbol, name=name)

    async def fake_history(ticker):
        return []

    monkeypatch.setattr(data_router_module, "_cached_quote_snapshot", flaky_snapshot)
    monkeypatch.setattr(data_router_module, "_price_history", fake_history)
    monkeypatch.setattr(data_router_module, "_generate_market_narrative", lambda market: _async_const("n"))
    monkeypatch.setattr(data_router_module, "_fetch_market_news", lambda: _async_const([]))
    monkeypatch.setattr(data_router_module, "_cabinet_concentration_scan", lambda: _async_const({"available": False, "threshold_pct": 30.0, "breaches": []}))

    resp = client.get("/data/briefing")
    assert resp.status_code == 200
    symbols = {i["symbol"] for i in resp.json()["indices"]}
    assert symbols == {"^GSPC", "^DJI", "^IXIC"}


def test_get_briefing_one_watchlist_history_failure_still_shows_its_quote(client, monkeypatch):
    async def fake_snapshot(symbol, *, name=None):
        return _fake_quote(symbol, name=name)

    async def flaky_history(ticker):
        if ticker == "NVDA":
            raise ValueError("history unavailable")
        return [{"date": "2026-09-21", "close": 1.0}]

    monkeypatch.setattr(data_router_module, "_cached_quote_snapshot", fake_snapshot)
    monkeypatch.setattr(data_router_module, "_price_history", flaky_history)
    monkeypatch.setattr(data_router_module, "_generate_market_narrative", lambda market: _async_const("n"))
    monkeypatch.setattr(data_router_module, "_fetch_market_news", lambda: _async_const([]))
    monkeypatch.setattr(data_router_module, "_cabinet_concentration_scan", lambda: _async_const({"available": False, "threshold_pct": 30.0, "breaches": []}))

    resp = client.get("/data/briefing")
    assert resp.status_code == 200
    watchlist = {w["symbol"]: w for w in resp.json()["watchlist"]}
    assert watchlist["NVDA"]["points"] == []
    assert watchlist["NVDA"]["price"] == 100.0  # quote itself still present


def test_get_briefing_all_quotes_failing_returns_empty_lists_not_a_500(client, monkeypatch):
    async def always_fails(symbol, *, name=None):
        raise ValueError("yfinance is down")

    monkeypatch.setattr(data_router_module, "_cached_quote_snapshot", always_fails)
    monkeypatch.setattr(data_router_module, "_generate_market_narrative", lambda market: _async_const("Market data unavailable right now."))
    monkeypatch.setattr(data_router_module, "_fetch_market_news", lambda: _async_const([]))
    monkeypatch.setattr(data_router_module, "_cabinet_concentration_scan", lambda: _async_const({"available": False, "threshold_pct": 30.0, "breaches": []}))

    resp = client.get("/data/briefing")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indices"] == [] and body["sectors"] == [] and body["watchlist"] == []
    assert body["narrative"] == "Market data unavailable right now."


def test_get_briefing_news_failure_does_not_affect_the_rest(client, monkeypatch):
    async def fake_snapshot(symbol, *, name=None):
        return _fake_quote(symbol, name=name)

    async def failing_news():
        return []  # _fetch_market_news already swallows its own errors (Task 3)

    monkeypatch.setattr(data_router_module, "_cached_quote_snapshot", fake_snapshot)
    monkeypatch.setattr(data_router_module, "_price_history", lambda ticker: _async_const([]))
    monkeypatch.setattr(data_router_module, "_generate_market_narrative", lambda market: _async_const("n"))
    monkeypatch.setattr(data_router_module, "_fetch_market_news", failing_news)
    monkeypatch.setattr(data_router_module, "_cabinet_concentration_scan", lambda: _async_const({"available": False, "threshold_pct": 30.0, "breaches": []}))

    resp = client.get("/data/briefing")
    assert resp.status_code == 200
    body = resp.json()
    assert body["news"] == []
    assert len(body["indices"]) == 4  # rest of the page unaffected
```

Add this small shared helper near the top of `tests/unit/test_data_endpoints.py` (used by the lambdas above, since `monkeypatch.setattr` needs a plain callable, not an `async def`, when the test passes `lambda ... : _async_const(...)`):

```python
async def _async_const(value):
    return value
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k get_briefing -v`
Expected: FAIL with `404` (route does not exist yet) or `AttributeError` on the monkeypatched names.

- [ ] **Step 3: Write the implementation**

Add to `app/api/routers/data.py`, after `_cabinet_concentration_scan`:

```python
async def _generate_market_narrative(market: dict) -> str:
    from app.agent.tools.market_narrative import generate_market_narrative

    return await generate_market_narrative(market)


@router.get("/briefing")
async def get_briefing() -> dict:
    index_results = await asyncio.gather(
        *(_cached_quote_snapshot(ticker, name=name) for name, ticker in _INDEX_TICKERS),
        return_exceptions=True,
    )
    indices = [r for r in index_results if not isinstance(r, BaseException)]

    sector_results = await asyncio.gather(
        *(_cached_quote_snapshot(ticker, name=name) for name, ticker in _SECTOR_ETFS),
        return_exceptions=True,
    )
    sectors = [r for r in sector_results if not isinstance(r, BaseException)]

    watchlist_results = await asyncio.gather(
        *(_cached_quote_snapshot(ticker) for ticker in _WATCHLIST_TICKERS),
        return_exceptions=True,
    )
    watchlist_base = [r for r in watchlist_results if not isinstance(r, BaseException)]

    market = {"indices": indices, "sectors": sectors}

    # None of these three depend on each other -- the narrative only needs
    # indices/sectors, not watchlist history -- so they run concurrently
    # rather than one after another.
    history_results, narrative, news = await asyncio.gather(
        asyncio.gather(*(_price_history(w["symbol"]) for w in watchlist_base), return_exceptions=True),
        _generate_market_narrative(market),
        _fetch_market_news(),
    )
    watchlist = [
        {**w, "points": (h if not isinstance(h, BaseException) and h else [])}
        for w, h in zip(watchlist_base, history_results)
    ]

    client_alerts = await _cabinet_concentration_scan()

    return {
        "indices": indices, "sectors": sectors, "watchlist": watchlist,
        "narrative": narrative, "news": news, "client_alerts": client_alerts,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_data_endpoints.py -k get_briefing -v`
Expected: PASS (5/5)

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest tests/ -v`
Expected: PASS, all tests (previous count plus this task's new tests)

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/data.py tests/unit/test_data_endpoints.py
git commit -m "feat(briefing): add GET /data/briefing endpoint

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjgaMZZ37PufvHKBSTqrWF"
```

---

## Task 6: Frontend API client for Briefing

**Files:**
- Modify: `frontend/src/lib/api.ts` (add types + `getBriefing`)
- Test: `frontend/src/lib/api.test.ts` if one exists for other `get*` functions — otherwise this task's deliverable is exercised end-to-end by Task 8's `BriefingPage.test.tsx`, so no standalone test file is required here (matches how `getClientReport`/`generateClientReport` were added in chantier 3 with no dedicated `api.test.ts`).

**Interfaces:**
- Produces:
  - `interface BriefingQuote { symbol: string; name: string; price: number; change_pct: number }`
  - `interface BriefingWatchlistQuote extends BriefingQuote { points: { date: string; close: number }[] }`
  - `interface BriefingNewsItem { title: string; url: string }`
  - `interface BriefingData { indices: BriefingQuote[]; sectors: BriefingQuote[]; watchlist: BriefingWatchlistQuote[]; narrative: string; news: BriefingNewsItem[]; client_alerts: { available: boolean; threshold_pct: number; breaches: { label: string; ticker: string; weight_pct: number; market_value: number }[] } }`
  - `async function getBriefing(base?: string): Promise<BriefingData>`

- [ ] **Step 1: Check the existing convention**

Read `frontend/src/lib/api.ts`'s existing `getClientReport` function to copy its exact fetch-throw-on-`!res.ok` shape (same `API_BASE` default parameter pattern).

- [ ] **Step 2: Write the implementation**

Add to `frontend/src/lib/api.ts`:

```ts
export interface BriefingQuote {
  symbol: string;
  name: string;
  price: number;
  change_pct: number;
}

export interface BriefingWatchlistQuote extends BriefingQuote {
  points: { date: string; close: number }[];
}

export interface BriefingNewsItem {
  title: string;
  url: string;
}

export interface BriefingData {
  indices: BriefingQuote[];
  sectors: BriefingQuote[];
  watchlist: BriefingWatchlistQuote[];
  narrative: string;
  news: BriefingNewsItem[];
  client_alerts: {
    available: boolean;
    threshold_pct: number;
    breaches: { label: string; ticker: string; weight_pct: number; market_value: number }[];
  };
}

export async function getBriefing(base = API_BASE): Promise<BriefingData> {
  const res = await fetch(`${base}/data/briefing`);
  if (!res.ok) throw new Error(`briefing ${res.status}`);
  return res.json();
}
```

- [ ] **Step 3: Verify the frontend still builds**

Run: `cd frontend && npm run build`
Expected: PASS (no TypeScript errors)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(briefing): add BriefingData type and getBriefing to the api client

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjgaMZZ37PufvHKBSTqrWF"
```

---

## Task 7: Sparkline component

**Files:**
- Create: `frontend/src/briefing/Sparkline.tsx`
- Test: `frontend/src/briefing/Sparkline.test.tsx`

**Interfaces:**
- Produces: `function Sparkline({ points }: { points: { date: string; close: number }[] }): JSX.Element | null`. Renders nothing (`null`) when `points` is empty.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("renders a chart container for non-empty points", () => {
    const { container } = render(
      <Sparkline points={[{ date: "2026-09-21", close: 338.98 }, { date: "2026-09-22", close: 340.0 }]} />,
    );
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });

  it("renders nothing for empty points", () => {
    const { container } = render(<Sparkline points={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/briefing/Sparkline.test.tsx`
Expected: FAIL with "Failed to resolve import "./Sparkline""

- [ ] **Step 3: Write the implementation**

```tsx
import { Line, LineChart, ResponsiveContainer } from "recharts";

export function Sparkline({ points }: { points: { date: string; close: number }[] }) {
  if (points.length === 0) return null;
  return (
    <div className="h-10 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points}>
          <Line type="monotone" dataKey="close" stroke="#34d399" dot={false} strokeWidth={1.5} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/briefing/Sparkline.test.tsx`
Expected: PASS (2/2)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/briefing/Sparkline.tsx frontend/src/briefing/Sparkline.test.tsx
git commit -m "feat(briefing): add Sparkline component for watchlist cards

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjgaMZZ37PufvHKBSTqrWF"
```

---

## Task 8: BriefingPage

**Files:**
- Create: `frontend/src/briefing/BriefingPage.tsx`
- Test: `frontend/src/briefing/BriefingPage.test.tsx`

**Interfaces:**
- Consumes: `getBriefing`, `BriefingData` (Task 6); `Sparkline` (Task 7); `ConcentrationAlert` from `../desk/displays/ConcentrationAlert` (existing, takes `{ display: { type: "concentration_alert", threshold_pct, breaches } }`).
- Produces: `function BriefingPage(): JSX.Element`, default-exported-free named export, mounted at `/briefing` in Task 9.

- [ ] **Step 1: Write the failing tests**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { BriefingPage } from "./BriefingPage";
import type { BriefingData } from "../lib/api";

const DATA: BriefingData = {
  indices: [{ symbol: "^GSPC", name: "S&P 500", price: 5800.0, change_pct: 0.73 }],
  sectors: [{ symbol: "XLK", name: "Technology", price: 230.0, change_pct: 1.2 }],
  watchlist: [
    { symbol: "AAPL", name: "Apple Inc.", price: 258.0, change_pct: -0.5, points: [{ date: "2026-09-21", close: 258.0 }] },
  ],
  narrative: "Markets edged higher today on strong tech earnings.",
  news: [{ title: "Markets rally", url: "https://example.com/a" }],
  client_alerts: { available: true, threshold_pct: 30.0, breaches: [{ label: "Jane Doe", ticker: "NVDA", weight_pct: 65.0, market_value: 65000 }] },
};

function stubFetch(data: BriefingData) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => data }));
}

describe("BriefingPage", () => {
  it("shows a loading indicator, then renders every section", async () => {
    stubFetch(DATA);
    render(<BriefingPage />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();

    expect(await screen.findByText("S&P 500")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText(/Résumé du marché macro-économique et micro-économique/)).toBeInTheDocument();
    expect(screen.getByText(DATA.narrative)).toBeInTheDocument();
    expect(screen.getByText("Markets rally")).toBeInTheDocument();
    expect(screen.getByText(/Jane Doe/)).toBeInTheDocument(); // via ConcentrationAlert
    expect(screen.queryByText(/loading/i)).not.toBeInTheDocument();
  });

  it("shows an error message when the fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }));
    render(<BriefingPage />);
    expect(await screen.findByText(/failed to load/i)).toBeInTheDocument();
  });

  it("omits the indices/sectors/watchlist sections when they are empty", async () => {
    stubFetch({ ...DATA, indices: [], sectors: [], watchlist: [] });
    render(<BriefingPage />);
    await screen.findByText(DATA.narrative);
    expect(screen.queryByText("S&P 500")).not.toBeInTheDocument();
    expect(screen.queryByText("Technology")).not.toBeInTheDocument();
    expect(screen.queryByText("Apple Inc.")).not.toBeInTheDocument();
  });

  it("shows a 'No news available' fallback when news is empty", async () => {
    stubFetch({ ...DATA, news: [] });
    render(<BriefingPage />);
    expect(await screen.findByText(/no news available/i)).toBeInTheDocument();
  });

  it("shows 'No concentration breaches' and does not render ConcentrationAlert when available but empty", async () => {
    // Regression (chantier-3 finding, pinned again here): an empty
    // breaches list must never render an empty alert box.
    stubFetch({ ...DATA, client_alerts: { available: true, threshold_pct: 30.0, breaches: [] } });
    render(<BriefingPage />);
    expect(await screen.findByText(/no concentration breaches/i)).toBeInTheDocument();
    expect(screen.queryByText(/Concentration >/)).not.toBeInTheDocument();
  });

  it("shows an 'Alerts unavailable' fallback when client_alerts.available is false", async () => {
    stubFetch({ ...DATA, client_alerts: { available: false, threshold_pct: 30.0, breaches: [] } });
    render(<BriefingPage />);
    expect(await screen.findByText(/alerts unavailable/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/briefing/BriefingPage.test.tsx`
Expected: FAIL with "Failed to resolve import "./BriefingPage""

- [ ] **Step 3: Write the implementation**

```tsx
import { useEffect, useState } from "react";
import { ConcentrationAlert } from "../desk/displays/ConcentrationAlert";
import { getBriefing, type BriefingData, type BriefingQuote } from "../lib/api";
import { Sparkline } from "./Sparkline";

function changeColor(change_pct: number) {
  return change_pct >= 0 ? "text-terminal-accent" : "text-terminal-danger";
}

function QuoteCard({ name, price, change_pct }: BriefingQuote) {
  return (
    <div className="rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3">
      <div className="text-xs text-terminal-muted">{name}</div>
      <div className="font-mono text-sm font-semibold text-terminal-text">{price.toFixed(2)}</div>
      <div className={`text-xs ${changeColor(change_pct)}`}>
        {change_pct >= 0 ? "+" : ""}{change_pct.toFixed(2)}%
      </div>
    </div>
  );
}

export function BriefingPage() {
  const [data, setData] = useState<BriefingData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBriefing()
      .then(setData)
      .catch(() => setError("Failed to load the briefing."));
  }, []);

  if (error) {
    return (
      <main className="flex min-h-0 flex-1 items-center justify-center font-mono text-sm text-terminal-danger">
        {error}
      </main>
    );
  }
  if (!data) {
    return (
      <main className="flex min-h-0 flex-1 items-center justify-center font-mono text-sm text-terminal-muted">
        Loading…
      </main>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4 font-mono text-sm text-terminal-text">
      {data.indices.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-xs font-semibold text-terminal-muted">Indices</h3>
          <div className="grid grid-cols-4 gap-2">
            {data.indices.map((q) => <QuoteCard key={q.symbol} {...q} />)}
          </div>
        </section>
      )}

      {data.watchlist.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-xs font-semibold text-terminal-muted">Watchlist</h3>
          <div className="grid grid-cols-3 gap-2">
            {data.watchlist.map((q) => (
              <div key={q.symbol} className="rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3">
                <div className="text-xs text-terminal-muted">{q.name}</div>
                <div className="font-mono text-sm font-semibold text-terminal-text">{q.price.toFixed(2)}</div>
                <div className={`text-xs ${changeColor(q.change_pct)}`}>
                  {q.change_pct >= 0 ? "+" : ""}{q.change_pct.toFixed(2)}%
                </div>
                <Sparkline points={q.points} />
              </div>
            ))}
          </div>
        </section>
      )}

      {data.sectors.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-xs font-semibold text-terminal-muted">Sector performance</h3>
          <div className="flex flex-col gap-1 rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3">
            {data.sectors.map((s) => (
              <div key={s.symbol} className="flex items-center justify-between">
                <span>{s.name}</span>
                <span className={changeColor(s.change_pct)}>
                  {s.change_pct >= 0 ? "+" : ""}{s.change_pct.toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="flex flex-col gap-1.5">
        <h3 className="text-xs font-semibold text-terminal-muted">
          Résumé du marché macro-économique et micro-économique
        </h3>
        <div className="whitespace-pre-line rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 text-xs leading-relaxed text-terminal-text">
          {data.narrative}
        </div>
      </section>

      <section className="flex flex-col gap-1.5">
        <h3 className="text-xs font-semibold text-terminal-muted">News</h3>
        {data.news.length > 0 ? (
          <ul className="flex flex-col gap-1 text-xs">
            {data.news.map((n) => (
              <li key={n.url}>
                <a href={n.url} target="_blank" rel="noreferrer" className="text-terminal-accent hover:underline">
                  {n.title}
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-xs text-terminal-muted">No news available.</div>
        )}
      </section>

      <section className="flex flex-col gap-1.5">
        <h3 className="text-xs font-semibold text-terminal-muted">Client alerts</h3>
        {data.client_alerts.available ? (
          data.client_alerts.breaches.length > 0 ? (
            <ConcentrationAlert
              display={{
                type: "concentration_alert",
                threshold_pct: data.client_alerts.threshold_pct,
                breaches: data.client_alerts.breaches,
              }}
            />
          ) : (
            <div className="text-xs text-terminal-muted">No concentration breaches.</div>
          )
        ) : (
          <div className="text-xs text-terminal-muted">Alerts unavailable.</div>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/briefing/BriefingPage.test.tsx`
Expected: PASS (6/6)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/briefing/BriefingPage.tsx frontend/src/briefing/BriefingPage.test.tsx
git commit -m "feat(briefing): add BriefingPage

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjgaMZZ37PufvHKBSTqrWF"
```

---

## Task 9: Wire BriefingPage into App.tsx and retire ComingSoonPage

**Files:**
- Modify: `frontend/src/App.tsx` (lines 4, 122-130)
- Modify: `frontend/src/App.test.tsx` (lines 11-13, 54-57)
- Delete: `frontend/src/layout/ComingSoonPage.tsx`, `frontend/src/layout/ComingSoonPage.test.tsx` (verify no remaining references first)

**Interfaces:**
- Consumes: `BriefingPage` from `./briefing/BriefingPage` (Task 8).

- [ ] **Step 1: Verify ComingSoonPage has no other usages**

Run: `cd frontend && grep -rn "ComingSoonPage" src/`
Expected: only `App.tsx` (import + the `/briefing` route) and the component's own file + its own test file. If any other file references it, stop and investigate before deleting.

- [ ] **Step 2: Update the failing App.test.tsx first**

In `frontend/src/App.test.tsx`, replace lines 11-13:

```tsx
vi.mock("./reports/ReportWorkspace", () => ({
  ReportWorkspace: () => <div data-testid="report-workspace" />,
}));
```

with:

```tsx
vi.mock("./reports/ReportWorkspace", () => ({
  ReportWorkspace: () => <div data-testid="report-workspace" />,
}));
vi.mock("./briefing/BriefingPage", () => ({
  BriefingPage: () => <div data-testid="briefing-page" />,
}));
```

Then replace the test at lines 54-57:

```tsx
  it("the one not-yet-built section renders ComingSoonPage without crashing", () => {
    renderAt("/briefing");
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });
```

with:

```tsx
  it("/briefing renders BriefingPage", () => {
    renderAt("/briefing");
    expect(screen.getByTestId("briefing-page")).toBeInTheDocument();
  });
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL — `/briefing` still renders `ComingSoonPage`, not the mocked `BriefingPage` testid.

- [ ] **Step 4: Update App.tsx**

Replace line 4:

```tsx
import { ComingSoonPage } from "./layout/ComingSoonPage";
```

with:

```tsx
import { BriefingPage } from "./briefing/BriefingPage";
```

Replace lines 122-130:

```tsx
          <Route
            path="/briefing"
            element={
              <ComingSoonPage
                title="Briefing"
                description="Automatic daily summary: concentration alerts, notable market moves, agent synthesis. Coming in a future chantier."
              />
            }
          />
```

with:

```tsx
          <Route path="/briefing" element={<BriefingPage />} />
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS (all tests, with `/briefing renders BriefingPage` passing)

- [ ] **Step 6: Delete the now-dead ComingSoonPage files**

```bash
rm frontend/src/layout/ComingSoonPage.tsx frontend/src/layout/ComingSoonPage.test.tsx
```

- [ ] **Step 7: Run the full frontend suite**

Run: `cd frontend && npm test -- --run`
Expected: PASS, all tests (no ComingSoonPage-related failures, no orphaned imports)

- [ ] **Step 8: Verify the real production build**

Run: `cd frontend && npm run build`
Expected: PASS (no TypeScript errors — this is the check that caught the unused-import bug in chantier 3; `vitest` passing is not sufficient on its own)

- [ ] **Step 9: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git rm frontend/src/layout/ComingSoonPage.tsx frontend/src/layout/ComingSoonPage.test.tsx
git commit -m "feat(briefing): wire BriefingPage into /briefing, retire ComingSoonPage

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjgaMZZ37PufvHKBSTqrWF"
```

---

## Final Checks (after Task 9)

- [ ] Run the full backend suite: `uv run pytest tests/ -v` — expect all green.
- [ ] Run the full frontend suite: `cd frontend && npm test -- --run` — expect all green.
- [ ] Run the frontend production build: `cd frontend && npm run build` — expect no TypeScript errors.
- [ ] Restart both dev servers (backend has no `--reload`; frontend's Vite HMR should already reflect the changes) and open `/briefing` in a real browser for a live-Chrome QA pass — jsdom/vitest cannot catch rendering bugs (chantier 3 found two: a clipped chart label and a blank-page loading state). Check in particular: sparklines render inside watchlist cards, the narrative heading reads exactly "Résumé du marché macro-économique et micro-économique", and the page does not visibly hang for several seconds with no loading indicator on first load (cold yfinance calls).
