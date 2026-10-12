"""Read-only clients/holdings/documents view, plus PDF->RAG and
Excel->DB imports, for the React console's /data section. Deliberately
NOT wired into the agent graph: this is deterministic CRUD and ingestion,
not an agent capability -- see docs/superpowers/specs/
2026-10-03-data-import-and-view-design.md Decision 9."""

import asyncio
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.agent.tools.concentration import build_holdings_query, parse_tool_payload, price_from_quote
from app.agent.tools.finance_calc import (
    LabeledPortfolio,
    Position,
    compute_concentration_screen,
    compute_portfolio_metrics,
)
from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.agent.tools.portfolio_report import build_portfolio_report_xlsx
from app.core.config import settings
from app.data_import.client_summary import build_client_summary
from app.data_import.db import (
    DB_PATH,
    client_id_by_email,
    existing_client_emails,
    get_client_with_holdings,
    known_tickers,
    list_clients_with_holdings,
    write_clients,
    write_holdings,
)
from app.data_import.pdf_ingest import ingest_single_pdf
from app.reports.names import slugify
from app.data_import.validation import (
    detect_import_type,
    validate_clients_rows,
    validate_holdings_rows,
)

router = APIRouter(prefix="/data")


class ImportRowsRequest(BaseModel):
    rows: list[dict]


class ImportConfirmRequest(BaseModel):
    type: str
    rows: list[dict]


def _validate(conn: sqlite3.Connection, rows: list[dict]):
    kind = detect_import_type(rows)
    if kind is None:
        return None, None
    if kind == "clients":
        return kind, validate_clients_rows(rows, existing_emails=existing_client_emails(conn))
    return kind, validate_holdings_rows(
        rows, client_id_by_email=client_id_by_email(conn), known_tickers=known_tickers(conn)
    )


@router.get("/clients")
async def get_clients() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        return list_clients_with_holdings(conn)
    finally:
        conn.close()


async def _fetch_live_price(ticker: str) -> float:
    # Deferred import: avoids connecting to the yfinance MCP server at
    # module import time for every test that imports this router, same
    # convention as client_portfolio_tool / concentration_screen_tool.
    from app.agent.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"
    return price_from_quote(parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: ticker})))


# A single yfinance MCP quote call measured ~5-6s locally (yfinance's own
# Yahoo Finance round trip, not something this app controls), and the
# /summary and /report endpoints each fetch the same client's tickers
# independently -- clicking a client then "View full report" moments later
# re-fetched every price from scratch. This short TTL cache means the
# second fetch for a ticker already seen recently is instant. Five minutes
# keeps Briefing -> Client -> Report navigation responsive without pretending
# that an old quote is real-time market data.
_price_cache: dict[str, tuple[float, float]] = {}
_PRICE_CACHE_TTL_S = 300.0


async def _live_price(ticker: str) -> float:
    now = time.monotonic()
    cached = _price_cache.get(ticker)
    if cached is not None and now - cached[1] < _PRICE_CACHE_TTL_S:
        return cached[0]
    price = await _fetch_live_price(ticker)
    _price_cache[ticker] = (price, now)
    return price


_MARKETS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "us": ("United States", [("S&P 500", "^GSPC"), ("Dow Jones", "^DJI"), ("Nasdaq", "^IXIC"), ("Russell 2000", "^RUT"), ("NYSE Composite", "^NYA"), ("S&P MidCap 400", "^MID"), ("VIX", "^VIX")]),
    "europe": ("Europe", [("DAX", "^GDAXI"), ("FTSE 100", "^FTSE"), ("CAC 40", "^FCHI"), ("Euro Stoxx 50", "^STOXX50E"), ("IBEX 35", "^IBEX"), ("SMI", "^SSMI"), ("AEX", "^AEX")]),
    "asia": ("Asia", [("Nikkei 225", "^N225"), ("Hang Seng", "^HSI"), ("Shanghai Composite", "000001.SS"), ("KOSPI", "^KS11"), ("Nifty 50", "^NSEI"), ("BSE Sensex", "^BSESN"), ("ASX 200", "^AXJO"), ("Taiwan Weighted", "^TWII")]),
    "latin-america": ("Latin America", [("Ibovespa", "^BVSP"), ("S&P/BMV IPC", "^MXX"), ("Merval", "^MERV"), ("S&P Latin America 40", "^SPBLPGPT"), ("S&P IPSA", "^IPSA")]),
    "currencies": ("Currencies", [("EUR / USD", "EURUSD=X"), ("USD / JPY", "JPY=X"), ("GBP / USD", "GBPUSD=X"), ("AUD / USD", "AUDUSD=X"), ("USD / CAD", "CAD=X"), ("USD / CHF", "CHF=X"), ("USD / CNY", "CNY=X")]),
    "crypto": ("Cryptocurrency", [("Bitcoin", "BTC-USD"), ("Ethereum", "ETH-USD"), ("Solana", "SOL-USD"), ("XRP", "XRP-USD"), ("BNB", "BNB-USD"), ("Dogecoin", "DOGE-USD"), ("Cardano", "ADA-USD")]),
}
_INDEX_TICKERS = _MARKETS["us"][1]
_SECTOR_ETFS = [
    ("Technology", "XLK"), ("Financial Services", "XLF"), ("Healthcare", "XLV"),
    ("Energy", "XLE"), ("Consumer Cyclical", "XLY"), ("Consumer Defensive", "XLP"),
    ("Industrials", "XLI"), ("Communication Services", "XLC"),
]
_WATCHLIST_TICKERS = ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META"]
_MARKET_MOVER_TICKERS = {
    "us": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "WMT", "XOM", "NFLX"],
    "europe": ["SAP.DE", "ASML.AS", "SIE.DE", "AIR.PA", "MC.PA", "OR.PA", "SHEL.L", "AZN.L", "HSBA.L", "NESN.SW"],
    "asia": ["7203.T", "6758.T", "9984.T", "0700.HK", "9988.HK", "005930.KS", "000660.KS", "RELIANCE.NS"],
    "latin-america": ["PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "ABEV3.SA", "AMXL.MX", "WALMEX.MX", "MELI"],
    "currencies": [symbol for _, symbol in _MARKETS["currencies"][1]],
    "crypto": [symbol for _, symbol in _MARKETS["crypto"][1]],
}
_MARKET_TICKER_SPECS = [
    ("S&P 500", "^GSPC"),
    ("Nasdaq", "^IXIC"),
    ("Dow Jones", "^DJI"),
    ("DAX", "^GDAXI"),
    ("Nikkei 225", "^N225"),
    ("Bitcoin", "BTC-USD"),
    ("EUR/USD", "EURUSD=X"),
    ("Gold", "GC=F"),
    ("Crude Oil", "CL=F"),
]


def _change_pct_from_quote(info: dict) -> float:
    for key in ("regularMarketChangePercent", "fulldayChangePercent"):
        value = info.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    raise ValueError("no change percent in quote")


async def _quote_snapshot(symbol: str, *, name: str | None = None) -> dict:
    from app.agent.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"
    info = parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: symbol}))
    price = price_from_quote(info)
    snapshot = {
        "symbol": symbol,
        "name": name or info.get("shortName") or info.get("longName") or symbol,
        "price": price,
        "change_pct": _change_pct_from_quote(info),
    }
    # Reports and client summaries use the lighter price cache. Reusing the
    # exact quote fetched here prevents another 5-6s yfinance round trip when
    # an advisor opens a report directly after the Briefing.
    _price_cache[symbol] = (price, time.monotonic())
    volume = info.get("regularMarketVolume") or info.get("volume")
    if isinstance(volume, (int, float)):
        snapshot["volume"] = int(volume)
    return snapshot


# Briefing is a "daily summary", not a live ticker -- 600s, not the 30s
# Reports/Clients use. Separate cache from _price_cache: this stores a
# full snapshot dict (symbol/name/price/change_pct), not a bare float.
_quote_cache: dict[str, tuple[dict, float]] = {}
_quote_inflight: dict[str, asyncio.Task] = {}
_BRIEFING_CACHE_TTL_S = 600.0


async def _cached_quote_snapshot(symbol: str, *, name: str | None = None) -> dict:
    now = time.monotonic()
    cached = _quote_cache.get(symbol)
    if cached is not None and now - cached[1] < _BRIEFING_CACHE_TTL_S:
        return cached[0]
    task = _quote_inflight.get(symbol)
    if task is None:
        task = asyncio.create_task(_quote_snapshot(symbol, name=name))
        _quote_inflight[symbol] = task
    try:
        snapshot = await task
        _quote_cache[symbol] = (snapshot, time.monotonic())
        return snapshot
    finally:
        if _quote_inflight.get(symbol) is task:
            _quote_inflight.pop(symbol, None)


@router.get("/clients/{client_id}/summary")
async def get_client_summary(client_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        client = get_client_with_holdings(conn, client_id)
    finally:
        conn.close()
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    return await build_client_summary(client=client, get_price=_live_price)


async def _generate_narrative(report: dict) -> str:
    # Deferred import: avoids constructing a ChatOpenAI client (and
    # requiring OPENAI_API_KEY) at module import time for every test that
    # imports this router, same convention as _live_price's yfinance import.
    from app.narratives.portfolio_narrative import generate_portfolio_narrative

    return await generate_portfolio_narrative(report)


async def _fetch_market_news(query: str = "US stock market today") -> list[dict]:
    # TavilyClient.search is SYNCHRONOUS -- must run in a thread or it
    # blocks the event loop for every other request this process serves.
    from tavily import TavilyClient

    try:
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = await asyncio.to_thread(
            client.search, query=query, max_results=5, search_depth="basic",
        )
        return [
            {
                "title": r.get("title", ""), "url": r["url"],
                **({"summary": r["content"][:280]} if r.get("content") else {}),
            }
            for r in response.get("results", [])
            if r.get("url")
        ]
    except Exception:
        return []


async def _generate_market_narrative(market: dict) -> str:
    from app.narratives.market_narrative import generate_market_narrative

    try:
        return await generate_market_narrative(market)
    except Exception:
        # An OpenAI timeout/rate-limit/auth error must not throw away the
        # indices/sectors/watchlist/news/client_alerts this same request
        # already fetched successfully -- same fallback string the
        # no-data case already uses.
        return "Market data unavailable right now."


async def _market_movers(market: str = "us") -> dict[str, list[dict]]:
    results = await asyncio.gather(
        *(_cached_quote_snapshot(symbol) for symbol in _MARKET_MOVER_TICKERS[market]), return_exceptions=True,
    )
    quotes = [quote for quote in results if not isinstance(quote, BaseException)]
    return {
        "most_active": sorted(quotes, key=lambda quote: quote.get("volume", 0), reverse=True)[:4],
        "gainers": sorted(quotes, key=lambda quote: quote["change_pct"], reverse=True)[:4],
        "losers": sorted(quotes, key=lambda quote: quote["change_pct"])[:4],
    }


@router.get("/briefing")
async def get_briefing(market: str = "us", detail: bool = True) -> dict:
    if market not in _MARKETS:
        raise HTTPException(status_code=422, detail="unknown market")
    market_id = market
    market_name, market_indices = _MARKETS[market_id]
    # The first response intentionally fetches only four index quotes. The
    # client then requests detail in the background, so the dashboard becomes
    # useful without waiting for histories, Tavily, OpenAI, and CRM screening.
    if not detail:
        results = await asyncio.gather(
            *(_cached_quote_snapshot(ticker, name=name) for name, ticker in market_indices),
            return_exceptions=True,
        )
        return {
            "market": market_id, "market_name": market_name,
            "markets": [{"id": key, "name": value[0]} for key, value in _MARKETS.items()],
            "indices": [result for result in results if not isinstance(result, BaseException)],
            "sectors": [], "watchlist": [], "narrative": "", "news": [],
            "movers": {"most_active": [], "gainers": [], "losers": []},
            "client_alerts": {"available": False, "threshold_pct": 30.0, "breaches": []},
        }
    # All 18 index/sector/watchlist quotes in ONE batch -- not 3 separate
    # awaited gathers run one after another, which used to pay yfinance's
    # latency 3 times over on a cold load (measured ~73s against the real
    # endpoint before this fix).
    n_idx, n_sec = len(market_indices), len(_SECTOR_ETFS)
    quote_specs = (
        list(market_indices) + list(_SECTOR_ETFS) + [(None, ticker) for ticker in _WATCHLIST_TICKERS]
    )
    movers_task = asyncio.create_task(_market_movers(market_id))
    quote_results = await asyncio.gather(
        *(_cached_quote_snapshot(ticker, name=name) for name, ticker in quote_specs),
        return_exceptions=True,
    )
    index_results = quote_results[:n_idx]
    sector_results = quote_results[n_idx:n_idx + n_sec]
    watchlist_results = quote_results[n_idx + n_sec:]

    indices = [r for r in index_results if not isinstance(r, BaseException)]
    sectors = [r for r in sector_results if not isinstance(r, BaseException)]
    watchlist_base = [r for r in watchlist_results if not isinstance(r, BaseException)]

    market_payload = {"indices": indices, "sectors": sectors}

    # None of these four depend on each other -- the narrative only needs
    # indices/sectors, the cabinet scan only needs the DB + live prices --
    # so they all run concurrently rather than one after another.
    history_results, narrative, news, client_alerts, movers = await asyncio.gather(
        asyncio.gather(*(_price_history(w["symbol"]) for w in watchlist_base), return_exceptions=True),
        _generate_market_narrative(market_payload),
        _fetch_market_news() if market_id == "us" else _fetch_market_news(f"{market_name} markets today"),
        _cabinet_concentration_scan(),
        movers_task,
    )
    watchlist = [
        {**w, "points": (h if not isinstance(h, BaseException) and h else [])}
        for w, h in zip(watchlist_base, history_results)
    ]

    return {
        "market": market_id, "market_name": market_name,
        "markets": [{"id": key, "name": value[0]} for key, value in _MARKETS.items()],
        "indices": indices, "sectors": sectors, "watchlist": watchlist,
        "narrative": narrative, "news": news, "movers": movers, "client_alerts": client_alerts,
    }


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

    tickers = sorted({r[2] for r in rows})
    price_results = await asyncio.gather(*(_live_price(t) for t in tickers), return_exceptions=True)
    prices = {t: p for t, p in zip(tickers, price_results) if not isinstance(p, BaseException)}

    # Grouped by client_id, not by name -- two different clients sharing
    # the exact same name must never be merged into one portfolio (that
    # would hide one client's real concentration inside the other's, or
    # fabricate a breach neither has alone).
    by_client: dict[int, tuple[str, list[Position]]] = {}
    for client_id, name, ticker, shares, avg_cost, sector in rows:
        if ticker not in prices:
            continue
        by_client.setdefault(client_id, (name, []))[1].append(Position(
            ticker=ticker, shares=shares, avg_cost=avg_cost, price=prices[ticker], sector=sector,
        ))

    name_counts: dict[str, int] = {}
    for name, positions in by_client.values():
        if positions:
            name_counts[name] = name_counts.get(name, 0) + 1

    seen: dict[str, int] = {}
    portfolios: list[LabeledPortfolio] = []
    for name, positions in by_client.values():
        if not positions:
            continue
        if name_counts[name] > 1:
            seen[name] = seen.get(name, 0) + 1
            label = f"{name} (#{seen[name]})"
        else:
            label = name
        portfolios.append(LabeledPortfolio(label=label, positions=positions))
    if not portfolios:
        return unavailable

    try:
        screen = compute_concentration_screen(portfolios, threshold_pct=30.0)
    except ValueError:
        # Defensive: compute_concentration_screen rejects a few other
        # portfolio shapes outright (e.g. the same ticker twice for one
        # client) -- degrade rather than 500 the whole Briefing page.
        return unavailable
    return {"available": True, "threshold_pct": screen["threshold_pct"], "breaches": screen["breaches"]}


def _tool_content_text(result) -> str:
    # Same content-block-joining step parse_tool_payload does, stopped
    # before its JSON/literal_eval attempt -- yfinance_get_price_history's
    # raw text is a markdown table, not JSON, and would fail both.
    if isinstance(result, list) and result and all(isinstance(b, dict) and "type" in b for b in result):
        return "".join(b.get("text", "") for b in result if b.get("type") == "text")
    return str(result)


async def _price_history(ticker: str) -> list[dict]:
    from app.agent.display import normalize_price_history
    from app.agent.mcp_clients.yfinance_client import yf_history_tool

    symbol_arg = "symbol" if "symbol" in yf_history_tool.args else "ticker"
    raw = await yf_history_tool.ainvoke({symbol_arg: ticker, "period": "3mo"})
    text = _tool_content_text(raw)
    displays = normalize_price_history(text, {symbol_arg: ticker})
    return displays[0]["points"] if displays else []


_history_cache: dict[str, tuple[list[dict], float]] = {}
_history_inflight: dict[str, asyncio.Task] = {}
_briefing_batch_inflight: dict[tuple[str, ...], asyncio.Task] = {}


async def _cached_price_history(ticker: str) -> list[dict]:
    now = time.monotonic()
    cached = _history_cache.get(ticker)
    if cached is not None and now - cached[1] < _BRIEFING_CACHE_TTL_S:
        return cached[0]
    task = _history_inflight.get(ticker)
    if task is None:
        task = asyncio.create_task(_price_history(ticker))
        _history_inflight[ticker] = task
    try:
        points = await task
        _history_cache[ticker] = (points, time.monotonic())
        return points
    finally:
        if _history_inflight.get(ticker) is task:
            _history_inflight.pop(ticker, None)


def _download_briefing_batch(specs: list[tuple[str | None, str]]) -> list[dict]:
    """Download quotes and chart history for a group in one yfinance call.

    The generic agent tools intentionally go through MCP, but a dashboard fan-out
    of dozens of MCP calls starts one stdio process per invocation.  yfinance's
    native multi-symbol download is a much better fit for this read-only screen.
    """
    import yfinance as yf

    symbols = list(dict.fromkeys(symbol for _, symbol in specs))
    if not symbols:
        return []
    frame = yf.download(
        symbols,
        period="3mo",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
        timeout=10,
        multi_level_index=True,
    )
    if frame is None or frame.empty:
        return []

    downloaded: list[dict] = []
    for name, symbol in specs:
        try:
            if getattr(frame.columns, "nlevels", 1) > 1:
                outer = frame.columns.get_level_values(0)
                ticker_frame = frame[symbol] if symbol in outer else frame.xs(symbol, axis=1, level=-1)
            else:
                ticker_frame = frame
            closes = ticker_frame["Close"].dropna()
            if closes.empty:
                continue
            price = float(closes.iloc[-1])
            previous = float(closes.iloc[-2]) if len(closes) > 1 else price
            change_pct = ((price / previous) - 1.0) * 100.0 if previous else 0.0
            points = [
                {"date": index.strftime("%Y-%m-%d"), "close": float(value)}
                for index, value in closes.items()
            ]
            item = {
                "symbol": symbol,
                "name": name or symbol,
                "price": price,
                "change_pct": change_pct,
                "points": points,
            }
            if "Volume" in ticker_frame:
                volumes = ticker_frame["Volume"].dropna()
                if not volumes.empty:
                    item["volume"] = int(volumes.iloc[-1])
            downloaded.append(item)
        except (KeyError, TypeError, ValueError):
            # Yahoo can return a partial DataFrame when one regional symbol is
            # unavailable. Keep the other cards usable instead of failing all.
            continue
    return downloaded


async def _cached_briefing_batch(specs: list[tuple[str | None, str]]) -> list[dict]:
    now = time.monotonic()
    missing = []
    for spec in specs:
        symbol = spec[1]
        quote = _quote_cache.get(symbol)
        history = _history_cache.get(symbol)
        if (
            quote is None or now - quote[1] >= _BRIEFING_CACHE_TTL_S
            or history is None or now - history[1] >= _BRIEFING_CACHE_TTL_S
        ):
            missing.append(spec)

    if missing:
        key = tuple(sorted(symbol for _, symbol in missing))
        task = _briefing_batch_inflight.get(key)
        if task is None:
            task = asyncio.create_task(asyncio.to_thread(_download_briefing_batch, missing))
            _briefing_batch_inflight[key] = task
        try:
            try:
                downloaded = await task
            except Exception:
                downloaded = []
            cached_at = time.monotonic()
            for item in downloaded:
                symbol = item["symbol"]
                quote = {field: value for field, value in item.items() if field != "points"}
                _quote_cache[symbol] = (quote, cached_at)
                _history_cache[symbol] = (item["points"], cached_at)
                _price_cache[symbol] = (item["price"], cached_at)
        finally:
            if _briefing_batch_inflight.get(key) is task:
                _briefing_batch_inflight.pop(key, None)

    resolved: list[dict] = []
    now = time.monotonic()
    for name, symbol in specs:
        quote = _quote_cache.get(symbol)
        history = _history_cache.get(symbol)
        if quote is None or history is None:
            continue
        if now - quote[1] >= _BRIEFING_CACHE_TTL_S or now - history[1] >= _BRIEFING_CACHE_TTL_S:
            continue
        resolved.append({**quote[0], "name": name or quote[0]["name"], "points": history[0]})
    return resolved


_MARKET_TICKER_CACHE_TTL_S = 60.0
_market_ticker_cache: tuple[list[dict], float] | None = None
_market_ticker_inflight: asyncio.Task | None = None


async def _cached_market_ticker() -> list[dict]:
    global _market_ticker_cache, _market_ticker_inflight

    now = time.monotonic()
    if _market_ticker_cache is not None and now - _market_ticker_cache[1] < _MARKET_TICKER_CACHE_TTL_S:
        return _market_ticker_cache[0]

    task = _market_ticker_inflight
    if task is None:
        task = asyncio.create_task(asyncio.to_thread(_download_briefing_batch, _MARKET_TICKER_SPECS))
        _market_ticker_inflight = task

    try:
        try:
            downloaded = await task
        except Exception:
            downloaded = []

        configured_names = {symbol: name for name, symbol in _MARKET_TICKER_SPECS}
        valid_by_symbol: dict[str, dict] = {}
        if isinstance(downloaded, list):
            for row in downloaded:
                if not isinstance(row, dict):
                    continue
                symbol = row.get("symbol")
                price = row.get("price")
                change_pct = row.get("change_pct")
                if symbol not in configured_names:
                    continue
                if isinstance(price, bool) or not isinstance(price, (int, float)):
                    continue
                if isinstance(change_pct, bool) or not isinstance(change_pct, (int, float)):
                    continue
                if not math.isfinite(float(price)) or not math.isfinite(float(change_pct)):
                    continue
                valid_by_symbol[symbol] = {
                    "symbol": symbol,
                    "name": configured_names[symbol],
                    "price": float(price),
                    "change_pct": float(change_pct),
                }

        items = [
            valid_by_symbol[symbol]
            for _, symbol in _MARKET_TICKER_SPECS
            if symbol in valid_by_symbol
        ]
        _market_ticker_cache = (items, time.monotonic())
        return items
    finally:
        if _market_ticker_inflight is task:
            _market_ticker_inflight = None


@router.get("/market-ticker")
async def get_market_ticker() -> dict:
    return {"items": await _cached_market_ticker()}


def _instrument_name(symbol: str) -> str | None:
    specs = [spec for _, entries in _MARKETS.values() for spec in entries] + _SECTOR_ETFS
    for name, candidate in specs:
        if candidate == symbol:
            return name
    if symbol in _WATCHLIST_TICKERS or any(symbol in values for values in _MARKET_MOVER_TICKERS.values()):
        return None
    raise HTTPException(status_code=422, detail="unknown briefing instrument")


@router.get("/briefing/instrument")
async def get_briefing_instrument(symbol: str) -> dict:
    name = _instrument_name(symbol)
    quote_result, history_result = await asyncio.gather(
        _cached_quote_snapshot(symbol, name=name),
        _cached_price_history(symbol),
        return_exceptions=True,
    )
    if isinstance(quote_result, BaseException):
        raise HTTPException(status_code=503, detail="market quote unavailable")
    return {
        **quote_result,
        "points": [] if isinstance(history_result, BaseException) else history_result,
    }


@router.get("/briefing/indices")
async def get_briefing_indices(market: str = "us") -> dict:
    if market not in _MARKETS:
        raise HTTPException(status_code=422, detail="unknown market")
    return {"items": await _cached_briefing_batch(_MARKETS[market][1])}


@router.get("/briefing/sectors")
async def get_briefing_sectors() -> dict:
    return {"items": await _cached_briefing_batch(_SECTOR_ETFS)}


@router.get("/briefing/watchlist")
async def get_briefing_watchlist() -> dict:
    specs = [(None, symbol) for symbol in _WATCHLIST_TICKERS]
    return {"items": await _cached_briefing_batch(specs)}


_news_cache: dict[str, tuple[list[dict], float]] = {}
_news_inflight: dict[str, asyncio.Task] = {}
_narrative_cache: dict[str, tuple[str, float]] = {}
_narrative_inflight: dict[str, asyncio.Task] = {}
_NEWS_CACHE_TTL_S = 300.0


async def _cached_market_news(market: str, query: str) -> list[dict]:
    now = time.monotonic()
    cached = _news_cache.get(market)
    if cached is not None and now - cached[1] < _NEWS_CACHE_TTL_S:
        return cached[0]
    task = _news_inflight.get(market)
    if task is None:
        task = asyncio.create_task(_fetch_market_news(query))
        _news_inflight[market] = task
    try:
        items = await task
        _news_cache[market] = (items, time.monotonic())
        return items
    finally:
        if _news_inflight.get(market) is task:
            _news_inflight.pop(market, None)


@router.get("/briefing/news")
async def get_briefing_news(market: str = "us") -> dict:
    if market not in _MARKETS:
        raise HTTPException(status_code=422, detail="unknown market")
    market_name = _MARKETS[market][0]
    query = "US stock market today" if market == "us" else f"{market_name} markets today"
    return {"items": await _cached_market_news(market, query)}


async def _build_market_narrative(market: str) -> str:
    indices, sectors = await asyncio.gather(
        _cached_briefing_batch(_MARKETS[market][1]),
        _cached_briefing_batch(_SECTOR_ETFS),
    )
    without_points = lambda items: [
        {field: value for field, value in item.items() if field != "points"}
        for item in items
    ]
    return await _generate_market_narrative({
        "indices": without_points(indices),
        "sectors": without_points(sectors),
    })


async def _cached_market_narrative(market: str) -> str:
    now = time.monotonic()
    cached = _narrative_cache.get(market)
    if cached is not None and now - cached[1] < _BRIEFING_CACHE_TTL_S:
        return cached[0]
    task = _narrative_inflight.get(market)
    if task is None:
        task = asyncio.create_task(_build_market_narrative(market))
        _narrative_inflight[market] = task
    try:
        text = await task
        _narrative_cache[market] = (text, time.monotonic())
        return text
    finally:
        if _narrative_inflight.get(market) is task:
            _narrative_inflight.pop(market, None)


@router.get("/briefing/narrative")
async def get_briefing_narrative(market: str = "us") -> dict:
    if market not in _MARKETS:
        raise HTTPException(status_code=422, detail="unknown market")
    return {"text": await _cached_market_narrative(market)}


@router.get("/briefing/movers")
async def get_briefing_movers(market: str = "us") -> dict:
    if market not in _MARKETS:
        raise HTTPException(status_code=422, detail="unknown market")
    items = await _cached_briefing_batch([
        (None, symbol) for symbol in _MARKET_MOVER_TICKERS[market]
    ])
    quotes = [{field: value for field, value in item.items() if field != "points"} for item in items]
    return {
        "most_active": sorted(quotes, key=lambda quote: quote.get("volume", 0), reverse=True)[:4],
        "gainers": sorted(quotes, key=lambda quote: quote["change_pct"], reverse=True)[:4],
        "losers": sorted(quotes, key=lambda quote: quote["change_pct"])[:4],
    }


@router.get("/briefing/client-alerts")
async def get_briefing_client_alerts() -> dict:
    return await _cabinet_concentration_scan()


@router.get("/clients/{client_id}/report")
async def get_client_report(client_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        client = get_client_with_holdings(conn, client_id)
    finally:
        conn.close()
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")

    holdings = client["holdings"]
    tickers = [h["ticker"] for h in holdings]
    price_results = await asyncio.gather(*(_live_price(t) for t in tickers), return_exceptions=True)

    priced_positions: list[Position] = []
    unpriced_tickers: list[str] = []
    for holding, result in zip(holdings, price_results):
        if isinstance(result, BaseException):
            unpriced_tickers.append(holding["ticker"])
            continue
        priced_positions.append(Position(
            ticker=holding["ticker"], shares=holding["shares"], avg_cost=holding["avg_cost"],
            price=float(result), sector=holding.get("sector"),
        ))

    totals: dict | None = None
    positions: list[dict] = []
    sector_allocation: dict | None = None
    concentration: dict | None = None
    price_history: dict[str, list[dict]] = {}
    # Narrative generation needs only these fields, all computed before any
    # yfinance history call -- running it concurrently with the price
    # history fetch (instead of after) means the endpoint pays for
    # whichever is slower, not both in sequence.
    narrative_input = {
        "name": client["name"], "risk_profile": client["risk_profile"],
        "totals": None, "positions": [], "sector_allocation": None,
        "concentration": None, "unpriced_tickers": unpriced_tickers,
    }

    if priced_positions:
        metrics = compute_portfolio_metrics(priced_positions)
        totals = metrics["totals"]
        positions = metrics["positions"]
        sector_allocation = metrics["sector_allocation"]
        concentration = compute_concentration_screen(
            [LabeledPortfolio(label=client["name"], positions=priced_positions)],
            threshold_pct=30.0,
        )
        narrative_input.update(
            totals=totals, positions=positions,
            sector_allocation=sector_allocation, concentration=concentration,
        )
        top = sorted(positions, key=lambda p: -p["weight_pct"])[:3]
        history_results, narrative = await asyncio.gather(
            asyncio.gather(*(_price_history(p["ticker"]) for p in top), return_exceptions=True),
            _generate_narrative(narrative_input),
        )
        for p, result in zip(top, history_results):
            if not isinstance(result, BaseException) and result:
                price_history[p["ticker"]] = result
    else:
        narrative = await _generate_narrative(narrative_input)

    reports_dir = settings.WORKSPACE_ROOT.resolve() / "reports"
    prefix = f"{slugify(client['name'])}-portfolio-brief-"
    files = sorted(
        (f for f in reports_dir.glob(f"{prefix}*.xlsx") if f.is_file()),
        key=lambda f: f.stat().st_mtime, reverse=True,
    ) if reports_dir.is_dir() else []
    generated_reports = [
        {
            "filename": f.name,
            "generated_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
            "download_url": f"/workspace/files/{f.name}",
        }
        for f in files
    ]

    return {
        "client_id": client["client_id"], "name": client["name"], "email": client["email"],
        "segment": client["segment"], "risk_profile": client["risk_profile"],
        "advisor": client["advisor"], "city": client["city"],
        "totals": totals, "positions": positions, "sector_allocation": sector_allocation,
        "concentration": concentration, "price_history": price_history,
        "unpriced_tickers": unpriced_tickers, "generated_reports": generated_reports,
        "narrative": narrative,
    }


@router.post("/clients/{client_id}/report/generate")
async def generate_client_report(client_id: int) -> dict:
    if settings.MCP_TRANSPORT.lower() == "gateway":
        raise HTTPException(
            status_code=503,
            detail="save_portfolio_report is not available in this deployment "
            "(MCP_TRANSPORT=gateway has no S3 write path for this tool yet).",
        )
    conn = sqlite3.connect(DB_PATH)
    try:
        client = get_client_with_holdings(conn, client_id)
    finally:
        conn.close()
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")

    holdings = client["holdings"]
    if not holdings:
        raise HTTPException(status_code=400, detail="build_portfolio_report_xlsx needs at least one position")

    tickers = [h["ticker"] for h in holdings]
    price_results = await asyncio.gather(*(_live_price(t) for t in tickers), return_exceptions=True)
    failed = [t for t, r in zip(tickers, price_results) if isinstance(r, BaseException)]
    if failed:
        raise HTTPException(status_code=502, detail=f"could not price: {', '.join(failed)}")

    positions = [
        Position(ticker=h["ticker"], shares=h["shares"], avg_cost=h["avg_cost"], price=float(r), sector=h.get("sector"))
        for h, r in zip(holdings, price_results)
    ]
    portfolio = compute_portfolio_metrics(positions)
    portfolio["client_name"] = client["name"]

    xlsx_bytes = await asyncio.to_thread(build_portfolio_report_xlsx, portfolio)
    today = datetime.now(timezone.utc).date().isoformat()
    filename = f"{slugify(client['name'])}-portfolio-brief-{today}.xlsx"
    reports_dir = settings.WORKSPACE_ROOT.resolve() / "reports"

    def _write() -> None:
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / filename).write_bytes(xlsx_bytes)

    await asyncio.to_thread(_write)
    return {"filename": filename}


@router.get("/documents")
async def get_documents() -> list[str]:
    if not KB_MANIFEST_PATH.exists():
        return []
    return json.loads(KB_MANIFEST_PATH.read_text())


@router.post("/import/preview")
async def import_preview(payload: ImportRowsRequest) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        kind, result = _validate(conn, payload.rows)
    finally:
        conn.close()
    if kind is None:
        raise HTTPException(status_code=400, detail="unrecognized file format")
    return {"type": kind, **result}


@router.post("/import/confirm")
async def import_confirm(payload: ImportConfirmRequest) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        kind, result = _validate(conn, payload.rows)
        if kind != payload.type or not result["valid"]:
            raise HTTPException(status_code=409, detail="validation changed since preview, please re-upload")
        try:
            with conn:
                if kind == "clients":
                    write_clients(conn, result["rows"])
                else:
                    write_holdings(conn, result["rows"])
        except sqlite3.DatabaseError as exc:
            raise HTTPException(status_code=500, detail=f"write failed: {exc}") from exc
        return {"written": len(result["rows"])}
    finally:
        conn.close()


@router.post("/import/pdf")
async def import_pdf(file: UploadFile = File(...)) -> dict:
    body = await file.read()
    filename = os.path.basename(file.filename) if file.filename else "upload.pdf"
    if not body.startswith(b"%PDF") or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="invalid PDF")
    # Any failure past this point (a real PDF that OpenAI/Pinecone fails to
    # embed/upsert) is a 500, not a 400 -- it's not the user's input that's
    # wrong. Caught explicitly (rather than left to propagate) because
    # Starlette's TestClient defaults to raise_server_exceptions=True, which
    # would otherwise re-raise instead of yielding a 500 response.
    # ingest_single_pdf makes real network-bound OpenAI/Pinecone calls that
    # can take tens of seconds -- run it off the event loop so it doesn't
    # freeze /stream, the voice worker, or Market Desk for other users.
    try:
        chunk_count = await run_in_threadpool(ingest_single_pdf, body, filename)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ingestion failed: {exc}") from exc
    return {"filename": filename, "chunks_added": chunk_count}
