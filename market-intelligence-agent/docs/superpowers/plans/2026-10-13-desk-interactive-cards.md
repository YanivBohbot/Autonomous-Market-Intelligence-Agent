# Market Desk Interactive Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the company-comparison, what-if, watchlist-alert and SQL-table cards, starter and follow-up suggestions, `useAgentContext`, and an interactive choice card to the Market Desk chat.

**Architecture:**
- Phase A reuses the existing display pipeline: a deterministic Python tool → a `DISPLAY_NORMALIZERS` entry → a `DisplayPayload` → a React card registered via `useRenderTool`.
- Phase B adds an `"ag-ui"` key to the graph state, so CopilotKit's context reaches a `@dynamic_prompt`.
- The choice card is a backend tool that calls LangGraph `interrupt()`. It is rendered through the existing `useInterrupt` hook.
- Follow-up suggestions come from a new last graph node.

**Tech Stack:** Python 3.12, LangChain 1.x `create_agent` + middleware, LangGraph, FastAPI, ag-ui-langgraph; React 19 + Vite + Tailwind, `@copilotkit/react-core` 1.74 (v2), recharts, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-13-desk-interactive-cards-design.md`

## Global Constraints

- **Commands.** Run every command from `market-intelligence-agent/`:
  - Python: `uv run ...`.
  - Frontend: `cd frontend && npx vitest run <path>`.
- **No arithmetic by the LLM.** Every number in a card comes from Python.
- **Data access.** Tools use the existing wrappers only: `crm_tool`, `yf_quote_tool`, `yf_history_tool`, `parse_tool_payload`, `price_from_quote`. They must work over stdio and over the AgentCore Gateway.
- **Fail open.** A normalizer failure must never break an answer; `MarketDeskDisplayMiddleware` already handles this.
- **Docs.** Every new tool gets a `docs/TOOLS.md` row and section, a CLAUDE.md tool-table row, and its name in `_BASE_READ_ONLY_TOOLS` if it is read-only. `ask_user_choice` is deliberately NOT read-only: `ToolRetryMiddleware` retries read-only tools and would catch `GraphInterrupt`.
- **The what-if never writes to the database.**
- **Transports.** `/stream`, `/approve`, voice and AgentCore behave exactly as before. Phase B features are only active when `state["ag-ui"]` is present.
- **Suggestions.** Starter suggestions use `available: "before-first-message"`. Never use `"always"`: commit 740ef53 removed persistent suggestions on purpose.
- **Git.** Commit after every task. Never push. End commit messages with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011F3XVHmonsZjQXwgjBpb5v
  ```
- **Untouched files.** Do not stage `app/agent/orchestration/supervisor.py`, `app/agent/tools/portfolio_report.py` or `app/core/config.py`: they hold unrelated uncommitted edits. Any task that must edit `supervisor.py` stages it with `git add -p` and only its own hunks.
- **Regex literals in Python files.** Write them with the Edit/Write tools, never through a bash heredoc. A heredoc once wrote `\b` as a literal backspace byte.

## Review Focus

1. **Ticker case and whitespace.** `" nvda "` vs `"NVDA"` in `compare_companies` / `simulate_portfolio_change` trades must match the stored upper-case tickers. Pinned in Tasks 1 and 2.
2. **Selling the whole position by pct=100 and by shares=exact.** The position must disappear, not stay with 0 shares, which would crash `Position(shares>0)`. Pinned in Task 2.
3. **A client with no watchlist rows, or a name matching nobody.** `watchlist_alerts` returns empty rows and the card shows nothing, never an error card. Pinned in Tasks 3 and 4.
4. **`read_query` on a non-SELECT error string or an empty result.** No table and no crash. Pinned in Task 4.
5. **Choice interrupt arriving on a transport without the AG-UI key.** The model never sees `ask_user_choice`. Pinned in Task 11.

---

## Phase A

### Task 1: `compare_companies` tool

**Files:**
- Create: `app/agent/tools/compare_companies.py`
- Test: `tests/unit/test_compare_companies.py`

**Interfaces:**
- Consumes: `parse_tool_payload`, `price_from_quote` from `app.agent.tools.concentration`.
- Produces:
  - `async compare_companies(*, symbols: list[str], period: str, get_info: Callable[[str], Awaitable[dict]], get_closes: Callable[[str, str], Awaitable[list[tuple[str, float]]]]) -> dict`;
  - `parse_closes(result) -> list[tuple[str, float]]`;
  - `compare_companies_tool` (LangChain tool named `compare_companies`).
- Return shape:
  ```
  {"period": str, "companies": [{"symbol","name","sector","currency","price","market_cap","trailing_pe","forward_pe","range_position_pct","period_return_pct","points":[{"date","value"}]}], "missing": [str]}
  ```
  or `{"error": str}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_compare_companies.py
import asyncio

import pytest

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_compare_companies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agent.tools.compare_companies'`.

- [ ] **Step 3: Implement**

```python
# app/agent/tools/compare_companies.py
"""`compare_companies` — side-by-side metrics and rebased price series for
2-4 tickers, computed in Python so the comparison card never shows a number
the LLM produced. Data comes through the same yfinance tools the finance
agent uses (yfmcp locally, the yfinance Lambda behind the Gateway)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools.concentration import parse_tool_payload, price_from_quote

Period = Literal["1mo", "3mo", "6mo", "1y"]


def _r(value: float) -> float:
    return round(value + 0.0, 2)


def _markdown_closes(text: str) -> list[tuple[str, float]]:
    closes = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not cells[0][:4].isdigit():
            continue  # header and ':--' separator rows
        try:
            closes.append((cells[0][:10], float(cells[4])))
        except ValueError:
            continue
    return closes


def parse_closes(result: Any) -> list[tuple[str, float]]:
    """(date, close) pairs from yfmcp's markdown table (stdio) or the
    yfinance Lambda's row list (Gateway)."""
    if isinstance(result, list) and result and all(isinstance(b, dict) and "type" in b for b in result):
        result = "".join(b.get("text", "") for b in result if b.get("type") == "text")
    if isinstance(result, str) and "|" in result:
        return _markdown_closes(result)
    rows = parse_tool_payload(result)
    return [(str(r["date"])[:10], float(r["close"])) for r in rows or [] if r.get("close") is not None]


def _range_position(price: float, low: Any, high: Any) -> float | None:
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)) or high <= low:
        return None
    return _r((price - low) / (high - low) * 100)


async def compare_companies(
    *,
    symbols: list[str],
    period: str,
    get_info: Callable[[str], Awaitable[dict]],
    get_closes: Callable[[str, str], Awaitable[list[tuple[str, float]]]],
) -> dict:
    wanted = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    if not 2 <= len(wanted) <= 4:
        return {"error": f"compare_companies needs 2 to 4 distinct tickers, got {wanted}."}

    infos = await asyncio.gather(*(get_info(s) for s in wanted), return_exceptions=True)
    histories = await asyncio.gather(*(get_closes(s, period) for s in wanted), return_exceptions=True)

    companies, missing = [], []
    for symbol, info, closes in zip(wanted, infos, histories):
        try:
            if isinstance(info, BaseException) or isinstance(closes, BaseException) or not closes:
                raise ValueError(symbol)
            price = price_from_quote(info)
        except ValueError:
            missing.append(symbol)
            continue
        base = closes[0][1]
        companies.append({
            "symbol": symbol,
            "name": info.get("shortName") or info.get("longName") or symbol,
            "sector": info.get("sector"),
            "currency": info.get("currency") or "USD",
            "price": _r(price),
            "market_cap": info.get("marketCap"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "range_position_pct": _range_position(price, info.get("fiftyTwoWeekLow"), info.get("fiftyTwoWeekHigh")),
            "period_return_pct": _r((closes[-1][1] - base) / base * 100),
            "points": [{"date": d, "value": _r(c / base * 100)} for d, c in closes],
        })

    if len(companies) < 2:
        return {"error": f"Need at least 2 tickers with market data; missing: {', '.join(missing)}."}
    return {"period": period, "companies": companies, "missing": missing}


class CompareCompaniesInput(BaseModel):
    symbols: list[str] = Field(description="2 to 4 ticker symbols, e.g. ['NVDA', 'AMD'].")
    period: Period = Field(default="6mo", description="Window for the performance chart: 1mo, 3mo, 6mo or 1y.")


@tool("compare_companies", args_schema=CompareCompaniesInput)
async def compare_companies_tool(symbols: list[str], period: str = "6mo") -> dict:
    """Compare 2-4 companies side by side: price, market cap, P/E, position
    in the 52-week range, and performance over `period` with a rebased
    (=100) price chart. Use this for ANY "compare X and Y" / "X vs Y"
    question -- do not fetch each ticker separately."""
    from app.agent.mcp_clients.yfinance_client import yf_history_tool, yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"

    async def get_info(symbol: str) -> dict:
        return parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: symbol}))

    async def get_closes(symbol: str, window: str) -> list[tuple[str, float]]:
        return parse_closes(await yf_history_tool.ainvoke({symbol_arg: symbol, "period": window}))

    return await compare_companies(symbols=symbols, period=period, get_info=get_info, get_closes=get_closes)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_compare_companies.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools/compare_companies.py tests/unit/test_compare_companies.py
git commit -m "feat(finance): compare_companies tool (deterministic side-by-side metrics + rebased series)"
```

### Task 2: `simulate_portfolio_change` tool

**Files:**
- Create: `app/agent/tools/what_if.py`
- Test: `tests/unit/test_what_if.py`

**Interfaces:**
- Consumes:
  - `load_client_portfolio(*, run_sql, get_price, client_name)` from `app.agent.tools.client_portfolio`. It returns the `compute_portfolio_metrics` dict plus `client_name`, or `{"error"}`;
  - `Position` and `compute_portfolio_metrics` from `finance_calc`.
- Produces:
  - `Trade(BaseModel)`;
  - `async simulate_change(*, run_sql, get_price, client_name: str, trades: list[Trade], threshold_pct: float = 30.0) -> dict`;
  - `simulate_portfolio_change_tool`.
- Return shape:
  ```
  {"client_name","before":{"totals","positions":[{"ticker","weight_pct","market_value"}]},"after":{...},"cash_delta","breaches_before":[ticker],"breaches_after":[ticker],"trades":[{"ticker","action","shares","price"}]}
  ```
  or `{"error": str}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_what_if.py
import asyncio

from app.agent.tools.what_if import Trade, simulate_change

HOLDINGS = [
    {"client_id": 1, "name": "Margaret Collins", "ticker": "NVDA", "shares": 100.0, "avg_cost": 50.0, "sector": "Technology"},
    {"client_id": 1, "name": "Margaret Collins", "ticker": "BND", "shares": 100.0, "avg_cost": 70.0, "sector": "ETF"},
]
PRICES = {"NVDA": 200.0, "BND": 70.0, "MSFT": 400.0}


async def run_sql(sql):
    if "FROM holdings" in sql:
        return HOLDINGS if "Collins" in sql else []
    if "FROM companies" in sql:
        return [{"ticker": "MSFT", "sector": "Technology"}] if "MSFT" in sql else []
    raise AssertionError(sql)


async def get_price(ticker):
    return PRICES[ticker]


def sim(trades, name="Collins"):
    return asyncio.run(simulate_change(run_sql=run_sql, get_price=get_price, client_name=name,
                                       trades=[Trade(**t) for t in trades]))


def weights(side):
    return {p["ticker"]: p["weight_pct"] for p in side["positions"]}


def test_sell_half_by_pct_raises_cash_and_resolves_concentration():
    out = sim([{"ticker": " nvda ", "action": "sell", "pct": 50}])
    assert out["client_name"] == "Margaret Collins"
    assert weights(out["before"]) == {"NVDA": 74.07, "BND": 25.93}
    assert weights(out["after"]) == {"NVDA": 58.82, "BND": 41.18}
    assert out["cash_delta"] == 10000.0
    assert out["breaches_before"] == ["NVDA"] and out["breaches_after"] == ["NVDA"]
    assert out["trades"] == [{"ticker": "NVDA", "action": "sell", "shares": 50.0, "price": 200.0}]


def test_sell_everything_by_pct_removes_the_position():
    out = sim([{"ticker": "NVDA", "action": "sell", "pct": 100}])
    assert weights(out["after"]) == {"BND": 100.0}
    assert out["breaches_after"] == []  # BND is an ETF: never a breach


def test_sell_exact_shares_removes_the_position():
    assert "NVDA" not in weights(sim([{"ticker": "NVDA", "action": "sell", "shares": 100}])["after"])


def test_buy_new_ticker_uses_live_price_and_companies_sector():
    out = sim([{"ticker": "MSFT", "action": "buy", "shares": 10}])
    assert out["cash_delta"] == -4000.0
    assert "MSFT" in weights(out["after"])


def test_oversell_is_an_error_and_nothing_applies():
    out = sim([{"ticker": "BND", "action": "sell", "pct": 50}, {"ticker": "NVDA", "action": "sell", "shares": 101}])
    assert "error" in out and "NVDA" in out["error"]


def test_selling_an_unheld_ticker_is_an_error():
    assert "error" in sim([{"ticker": "TSLA", "action": "sell", "shares": 1}])


def test_unknown_client_is_an_error():
    assert "error" in sim([{"ticker": "NVDA", "action": "sell", "pct": 10}], name="Nobody")


def test_trade_needs_exactly_one_of_pct_and_shares():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Trade(ticker="NVDA", action="sell", pct=10, shares=5)
    with pytest.raises(ValidationError):
        Trade(ticker="NVDA", action="sell")
    with pytest.raises(ValidationError):
        Trade(ticker="NVDA", action="buy", pct=10)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_what_if.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# app/agent/tools/what_if.py
"""`simulate_portfolio_change` — a what-if on one client's portfolio.

Loads the real portfolio (live prices), applies hypothetical buys/sells in
Python, and returns before/after weights, totals, cash raised or needed, and
single-stock concentration before/after. A simulation only: nothing is ever
written to the client database."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator

from app.agent.tools.client_portfolio import load_client_portfolio
from app.agent.tools.concentration import parse_tool_payload, price_from_quote
from app.agent.tools.finance_calc import Position, compute_portfolio_metrics


class Trade(BaseModel):
    ticker: str = Field(description="Ticker to buy or sell, e.g. 'NVDA'.")
    action: Literal["buy", "sell"]
    pct: float | None = Field(default=None, gt=0, le=100, description="Sell this % of the current position (sell only).")
    shares: float | None = Field(default=None, gt=0, description="Number of shares to buy or sell.")

    @model_validator(mode="after")
    def _one_size(self) -> "Trade":
        if (self.pct is None) == (self.shares is None):
            raise ValueError("give exactly one of pct or shares")
        if self.pct is not None and self.action == "buy":
            raise ValueError("pct is only valid for a sell")
        return self


def _side(metrics: dict) -> dict:
    return {
        "totals": metrics["totals"],
        "positions": [
            {"ticker": p["ticker"], "weight_pct": p["weight_pct"], "market_value": p["market_value"]}
            for p in metrics["positions"]
        ],
    }


def _breaches(metrics: dict, threshold_pct: float) -> list[str]:
    # Same rule as compute_concentration_screen's default: ETFs never breach.
    return [p["ticker"] for p in metrics["positions"] if p["sector"] != "ETF" and p["weight_pct"] > threshold_pct]


async def simulate_change(
    *,
    run_sql: Callable[[str], Awaitable[list[dict]]],
    get_price: Callable[[str], Awaitable[float]],
    client_name: str,
    trades: list[Trade],
    threshold_pct: float = 30.0,
) -> dict:
    before = await load_client_portfolio(run_sql=run_sql, get_price=get_price, client_name=client_name)
    if "error" in before:
        return before

    book = {p["ticker"]: {"shares": p["shares"], "avg_cost": p["avg_cost"], "price": p["price"], "sector": p["sector"]}
            for p in before["positions"]}
    applied, cash_delta = [], 0.0
    for trade in trades:
        ticker = trade.ticker.strip().upper()
        if trade.action == "sell":
            held = book.get(ticker)
            if held is None:
                return {"error": f"{before['client_name']} does not hold {ticker}; cannot sell it."}
            shares = held["shares"] * trade.pct / 100 if trade.pct is not None else trade.shares
            if shares > held["shares"] + 1e-9:
                return {"error": f"Cannot sell {shares:g} {ticker}: {before['client_name']} holds {held['shares']:g}."}
            held["shares"] -= shares
            if held["shares"] <= 1e-9:
                del book[ticker]
            cash_delta += shares * held["price"]
            applied.append({"ticker": ticker, "action": "sell", "shares": round(shares, 4), "price": held["price"]})
        else:
            price = book[ticker]["price"] if ticker in book else float(await get_price(ticker))
            if ticker in book:
                held = book[ticker]
                held["avg_cost"] = (held["avg_cost"] * held["shares"] + price * trade.shares) / (held["shares"] + trade.shares)
                held["shares"] += trade.shares
            else:
                rows = await run_sql(f"SELECT ticker, sector FROM companies WHERE ticker = '{ticker.replace(chr(39), '')}'")
                book[ticker] = {"shares": trade.shares, "avg_cost": price, "price": price,
                                "sector": rows[0]["sector"] if rows else None}
            cash_delta -= trade.shares * price
            applied.append({"ticker": ticker, "action": "buy", "shares": trade.shares, "price": price})

    if not book:
        return {"error": "The simulated trades would sell every position; nothing left to analyse."}
    after = compute_portfolio_metrics([Position(ticker=t, **v) for t, v in book.items()])
    return {
        "client_name": before["client_name"],
        "before": _side(before),
        "after": _side(after),
        "cash_delta": round(cash_delta, 2),
        "breaches_before": _breaches(before, threshold_pct),
        "breaches_after": _breaches(after, threshold_pct),
        "trades": applied,
    }


class SimulateInput(BaseModel):
    client_name: str = Field(description="Full or partial client name, e.g. 'Margaret Collins'.")
    trades: list[Trade] = Field(min_length=1, max_length=10, description="Hypothetical trades, applied in order.")


@tool("simulate_portfolio_change", args_schema=SimulateInput)
async def simulate_portfolio_change_tool(client_name: str, trades: list[Trade]) -> dict:
    """SIMULATE (never execute) buys/sells on one client's portfolio and show
    before/after weights, value, cash raised or needed, and concentration.
    Use for any "what if <client> sold/bought ..." question. Each trade is
    {ticker, action: buy|sell, pct (sell only) OR shares}."""
    from app.agent.mcp_clients.crm_client import crm_tool
    from app.agent.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"

    async def run_sql(sql: str) -> list[dict]:
        return parse_tool_payload(await crm_tool.ainvoke({"query": sql}))

    async def get_price(ticker: str) -> float:
        return price_from_quote(parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: ticker})))

    trades = [t if isinstance(t, Trade) else Trade(**t) for t in trades]
    return await simulate_change(run_sql=run_sql, get_price=get_price, client_name=client_name, trades=trades)
```

The expected weights in the tests come from: NVDA 100×200 = 20 000 and BND 100×70 = 7 000, so 27 000 in total and NVDA at 74.07 %. After selling 50 NVDA: 10 000 / 17 000 = 58.82 %.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_what_if.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools/what_if.py tests/unit/test_what_if.py
git commit -m "feat(portfolio): simulate_portfolio_change what-if tool (no DB writes)"
```

### Task 3: `watchlist_alerts` tool

**Files:**
- Create: `app/agent/tools/watchlist_alerts.py`
- Test: `tests/unit/test_watchlist_alerts.py`

**Interfaces:**
- Produces:
  - `build_watchlist_query(client_names: list[str] | None) -> str`;
  - `classify(price: float, alert_price: float, direction: str, near_pct: float) -> tuple[str, float]`, which returns `(status, distance_pct)`;
  - `async watchlist_alerts(*, run_sql, get_price, client_names: list[str] | None = None, near_pct: float = 5.0) -> dict`;
  - `watchlist_alerts_tool`.
- Return shape:
  ```
  {"near_pct": float, "rows": [{"client","ticker","company","price","alert_price","direction","status","distance_pct"}], "unpriced": [str]}
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_watchlist_alerts.py
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_watchlist_alerts.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# app/agent/tools/watchlist_alerts.py
"""`watchlist_alerts` — which client price alerts have fired, are close, or
are still waiting, against live prices. The status logic lives here so the
alert card is never an LLM's reading of a price table."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools.concentration import parse_tool_payload, price_from_quote

_ORDER = {"triggered": 0, "near": 1, "watching": 2}


def build_watchlist_query(client_names: list[str] | None) -> str:
    sql = (
        "SELECT c.name AS client, w.ticker, co.name AS company, w.alert_price, w.direction "
        "FROM watchlists w JOIN clients c ON c.client_id = w.client_id "
        "JOIN companies co ON co.ticker = w.ticker"
    )
    if client_names:
        likes = " OR ".join("c.name LIKE '%" + n.replace("'", "''") + "%'" for n in client_names)
        sql += f" WHERE ({likes})"
    return sql + " ORDER BY c.name, w.ticker"


def classify(price: float, alert_price: float, direction: str, near_pct: float) -> tuple[str, float]:
    distance = round((price - alert_price) / alert_price * 100, 2)
    crossed = price >= alert_price if direction == "above" else price <= alert_price
    if crossed:
        return "triggered", distance
    return ("near" if abs(distance) <= near_pct else "watching"), distance


async def watchlist_alerts(
    *,
    run_sql: Callable[[str], Awaitable[list[dict]]],
    get_price: Callable[[str], Awaitable[float]],
    client_names: list[str] | None = None,
    near_pct: float = 5.0,
) -> dict:
    alerts = await run_sql(build_watchlist_query(client_names))
    tickers = sorted({a["ticker"] for a in alerts})
    results = await asyncio.gather(*(get_price(t) for t in tickers), return_exceptions=True)
    prices = {t: float(r) for t, r in zip(tickers, results) if not isinstance(r, BaseException)}

    rows = []
    for a in alerts:
        if a["ticker"] not in prices:
            continue
        status, distance = classify(prices[a["ticker"]], float(a["alert_price"]), a["direction"], near_pct)
        rows.append({**a, "price": prices[a["ticker"]], "status": status, "distance_pct": distance})
    rows.sort(key=lambda r: (_ORDER[r["status"]], abs(r["distance_pct"]), r["client"]))
    return {"near_pct": float(near_pct), "rows": rows, "unpriced": sorted(set(tickers) - set(prices))}


class WatchlistAlertsInput(BaseModel):
    client_names: list[str] | None = Field(default=None, description="Only these clients (full or partial names). Omit for all clients.")
    near_pct: float = Field(default=5.0, gt=0, le=50, description="Within this % of the alert price counts as 'near'.")


@tool("watchlist_alerts", args_schema=WatchlistAlertsInput)
async def watchlist_alerts_tool(client_names: list[str] | None = None, near_pct: float = 5.0) -> dict:
    """Check clients' watchlist price alerts against live prices: which are
    triggered, near (within near_pct) or still watching. Use for any
    watchlist / price-alert question. Loads the alerts and prices itself --
    no SQL or price lookups first."""
    from app.agent.mcp_clients.crm_client import crm_tool
    from app.agent.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"

    async def run_sql(sql: str) -> list[dict]:
        return parse_tool_payload(await crm_tool.ainvoke({"query": sql}))

    async def get_price(ticker: str) -> float:
        return price_from_quote(parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: ticker})))

    return await watchlist_alerts(run_sql=run_sql, get_price=get_price, client_names=client_names, near_pct=near_pct)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_watchlist_alerts.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools/watchlist_alerts.py tests/unit/test_watchlist_alerts.py
git commit -m "feat(portfolio): watchlist_alerts tool (triggered / near / watching vs live prices)"
```

### Task 4: Display normalizers for the 3 tools and `read_query`

**Files:**
- Modify: `app/agent/display.py` (append after the existing `DISPLAY_NORMALIZERS[...] =` lines at the end of the file)
- Test: `tests/unit/test_display_normalizers.py` (append)

**Interfaces:**
- Consumes: the return shapes from Tasks 1–3. Normalizers receive `json.dumps(dict)` text for dict-returning tools.
- Produces these display payloads, which Task 6 mirrors in `types.ts`:
  - `{"type":"company_comparison","period","companies":[...same as tool...],"missing"}`
  - `{"type":"what_if", ...tool output minus nothing}`
  - `{"type":"watchlist_alerts","near_pct","rows","unpriced"}`
  - `{"type":"sql_table","columns":[str],"rows":[[...]],"truncated":bool}`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/unit/test_display_normalizers.py
def test_normalize_company_comparison_and_error():
    payload = {"period": "6mo", "missing": [], "companies": [{"symbol": "NVDA"}, {"symbol": "AMD"}]}
    out = display.DISPLAY_NORMALIZERS["compare_companies"](json.dumps(payload), {})
    assert out == [{"type": "company_comparison", **payload}]
    assert display.DISPLAY_NORMALIZERS["compare_companies"](json.dumps({"error": "x"}), {}) == []


def test_normalize_what_if_and_error():
    payload = {"client_name": "M", "before": {"positions": []}, "after": {"positions": []}, "cash_delta": 1.0,
               "breaches_before": [], "breaches_after": [], "trades": []}
    assert display.DISPLAY_NORMALIZERS["simulate_portfolio_change"](json.dumps(payload), {}) == [{"type": "what_if", **payload}]
    assert display.DISPLAY_NORMALIZERS["simulate_portfolio_change"](json.dumps({"error": "x"}), {}) == []


def test_normalize_watchlist_alerts_empty_rows_show_nothing():
    norm = display.DISPLAY_NORMALIZERS["watchlist_alerts"]
    assert norm(json.dumps({"near_pct": 5.0, "rows": [], "unpriced": []}), {}) == []
    row = {"client": "Ann", "ticker": "TSLA", "status": "triggered"}
    assert norm(json.dumps({"near_pct": 5.0, "rows": [row], "unpriced": []}), {}) == [
        {"type": "watchlist_alerts", "near_pct": 5.0, "rows": [row], "unpriced": []}]


def test_normalize_read_query_table():
    text = str([{"name": "Ann", "ticker": "TSLA"}, {"name": "Bob", "ticker": "TSLA"}])  # mcp-server-sqlite repr
    assert display.DISPLAY_NORMALIZERS["read_query"](text, {}) == [
        {"type": "sql_table", "columns": ["name", "ticker"], "rows": [["Ann", "TSLA"], ["Bob", "TSLA"]], "truncated": False}]


def test_normalize_read_query_hides_single_values_errors_and_empty():
    norm = display.DISPLAY_NORMALIZERS["read_query"]
    assert norm(str([{"email": "a@b.com"}]), {}) == []
    assert norm("[]", {}) == []
    assert norm("Error: only SELECT queries are allowed", {}) == []


def test_normalize_read_query_caps_at_50_rows():
    out = display.DISPLAY_NORMALIZERS["read_query"](str([{"n": i, "m": i} for i in range(60)]), {})
    assert len(out[0]["rows"]) == 50 and out[0]["truncated"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_display_normalizers.py -v -k "comparison or what_if or watchlist or read_query"`
Expected: FAIL with `KeyError: 'compare_companies'`.

- [ ] **Step 3: Implement (append to `app/agent/display.py`)**

```python
MAX_SQL_ROWS = 50


def _passthrough(display_type: str, required: str) -> Normalizer:
    """Tools that already return the card's exact shape: tag it, or show
    nothing when the tool returned an error / has nothing to show."""

    def normalize(text: str, args: dict) -> list[dict]:
        data = json.loads(text)
        if "error" in data or not data.get(required):
            return []
        return [{"type": display_type, **data}]

    return normalize


DISPLAY_NORMALIZERS["compare_companies"] = _passthrough("company_comparison", "companies")
DISPLAY_NORMALIZERS["simulate_portfolio_change"] = _passthrough("what_if", "after")
DISPLAY_NORMALIZERS["watchlist_alerts"] = _passthrough("watchlist_alerts", "rows")


def normalize_sql_table(text: str, args: dict) -> list[dict]:
    from app.agent.tools.concentration import parse_tool_payload

    try:
        rows = parse_tool_payload(text)
    except ValueError:
        return []  # error strings ("Error: ...") are not a result set
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        return []
    columns = list(rows[0].keys())
    if len(rows) == 1 and len(columns) == 1:
        return []  # a single looked-up value (e.g. an email address), not a table
    return [{
        "type": "sql_table",
        "columns": columns,
        "rows": [[r.get(c) for c in columns] for r in rows[:MAX_SQL_ROWS]],
        "truncated": len(rows) > MAX_SQL_ROWS,
    }]


DISPLAY_NORMALIZERS["read_query"] = normalize_sql_table
```

`"what_if"` keys on `"after"` because a valid simulation always has it, and the test payload's `"after"` is a non-empty dict. The required key only has to be truthy.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_display_normalizers.py -v`
Expected: all pass, the existing tests included.

- [ ] **Step 5: Commit**

```bash
git add app/agent/display.py tests/unit/test_display_normalizers.py
git commit -m "feat(display): normalizers for comparison, what-if, watchlist alerts and read_query tables"
```

### Task 5: Wire the tools into the specialists, registry, prompts and docs

**Files:**
- Modify:
  - `app/agent/tools/__init__.py` (imports, `TOOLS`, `_BASE_READ_ONLY_TOOLS`, `__all__`)
  - `app/agent/agents_specialist/finance_agent.py:14`
  - `app/agent/agents_specialist/portfolio_agent.py:26-36`
  - `app/agent/prompts/agents_specialist_prompts.py` (`FINANCE_SYSTEM_PROMPT`, `PORTFOLIO_SYSTEM_PROMPT`)
  - `app/agent/prompts/orchestration_prompt.py`
  - `docs/TOOLS.md`
  - `CLAUDE.md` (tool table and `READ_ONLY_TOOLS` line)
- Test:
  - `tests/unit/test_multi_agent_finance_agent.py`
  - `tests/unit/test_multi_agent_supervisor_routing.py`
  - `tests/unit/test_new_card_tools_wiring.py` (create)

**Interfaces:**
- Consumes: `compare_companies_tool`, `simulate_portfolio_change_tool`, `watchlist_alerts_tool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_new_card_tools_wiring.py
from app.agent import tools as tools_mod
from app.agent.agents_specialist import finance_agent, portfolio_agent
from app.agent.prompts.agents_specialist_prompts import FINANCE_SYSTEM_PROMPT, PORTFOLIO_SYSTEM_PROMPT
from app.agent.prompts.orchestration_prompt import SUPERVISOR_ROUTING_PROMPT


def _names(tools):
    return {t.name for t in tools}


def test_specialists_get_the_new_tools():
    assert "compare_companies" in _names(finance_agent._TOOLS)
    assert {"simulate_portfolio_change", "watchlist_alerts"} <= _names(portfolio_agent._TOOLS)


def test_new_tools_are_registered_read_only():
    for name in ("compare_companies", "simulate_portfolio_change", "watchlist_alerts"):
        assert name in _names(tools_mod.TOOLS)
        assert tools_mod.is_read_only(name)


def test_prompts_name_the_new_tools():
    assert "compare_companies" in FINANCE_SYSTEM_PROMPT
    assert "simulate_portfolio_change" in PORTFOLIO_SYSTEM_PROMPT
    assert "watchlist_alerts" in PORTFOLIO_SYSTEM_PROMPT
    assert "never an executed trade" in PORTFOLIO_SYSTEM_PROMPT


def test_routing_prompt_knows_the_new_intents():
    assert "compare two or more companies" in SUPERVISOR_ROUTING_PROMPT
    assert "what-if" in SUPERVISOR_ROUTING_PROMPT
    assert "watchlist" in SUPERVISOR_ROUTING_PROMPT
```

Check the name of the read-only helper before running:

```bash
grep -n "def is_read_only\|READ_ONLY_TOOLS" app/agent/tools/__init__.py
```

If the helper has a different name, use that name in the test. `middleware.tool_retry` imports it.

Also update the exact tool-set assertion in `tests/unit/test_multi_agent_finance_agent.py:19` so it includes `"compare_companies"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_new_card_tools_wiring.py tests/unit/test_multi_agent_finance_agent.py -v`
Expected: FAIL (tools missing).

- [ ] **Step 3: Implement**

`app/agent/tools/__init__.py`:
- add the imports next to the other `app.agent.tools.*` imports:
  ```python
  from app.agent.tools.compare_companies import compare_companies_tool
  from app.agent.tools.what_if import simulate_portfolio_change_tool
  from app.agent.tools.watchlist_alerts import watchlist_alerts_tool
  ```
- append the three tools to `TOOLS` after `save_portfolio_report_tool`;
- add `"compare_companies"`, `"simulate_portfolio_change"`, `"watchlist_alerts"` to `_BASE_READ_ONLY_TOOLS`;
- add `"compare_companies_tool"`, `"simulate_portfolio_change_tool"`, `"watchlist_alerts_tool"` to `__all__`.

`finance_agent.py`:

```python
from app.agent.tools import compare_companies_tool, yf_history_tool, yf_news_tool, yf_quote_tool

_TOOLS = [yf_quote_tool, yf_history_tool, yf_news_tool, compare_companies_tool]
```

`portfolio_agent.py`: add `simulate_portfolio_change_tool` and `watchlist_alerts_tool` to the import list and to the end of `_TOOLS`.

`FINANCE_SYSTEM_PROMPT`:
- after tool 3, add:
  ```
  4. `compare_companies` — side-by-side comparison of 2-4 tickers: price, market cap, P/E, 52-week range position and performance with a rebased chart (args: `symbols: list[str]`, optional `period`: "1mo" | "3mo" | "6mo" | "1y", default "6mo").
  ```
- in the guidelines, add:
  ```
  - For ANY "compare X and Y" / "X vs Y" / "which is better, X or Y" question, call `compare_companies` once with all the tickers — never call yfinance_get_ticker_info per ticker for a comparison.
  ```
- extend the cards sentence to: `...for every one of these 4 tools (price/stats card, price-history chart, news list, comparison table + chart)...`.

`PORTFOLIO_SYSTEM_PROMPT`: after tool 9, add:

```
10. `simulate_portfolio_change` — SIMULATE buys/sells on one named client's portfolio and get before/after weights, value, cash raised or needed and concentration (args: `client_name: str`, `trades`: list of `{ticker, action: "buy"|"sell", pct (sell only, % of the position) OR shares}`). Loads its own data.
11. `watchlist_alerts` — clients' watchlist price alerts vs live prices: triggered / near / watching (args, optional: `client_names: list[str]`, `near_pct: float` default 5). Loads its own data.
```

Then add to the instructions:

```
- What-if recipe: for "what if <client> sold/bought ..." / "simulate ..." call `simulate_portfolio_change` directly. A what-if is a simulation, never an executed trade: never say a trade was placed or executed.
- Watchlist recipe: for watchlist / price-alert questions call `watchlist_alerts` directly (with `client_names` when the user names clients) — no SQL first.
```

Finally, extend the final cards sentence with: `, for simulate_portfolio_change (before/after card), for watchlist_alerts (alert list) and for read_query result sets (table)`.

`orchestration_prompt.py`:
- in the `finance_agent` bullet, append:
  ```
  Also owns requests to compare two or more companies or tickers side by side ("compare NVDA and AMD", "NVDA vs AMD").
  ```
- in the `portfolio_agent` bullet, append:
  ```
  Also owns what-if simulations on a client's portfolio ("what if Margaret sold half her NVDA", "simulate selling 100 TSLA") and watchlist / price-alert questions ("which clients have triggered alerts").
  ```

`docs/TOOLS.md`:
- add summary rows 19–21 for `compare_companies` (finance), `simulate_portfolio_change` (portfolio) and `watchlist_alerts` (portfolio), all read-only and backed by "native Python over `read_query` / yfinance tools";
- add a per-tool section for each, with File, What and Why, written from this plan's Task 1–3 docstrings;
- add the three names to the `READ_ONLY_TOOLS` line.

`CLAUDE.md`: add three rows to the tool table with the same File, Type and description, and add the names to the `READ_ONLY_TOOLS = {...}` line.

- [ ] **Step 4: Run the tests to verify they pass, then probe the live router**

Run: `uv run pytest tests/ -q`
Expected: all pass.

Then run the live router probe. It is network-bound, takes about 2 minutes and costs a few cents:

```bash
cat > "$TMPDIR/route_probe_cards.py" <<'EOF'
import asyncio, collections
from langchain_core.messages import HumanMessage
from app.agent.orchestration.supervisor import router_agent
QS = {"Compare NVDA vs AMD": "finance_agent",
      "Which is better, Apple or Microsoft?": "finance_agent",
      "What if Margaret Collins sold half her NVDA?": "portfolio_agent",
      "Simulate selling 100 TSLA for Martin Levy": "portfolio_agent",
      "Which clients have triggered watchlist alerts?": "portfolio_agent"}
async def main():
    for q, want in QS.items():
        got = collections.Counter()
        for _ in range(3):
            r = await router_agent.ainvoke({"messages": [HumanMessage(q)]})
            got[r["structured_response"].next] += 1
        print("OK " if got[want] == 3 else "BAD", dict(got), q)
asyncio.run(main())
EOF
PYTHONPATH=. uv run python "$TMPDIR/route_probe_cards.py" 2>&1 | grep -E "^(OK|BAD)"
```

Expected: 5 lines starting with `OK`. If one says `BAD`, strengthen that prompt bullet, add an Example to `SUPERVISOR_ROUTING_PROMPT`, and re-probe.

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools/__init__.py app/agent/agents_specialist/finance_agent.py app/agent/agents_specialist/portfolio_agent.py app/agent/prompts/agents_specialist_prompts.py app/agent/prompts/orchestration_prompt.py docs/TOOLS.md CLAUDE.md tests/unit/test_new_card_tools_wiring.py tests/unit/test_multi_agent_finance_agent.py
git commit -m "feat(agents): wire comparison, what-if and watchlist tools into finance/portfolio + routing"
```

### Task 6: Frontend cards

**Files:**
- Modify:
  - `frontend/src/desk/displays/types.ts`
  - `frontend/src/desk/displays/parseDisplay.ts` (the `VALIDATORS` map)
  - `frontend/src/desk/displays/useToolDisplay.tsx` (`Rendered` switch + `DISPLAYABLE_TOOLS`)
- Create:
  - `frontend/src/desk/displays/CompanyComparisonCard.tsx` (+ `.test.tsx`)
  - `frontend/src/desk/displays/WhatIfCard.tsx` (+ `.test.tsx`)
  - `frontend/src/desk/displays/WatchlistAlertsCard.tsx` (+ `.test.tsx`)
  - `frontend/src/desk/displays/SqlResultTable.tsx` (+ `.test.tsx`)
- Test: `frontend/src/desk/displays/parseDisplay.test.ts` (append)

**Interfaces:**
- Consumes: the Task 4 payloads, keys in snake_case exactly as Python.

- [ ] **Step 1: Add the types**

Append these members to the `DisplayPayload` union in `types.ts`, before the final `;`:

```ts
  | { type: "company_comparison"; period: string; missing: string[]; companies: ComparedCompany[] }
  | { type: "what_if"; client_name: string; before: WhatIfSide; after: WhatIfSide; cash_delta: number; breaches_before: string[]; breaches_after: string[]; trades: { ticker: string; action: "buy" | "sell"; shares: number; price: number }[] }
  | { type: "watchlist_alerts"; near_pct: number; unpriced: string[]; rows: WatchlistRow[] }
  | { type: "sql_table"; columns: string[]; rows: unknown[][]; truncated: boolean }
```

Above the union, add:

```ts
export interface ComparedCompany {
  symbol: string; name: string; sector: string | null; currency: string; price: number;
  market_cap: number | null; trailing_pe: number | null; forward_pe: number | null;
  range_position_pct: number | null; period_return_pct: number;
  points: { date: string; value: number }[];
}
export interface WhatIfSide {
  totals: { market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number };
  positions: { ticker: string; weight_pct: number; market_value: number }[];
}
export interface WatchlistRow {
  client: string; ticker: string; company: string; price: number; alert_price: number;
  direction: "above" | "below"; status: "triggered" | "near" | "watching"; distance_pct: number;
}
```

- [ ] **Step 2: Write the failing tests**

```tsx
// frontend/src/desk/displays/CompanyComparisonCard.test.tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CompanyComparisonCard, mergeSeries } from "./CompanyComparisonCard";
import type { DisplayPayload } from "./types";

const company = (symbol: string, ret: number) => ({
  symbol, name: `${symbol} Inc.`, sector: "Technology", currency: "USD", price: 100, market_cap: 2.5e12,
  trailing_pe: 40, forward_pe: null, range_position_pct: 75, period_return_pct: ret,
  points: [{ date: "2026-04-01", value: 100 }, { date: "2026-10-01", value: 100 + ret }],
});
const display: Extract<DisplayPayload, { type: "company_comparison" }> = {
  type: "company_comparison", period: "6mo", missing: ["ZZZZ"], companies: [company("NVDA", 42.5), company("AMD", -3.1)],
};

describe("CompanyComparisonCard", () => {
  it("shows one column per company with its metrics", () => {
    render(<CompanyComparisonCard display={display} />);
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("AMD")).toBeInTheDocument();
    expect(screen.getByText("+42.5%")).toBeInTheDocument();
    expect(screen.getByText("-3.1%")).toBeInTheDocument();
    expect(screen.getByText("$2.50T")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0); // null forward P/E
    expect(screen.getByText(/No data for ZZZZ/)).toBeInTheDocument();
  });

  it("merges the rebased series by date for the chart", () => {
    expect(mergeSeries(display.companies)).toEqual([
      { date: "2026-04-01", NVDA: 100, AMD: 100 },
      { date: "2026-10-01", NVDA: 142.5, AMD: 96.9 },
    ]);
  });
});
```

```tsx
// frontend/src/desk/displays/WhatIfCard.test.tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { WhatIfCard } from "./WhatIfCard";
import type { DisplayPayload } from "./types";

const totals = (mv: number) => ({ market_value: mv, cost_basis: 1, unrealized_pnl: 0, unrealized_pnl_pct: 0 });
const display: Extract<DisplayPayload, { type: "what_if" }> = {
  type: "what_if", client_name: "Margaret Collins", cash_delta: 10000,
  before: { totals: totals(27000), positions: [{ ticker: "NVDA", weight_pct: 74.07, market_value: 20000 }, { ticker: "BND", weight_pct: 25.93, market_value: 7000 }] },
  after: { totals: totals(17000), positions: [{ ticker: "BND", weight_pct: 100, market_value: 7000 }] },
  breaches_before: ["NVDA"], breaches_after: [],
  trades: [{ ticker: "NVDA", action: "sell", shares: 100, price: 200 }],
};

describe("WhatIfCard", () => {
  it("shows before/after weights, cash raised and a resolved concentration", () => {
    render(<WhatIfCard display={display} />);
    expect(screen.getByText(/Margaret Collins/)).toBeInTheDocument();
    expect(screen.getByText(/Sell 100 NVDA/)).toBeInTheDocument();
    expect(screen.getByText("74.1%")).toBeInTheDocument();
    expect(screen.getByText("0.0%")).toBeInTheDocument(); // NVDA after: closed
    expect(screen.getByText(/Cash raised/)).toBeInTheDocument();
    expect(screen.getByText(/NVDA concentration resolved/)).toBeInTheDocument();
    expect(screen.getByText(/Simulation/)).toBeInTheDocument();
  });
});
```

```tsx
// frontend/src/desk/displays/WatchlistAlertsCard.test.tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { WatchlistAlertsCard } from "./WatchlistAlertsCard";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "watchlist_alerts" }> = {
  type: "watchlist_alerts", near_pct: 5, unpriced: ["XXXX"],
  rows: [
    { client: "Ann Lee", ticker: "TSLA", company: "Tesla", price: 460, alert_price: 450, direction: "above", status: "triggered", distance_pct: 2.22 },
    { client: "Bob Ray", ticker: "NVDA", company: "NVIDIA", price: 205, alert_price: 200, direction: "below", status: "near", distance_pct: 2.5 },
  ],
};

describe("WatchlistAlertsCard", () => {
  it("shows a status badge, the alert and the distance for each row", () => {
    render(<WatchlistAlertsCard display={display} />);
    expect(screen.getByText("Triggered")).toBeInTheDocument();
    expect(screen.getByText("Near")).toBeInTheDocument();
    expect(screen.getByText(/Ann Lee/)).toBeInTheDocument();
    expect(screen.getByText(/above \$450.00/)).toBeInTheDocument();
    expect(screen.getByText("+2.2%")).toBeInTheDocument();
    expect(screen.getByText(/No price for XXXX/)).toBeInTheDocument();
  });
});
```

```tsx
// frontend/src/desk/displays/SqlResultTable.test.tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SqlResultTable } from "./SqlResultTable";

describe("SqlResultTable", () => {
  it("renders headers, cells and the truncation note", () => {
    render(<SqlResultTable display={{ type: "sql_table", columns: ["name", "shares"], rows: [["Ann", 10], ["Bob", null]], truncated: true }} />);
    expect(screen.getByRole("columnheader", { name: "name" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Ann" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "10" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "—" })).toBeInTheDocument();
    expect(screen.getByText(/first 50 rows/)).toBeInTheDocument();
  });
});
```

Append to `parseDisplay.test.ts`, matching the file's existing `describe`/`it` style:

```ts
it("accepts the four new display types", () => {
  const raw = JSON.stringify({ summary: "s", displays: [
    { type: "company_comparison", period: "6mo", missing: [], companies: [] },
    { type: "what_if", client_name: "M", before: {}, after: {}, cash_delta: 0, breaches_before: [], breaches_after: [], trades: [] },
    { type: "watchlist_alerts", near_pct: 5, rows: [], unpriced: [] },
    { type: "sql_table", columns: ["a"], rows: [], truncated: false },
  ] });
  expect(parseDisplay(raw)?.displays.map((d) => d.type)).toEqual(["company_comparison", "what_if", "watchlist_alerts", "sql_table"]);
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/desk/displays`
Expected: FAIL (modules not found).

- [ ] **Step 4: Implement**

`parseDisplay.ts` — add to `VALIDATORS`:

```ts
  company_comparison: (d) => Array.isArray(d.companies),
  what_if: (d) => isRecord(d.before) && isRecord(d.after) && Array.isArray(d.trades),
  watchlist_alerts: (d) => Array.isArray(d.rows),
  sql_table: (d) => Array.isArray(d.columns) && Array.isArray(d.rows),
```

```tsx
// frontend/src/desk/displays/CompanyComparisonCard.tsx
import { Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatAxisDate } from "./PriceChart";
import type { ComparedCompany, DisplayPayload } from "./types";

const COLORS = ["#34d399", "#60a5fa", "#fbbf24", "#f87171"];

export function mergeSeries(companies: ComparedCompany[]): Record<string, string | number>[] {
  const byDate = new Map<string, Record<string, string | number>>();
  for (const c of companies) {
    for (const p of c.points) {
      const row = byDate.get(p.date) ?? { date: p.date };
      row[c.symbol] = p.value;
      byDate.set(p.date, row);
    }
  }
  return [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

function money(v: number | null): string {
  if (v === null) return "—";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  return `$${v.toLocaleString("en-US")}`;
}
const num = (v: number | null) => (v === null ? "—" : v.toFixed(1));
const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

export function CompanyComparisonCard({ display }: { display: Extract<DisplayPayload, { type: "company_comparison" }> }) {
  const rows: [string, (c: ComparedCompany) => string][] = [
    ["Price", (c) => `${c.price.toFixed(2)} ${c.currency}`],
    ["Market cap", (c) => money(c.market_cap)],
    ["P/E (trailing)", (c) => num(c.trailing_pe)],
    ["P/E (forward)", (c) => num(c.forward_pe)],
    ["52-week range", (c) => (c.range_position_pct === null ? "—" : `${c.range_position_pct.toFixed(0)}% of range`)],
    [`Return (${display.period})`, (c) => signed(c.period_return_pct)],
  ];
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 font-mono text-xs text-terminal-text">
      <div className="mb-2 font-semibold">Comparison · {display.period}</div>
      <table className="w-full">
        <thead>
          <tr>
            <th className="text-left text-terminal-muted font-normal" />
            {display.companies.map((c, i) => (
              <th key={c.symbol} className="text-right" style={{ color: COLORS[i % COLORS.length] }}>{c.symbol}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, cell]) => (
            <tr key={label}>
              <td className="py-0.5 text-terminal-muted">{label}</td>
              {display.companies.map((c) => <td key={c.symbol} className="py-0.5 text-right">{cell(c)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={mergeSeries(display.companies)} margin={{ top: 5, right: 12, bottom: 5, left: 0 }}>
            <XAxis dataKey="date" tickFormatter={formatAxisDate} tick={{ fill: "#6b7a8d", fontSize: 10 }} />
            <YAxis domain={["auto", "auto"]} tick={{ fill: "#6b7a8d", fontSize: 10 }} width={40} />
            <Tooltip contentStyle={{ background: "#0f1620", border: "1px solid #1c2733", fontSize: 11 }} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            {display.companies.map((c, i) => (
              <Line key={c.symbol} type="monotone" dataKey={c.symbol} stroke={COLORS[i % COLORS.length]} dot={false} strokeWidth={2} connectNulls />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 text-[10px] text-terminal-muted">Prices rebased to 100 at the start of the period.</div>
      {display.missing.length > 0 && <div className="mt-1 text-terminal-warn">No data for {display.missing.join(", ")}</div>}
    </div>
  );
}
```

```tsx
// frontend/src/desk/displays/WhatIfCard.tsx
import type { DisplayPayload } from "./types";

const usd = (v: number) => v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function WhatIfCard({ display }: { display: Extract<DisplayPayload, { type: "what_if" }> }) {
  const tickers = [...new Set([...display.before.positions, ...display.after.positions].map((p) => p.ticker))];
  const weight = (side: typeof display.before, t: string) => side.positions.find((p) => p.ticker === t)?.weight_pct ?? 0;
  const resolved = display.breaches_before.filter((t) => !display.breaches_after.includes(t));
  const introduced = display.breaches_after.filter((t) => !display.breaches_before.includes(t));
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 font-mono text-xs text-terminal-text">
      <div className="mb-1 font-semibold">What-if · {display.client_name}</div>
      <div className="mb-2 text-terminal-muted">
        Simulation only, nothing executed ·{" "}
        {display.trades.map((t) => `${t.action === "sell" ? "Sell" : "Buy"} ${t.shares} ${t.ticker}`).join(", ")}
      </div>
      <div className="flex flex-col gap-1.5">
        {tickers.map((t) => {
          const b = weight(display.before, t);
          const a = weight(display.after, t);
          return (
            <div key={t} className="grid grid-cols-[4rem_1fr_3.5rem_3.5rem] items-center gap-2">
              <span>{t}</span>
              <div className="flex flex-col gap-0.5">
                <div className="h-1.5 rounded bg-terminal-muted/40" style={{ width: `${b}%` }} />
                <div className="h-1.5 rounded bg-terminal-accent" style={{ width: `${a}%` }} />
              </div>
              <span className="text-right text-terminal-muted">{b.toFixed(1)}%</span>
              <span className="text-right">{a.toFixed(1)}%</span>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between border-t border-terminal-border pt-2">
        <span>Value {usd(display.before.totals.market_value)} → {usd(display.after.totals.market_value)}</span>
        <span>{display.cash_delta >= 0 ? "Cash raised" : "Cash needed"} {usd(Math.abs(display.cash_delta))}</span>
      </div>
      {resolved.map((t) => <div key={`r-${t}`} className="mt-1 text-terminal-accent">✓ {t} concentration resolved</div>)}
      {introduced.map((t) => <div key={`n-${t}`} className="mt-1 text-terminal-warn">⚠ {t} becomes a concentration risk</div>)}
      {display.breaches_after.filter((t) => display.breaches_before.includes(t)).map((t) => (
        <div key={`s-${t}`} className="mt-1 text-terminal-warn">⚠ {t} still over 30%</div>
      ))}
    </div>
  );
}
```

```tsx
// frontend/src/desk/displays/WatchlistAlertsCard.tsx
import type { DisplayPayload, WatchlistRow } from "./types";

const BADGE: Record<WatchlistRow["status"], { label: string; cls: string }> = {
  triggered: { label: "Triggered", cls: "bg-red-500/15 text-red-400" },
  near: { label: "Near", cls: "bg-amber-500/15 text-amber-400" },
  watching: { label: "Watching", cls: "bg-terminal-muted/15 text-terminal-muted" },
};

export function WatchlistAlertsCard({ display }: { display: Extract<DisplayPayload, { type: "watchlist_alerts" }> }) {
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 font-mono text-xs text-terminal-text">
      <div className="mb-2 font-semibold">Watchlist alerts · near = within {display.near_pct}%</div>
      <div className="flex flex-col gap-1.5">
        {display.rows.map((r) => (
          <div key={`${r.client}-${r.ticker}`} className="grid grid-cols-[5.5rem_1fr_auto] items-center gap-2">
            <span className={`rounded px-1.5 py-0.5 text-center text-[10px] font-semibold ${BADGE[r.status].cls}`}>{BADGE[r.status].label}</span>
            <span>
              {r.client} — {r.ticker} ${r.price.toFixed(2)}{" "}
              <span className="text-terminal-muted">({r.direction} ${r.alert_price.toFixed(2)})</span>
            </span>
            <span className="text-right">{`${r.distance_pct > 0 ? "+" : ""}${r.distance_pct.toFixed(1)}%`}</span>
          </div>
        ))}
      </div>
      {display.unpriced.length > 0 && <div className="mt-2 text-terminal-muted">No price for {display.unpriced.join(", ")}</div>}
    </div>
  );
}
```

```tsx
// frontend/src/desk/displays/SqlResultTable.tsx
import type { DisplayPayload } from "./types";

const cell = (v: unknown) => (v === null || v === undefined ? "—" : String(v));

export function SqlResultTable({ display }: { display: Extract<DisplayPayload, { type: "sql_table" }> }) {
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 font-mono text-xs text-terminal-text">
      <div className="max-h-72 overflow-auto">
        <table className="w-full">
          <thead>
            <tr>{display.columns.map((c) => <th key={c} className="sticky top-0 bg-terminal-panel px-2 py-1 text-left text-terminal-muted">{c}</th>)}</tr>
          </thead>
          <tbody>
            {display.rows.map((row, i) => (
              <tr key={i} className="border-t border-terminal-border/50">
                {row.map((v, j) => <td key={j} className={`px-2 py-1 ${typeof v === "number" ? "text-right" : ""}`}>{cell(v)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {display.truncated && <div className="mt-1 text-terminal-muted">Showing the first 50 rows.</div>}
    </div>
  );
}
```

`useToolDisplay.tsx`:
- import the four cards;
- add these to the `Rendered` switch:
  ```tsx
  case "company_comparison": return <CompanyComparisonCard key={i} display={d} />;
  case "what_if": return <WhatIfCard key={i} display={d} />;
  case "watchlist_alerts": return <WatchlistAlertsCard key={i} display={d} />;
  case "sql_table": return <SqlResultTable key={i} display={d} />;
  ```
- append `"compare_companies"`, `"simulate_portfolio_change"`, `"watchlist_alerts"`, `"read_query"` to `DISPLAYABLE_TOOLS`;
- update the comment above `useToolDisplay`: `read_query` is no longer in the "left to the default card" list.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/desk && npx tsc --noEmit -p .`
Expected: all pass, no type errors. If `useToolDisplay.test.tsx` asserts the exact `DISPLAYABLE_TOOLS` list, add the four names there.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/desk/displays
git commit -m "feat(desk): comparison, what-if, watchlist alert and SQL table cards"
```

### Task 7: Starter suggestions

**Files:**
- Modify:
  - `frontend/src/desk/DeskView.tsx`
  - `frontend/src/clients/ClientWorkspace.tsx:157`
- Test: `frontend/src/desk/DeskView.test.tsx` (replace the `"does not register persistent prompt suggestions"` test)

**Interfaces:**
- Produces:
  - the `DeskView` prop `starterSuggestions?: { title: string; message: string }[]`, defaulting to `RESEARCH_STARTERS`;
  - the exported constants `RESEARCH_STARTERS` and `CLIENT_STARTERS`.

- [ ] **Step 1: Write the failing tests** (replace the old test)

```tsx
  it("offers starter suggestions only before the first message", () => {
    render(<DeskView threadId="research_3" />);
    const config = suggestionConfigs[suggestionConfigs.length - 1] as {
      available: string; suggestions: { title: string; message: string }[];
    };
    expect(config.available).toBe("before-first-message");
    expect(config.suggestions.map((s) => s.title)).toEqual([
      "Compare NVDA vs AMD",
      "Triggered watchlist alerts",
      "What if Margaret sold half her NVDA?",
      "Who holds Tesla?",
    ]);
  });

  it("uses the starters passed by the page", () => {
    render(<DeskView threadId="clients_4" starterSuggestions={[{ title: "T", message: "M" }]} />);
    const config = suggestionConfigs[suggestionConfigs.length - 1] as { suggestions: unknown[] };
    expect(config.suggestions).toEqual([{ title: "T", message: "M" }]);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/desk/DeskView.test.tsx`
Expected: FAIL (no suggestions registered).

- [ ] **Step 3: Implement**

In `DeskView.tsx`:
- add `useConfigureSuggestions` to the `@copilotkit/react-core/v2` import;
- add the constants:
  ```tsx
  export type StarterSuggestion = { title: string; message: string };

  export const RESEARCH_STARTERS: StarterSuggestion[] = [
    { title: "Compare NVDA vs AMD", message: "Compare NVDA vs AMD" },
    { title: "Triggered watchlist alerts", message: "Which clients have triggered watchlist alerts?" },
    { title: "What if Margaret sold half her NVDA?", message: "What if Margaret Collins sold half her NVDA?" },
    { title: "Who holds Tesla?", message: "Which clients hold Tesla?" },
  ];

  export const CLIENT_STARTERS: StarterSuggestion[] = [
    { title: "Summarize this portfolio", message: "Summarize this client's portfolio" },
    { title: "Watchlist alerts", message: "Any watchlist alerts for this client?" },
    { title: "Sell half the largest position?", message: "What if this client sold half of their largest position?" },
  ];
  ```
- add `starterSuggestions?: StarterSuggestion[]` to `DeskViewProps`, default it to `RESEARCH_STARTERS`, and pass it down to `DeskBody` as a prop;
- in `DeskBody`, after `useToolDisplay();`:
  ```tsx
  // Before the first message only: commit 740ef53 removed suggestions that
  // stayed on screen for the whole conversation ("always").
  useConfigureSuggestions({ suggestions: starterSuggestions, available: "before-first-message" }, [starterSuggestions]);
  ```

In `ClientWorkspace.tsx:157`:

```tsx
<DeskView threadId={`clients_${clientId}`} voiceEnabled={false} starterSuggestions={CLIENT_STARTERS} />
```

and import `CLIENT_STARTERS` from `../desk/DeskView`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/desk src/clients && npx tsc --noEmit -p .`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/desk/DeskView.tsx frontend/src/desk/DeskView.test.tsx frontend/src/clients/ClientWorkspace.tsx
git commit -m "feat(desk): starter suggestions before the first message (research + client variants)"
```

### Task 8: Phase A live check

**Files:** none. This task only verifies.

- [ ] **Step 1: Restart the backend**

Restart without `--reload`:
- stop the process listening on :8000;
- `uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000` in the background;
- wait for `curl -s localhost:8000/health` to return `{"status":"ok",...}`.

- [ ] **Step 2: Click the starters in the real browser**

Open `http://127.0.0.1:5173/research` with a fresh session ("New session"), then:
1. Click "Compare NVDA vs AMD". Expect a comparison table and a 2-line chart.
2. Start a new session and click "Triggered watchlist alerts". Expect the alert list with badges.
3. Start a new session and click "What if Margaret sold half her NVDA?". Expect before/after bars and cash raised, with no "executed" claim in the text.
4. Start a new session and click "Who holds Tesla?". Expect an SQL table.

In each case the starters disappear after the first message.

Record any failure and fix it in the owning task's files before moving on. Use only `qa_*` / fresh `desk_*` threads, never `clients_<id>` real threads.

- [ ] **Step 3: Commit any fixes**, with a message describing them.

---

## Phase B

### Task 9: AG-UI state plumbing and `ui_context_prompt`

**Files:**
- Modify:
  - `app/agent/orchestration/state.py`
  - `app/agent/middleware.py` (add `ui_context_prompt` next to `client_context_prompt`)
  - `app/agent/orchestration/supervisor.py` (router middleware list; stage only this hunk)
  - `app/agent/agents_specialist/portfolio_agent.py`
  - `app/agent/agents_specialist/finance_agent.py`
  - `app/agent/agents_specialist/rag_agent.py`
- Test: `tests/unit/test_ag_ui_state.py` (create)

**Interfaces:**
- Produces:
  - `AG_UI_KEY = "ag-ui"` in `state.py`;
  - `AgUiState` (`TypedDict` with the `"ag-ui"` key, `total=False`), inherited by `SupervisorState` and `ClientContextState`;
  - `ui_context_prompt` (a `@dynamic_prompt` middleware);
  - `def ui_context_lines(state) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ag_ui_state.py
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.middleware import ui_context_lines
from app.agent.orchestration.state import AG_UI_KEY, ClientContextState, SupervisorState


def test_graph_state_keeps_the_ag_ui_key():
    seen = {}

    def node(state):
        seen.update(state.get(AG_UI_KEY) or {})
        return {}

    g = StateGraph(SupervisorState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    app = g.compile(checkpointer=InMemorySaver())
    app.invoke({"messages": [], AG_UI_KEY: {"context": [{"description": "Page", "value": "research"}]}},
               {"configurable": {"thread_id": "t"}})
    assert seen == {"context": [{"description": "Page", "value": "research"}]}


def test_specialist_state_declares_the_key():
    assert AG_UI_KEY in ClientContextState.__annotations__ or AG_UI_KEY in ClientContextState.__optional_keys__


def test_ui_context_lines():
    state = {AG_UI_KEY: {"context": [{"description": "Selected position", "value": '{"ticker": "NVDA"}'},
                                     {"description": "", "value": ""}]}}
    assert ui_context_lines(state) == ['- Selected position: {"ticker": "NVDA"}']
    assert ui_context_lines({}) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ag_ui_state.py -v`
Expected: FAIL (`ImportError: AG_UI_KEY`).

- [ ] **Step 3: Implement**

In `state.py`, add at the top after the imports:

```python
AG_UI_KEY = "ag-ui"

# ag-ui-langgraph merges {"ag-ui": {"tools": [...], "context": [...]}} into
# the run input (CopilotKit's useAgentContext entries land in "context").
# LangGraph drops undeclared keys, so the key must be part of the schema;
# a hyphenated key needs the functional TypedDict form.
AgUiState = TypedDict("AgUiState", {AG_UI_KEY: Optional[dict]}, total=False)
```

Then change the class headers:
- `class SupervisorState(AgUiState):`
- `class ClientContextState(AgentState, AgUiState):`

If `class ClientContextState(AgentState, AgUiState)` raises at import, because typing rejects mixing a `total=False` functional TypedDict with `AgentState`, declare the key on `ClientContextState` as `__annotations__[AG_UI_KEY] = NotRequired[Optional[dict]]` instead, and keep the test.

In `middleware.py`, next to `client_context_prompt`:

```python
def ui_context_lines(state) -> list[str]:
    """CopilotKit useAgentContext entries (state["ag-ui"]["context"]) as
    prompt lines. Absent outside the Market Desk AG-UI transport."""
    from app.agent.orchestration.state import AG_UI_KEY

    entries = ((state or {}).get(AG_UI_KEY) or {}).get("context") or []
    return [
        f"- {e['description']}: {e['value']}"
        for e in entries
        if isinstance(e, dict) and e.get("description") and e.get("value")
    ]


@dynamic_prompt
def ui_context_prompt(request: ModelRequest) -> str:
    base = request.system_prompt or ""
    lines = ui_context_lines(request.state)
    if not lines:
        return base
    return f"{base}\n\nWhat the user is looking at in the app right now:\n" + "\n".join(lines)
```

Wiring:
- add `ui_context_prompt` right after `client_context_prompt` in the middleware lists of portfolio, finance and rag;
- in `build_router_agent` (`supervisor.py`), add it after `client_context_routing_prompt`.

`supervisor.py` has unrelated uncommitted edits. Stage it with `git add -p app/agent/orchestration/supervisor.py` and accept only the import line and the middleware-list line.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ag_ui_state.py -v && uv run pytest tests/ -q`
Expected: all pass.

Then confirm that a real AG-UI run carries the key end to end. Restart the backend as in Task 8, and post one run with a context entry:

```bash
curl -s -N -X POST localhost:8000/copilot/market-desk -H 'Content-Type: application/json' -d '{
 "threadId":"qa_agui_ctx_1","runId":"r1","state":{},"tools":[],"forwardedProps":{},
 "context":[{"description":"Selected position","value":"{\"ticker\":\"NVDA\"}"}],
 "messages":[{"id":"m1","role":"user","content":"What position am I looking at? Answer with the ticker only."}]}' | grep -o 'NVDA' | head -1
```

Expected: `NVDA`. If `/copilot/market-desk` is disabled, set `COPILOT_ENABLED=true` in `.env`.

- [ ] **Step 5: Commit**

```bash
git add app/agent/orchestration/state.py app/agent/middleware.py app/agent/agents_specialist/portfolio_agent.py app/agent/agents_specialist/finance_agent.py app/agent/agents_specialist/rag_agent.py tests/unit/test_ag_ui_state.py
git add -p app/agent/orchestration/supervisor.py
git commit -m "feat(agents): carry CopilotKit context (state['ag-ui']) into router and specialist prompts"
```

### Task 10: `useAgentContext` on Research and Client pages

**Files:**
- Create:
  - `frontend/src/desk/lastCardContext.ts` (+ `.test.ts`)
  - `frontend/src/clients/HoldingsStrip.tsx` (+ `.test.tsx`)
- Modify:
  - `frontend/src/desk/DeskView.tsx`
  - `frontend/src/clients/ClientWorkspace.tsx`
- Test: `frontend/src/desk/DeskView.test.tsx` (append; add `useAgentContext` to the mock)

**Interfaces:**
- Consumes:
  - `parseDisplay` from `./displays/parseDisplay`;
  - message shape from `agent.messages`: tool messages are `{role: "tool", content: string}`.
- Produces:
  - `lastCardContext(messages: { role?: string; content?: unknown }[]): string | null`;
  - `DeskView` prop `agentContext?: { description: string; value: string }[]`;
  - `HoldingsStrip({ positions, selected, onSelect })`.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/desk/lastCardContext.test.ts
import { describe, expect, it } from "vitest";
import { lastCardContext } from "./lastCardContext";

const tool = (displays: unknown[]) => ({ role: "tool", content: JSON.stringify({ summary: "s", displays }) });

describe("lastCardContext", () => {
  it("summarizes the most recent card's key fields", () => {
    const msgs = [
      tool([{ type: "watchlist_alerts", near_pct: 5, rows: [{ client: "Ann" }], unpriced: [] }]),
      { role: "assistant", content: "ok" },
      tool([{ type: "company_comparison", period: "6mo", missing: [], companies: [{ symbol: "NVDA" }, { symbol: "AMD" }] }]),
    ];
    expect(lastCardContext(msgs)).toBe('{"card":"company_comparison","symbols":["NVDA","AMD"],"period":"6mo"}');
  });

  it("describes a what-if by client and trades", () => {
    const msgs = [tool([{ type: "what_if", client_name: "Margaret Collins", before: {}, after: {}, cash_delta: 0,
      breaches_before: [], breaches_after: [], trades: [{ ticker: "NVDA", action: "sell", shares: 50, price: 1 }] }])];
    expect(lastCardContext(msgs)).toBe('{"card":"what_if","client":"Margaret Collins","trades":["sell 50 NVDA"]}');
  });

  it("returns null without cards", () => {
    expect(lastCardContext([{ role: "user", content: "hi" }])).toBeNull();
  });
});
```

```tsx
// frontend/src/clients/HoldingsStrip.test.tsx
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { HoldingsStrip } from "./HoldingsStrip";

const positions = [{ ticker: "NVDA", weight_pct: 57.5 }, { ticker: "BND", weight_pct: 42.5 }];

describe("HoldingsStrip", () => {
  it("selects and unselects a position", () => {
    const onSelect = vi.fn();
    const { rerender } = render(<HoldingsStrip positions={positions} selected={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /NVDA/ }));
    expect(onSelect).toHaveBeenLastCalledWith("NVDA");
    rerender(<HoldingsStrip positions={positions} selected="NVDA" onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: /NVDA/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /NVDA/ }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });
});
```

Append to `DeskView.test.tsx`:
- add `useAgentContext: (c: Record<string, unknown>) => { agentContexts.push(c); },` to the `vi.mock` factory;
- declare `const agentContexts: Record<string, unknown>[] = [];` at the top and reset it in `beforeEach`;
- add the test:
  ```tsx
  it("shares page context entries with the agent", () => {
    render(<DeskView threadId="clients_4" agentContext={[{ description: "Selected position", value: "{\"ticker\":\"NVDA\"}" }]} />);
    expect(agentContexts).toContainEqual({ description: "Selected position", value: "{\"ticker\":\"NVDA\"}" });
  });
  ```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/desk/lastCardContext.test.ts src/clients/HoldingsStrip.test.tsx src/desk/DeskView.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

```ts
// frontend/src/desk/lastCardContext.ts
import { parseDisplay } from "./displays/parseDisplay";
import type { DisplayPayload } from "./displays/types";

function keyFields(d: DisplayPayload): Record<string, unknown> | null {
  switch (d.type) {
    case "company_comparison": return { card: d.type, symbols: d.companies.map((c) => c.symbol), period: d.period };
    case "what_if": return { card: d.type, client: d.client_name, trades: d.trades.map((t) => `${t.action} ${t.shares} ${t.ticker}`) };
    case "watchlist_alerts": return { card: d.type, clients: [...new Set(d.rows.map((r) => r.client))] };
    case "portfolio_table": return { card: d.type, tickers: d.positions.map((p) => p.ticker) };
    case "ticker_info": return { card: d.type, ticker: d.ticker };
    case "price_chart": return { card: d.type, ticker: d.ticker };
    default: return null;
  }
}

// The newest rich card in the chat, so "add AMD" / "now 25% instead" has a referent.
export function lastCardContext(messages: { role?: string; content?: unknown }[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role !== "tool") continue;
    const env = parseDisplay(messages[i].content);
    for (const d of env?.displays ?? []) {
      const fields = keyFields(d);
      if (fields) return JSON.stringify(fields);
    }
  }
  return null;
}
```

```tsx
// frontend/src/clients/HoldingsStrip.tsx
export function HoldingsStrip({
  positions, selected, onSelect,
}: {
  positions: { ticker: string; weight_pct: number }[];
  selected: string | null;
  onSelect: (ticker: string | null) => void;
}) {
  if (positions.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2" aria-label="Holdings">
      {positions.map((p) => {
        const on = p.ticker === selected;
        return (
          <button
            key={p.ticker}
            type="button"
            aria-pressed={on}
            onClick={() => onSelect(on ? null : p.ticker)}
            className={`rounded-full border px-3 py-1 font-mono text-xs transition-colors ${on ? "border-terminal-accent bg-terminal-accent/15 text-terminal-text" : "border-terminal-border text-terminal-muted hover:text-terminal-text"}`}
          >
            {p.ticker} · {p.weight_pct.toFixed(1)}%
          </button>
        );
      })}
    </div>
  );
}
```

In `DeskView.tsx`:
- add `useAgentContext` and `useAgent` to the v2 import;
- add `agentContext?: { description: string; value: string }[]` to `DeskViewProps` and pass it to `DeskBody`;
- in `DeskBody`, add the following. `useAgentContext` is called with a stable count: one fixed call for the last card, plus one per entry of `agentContext`, through a child component per entry, so the hook-count rule holds when the list changes:
  ```tsx
  function ContextEntry({ description, value }: { description: string; value: string }) {
    useAgentContext({ description, value });
    return null;
  }

  function LastCardContext() {
    const { agent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
    const value = lastCardContext((agent?.messages ?? []) as { role?: string; content?: unknown }[]);
    useAgentContext({ description: "Most recent card shown in the chat", value: value ?? "none" });
    return null;
  }
  ```
- render `<LastCardContext />` and `{agentContext?.map((c) => <ContextEntry key={c.description} {...c} />)}` inside `DeskBody`'s fragment;
- update the `@copilotkit/react-core/v2` mock in `DeskView.test.tsx`:
  - `useAgent` returns `{ agent: { messages: [], subscribe: ... } }`;
  - `useAgentContext` records to `agentContexts`.

In `ClientWorkspace.tsx` (`ClientWorkspaceBody`):
- `const [selected, setSelected] = useState<string | null>(null);`;
- render `<HoldingsStrip positions={summary.positions} selected={selected} onSelect={setSelected} />` under `<PortfolioMetrics summary={summary} />`;
- build the context:
  ```tsx
  const agentContext = [
    { description: "Client workspace on screen", value: JSON.stringify({ client: summary.name, totals: summary.totals, priced_positions: summary.positions.length }) },
    ...(selected ? [{ description: "Selected position", value: JSON.stringify(summary.positions.find((p) => p.ticker === selected)) }] : []),
  ];
  ```
- pass `agentContext={agentContext}` to `<DeskView ... />`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src && npx tsc --noEmit -p .`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/desk/lastCardContext.ts frontend/src/desk/lastCardContext.test.ts frontend/src/clients/HoldingsStrip.tsx frontend/src/clients/HoldingsStrip.test.tsx frontend/src/desk/DeskView.tsx frontend/src/desk/DeskView.test.tsx frontend/src/clients/ClientWorkspace.tsx
git commit -m "feat(desk): share last card and selected client position with the agent (useAgentContext)"
```

### Task 11: `ask_user_choice` tool and gating middleware

**Files:**
- Create:
  - `app/agent/tools/user_choice.py`
  - `tests/unit/test_user_choice.py`
- Modify:
  - `app/agent/middleware.py` (add `OnlyOnAgUi`)
  - `app/agent/tools/__init__.py` (`TOOLS` and `__all__`; NOT read-only)
  - `app/agent/agents_specialist/portfolio_agent.py`
  - `app/agent/agents_specialist/finance_agent.py`
  - `app/agent/agents_specialist/email_agent.py`
  - `app/agent/prompts/agents_specialist_prompts.py`
  - `docs/TOOLS.md`
  - `CLAUDE.md`

**Interfaces:**
- Produces:
  - `ask_user_choice_tool` (tool name `ask_user_choice`);
  - `build_choice_payload(question, options, multi, allow_other) -> dict`;
  - `OnlyOnAgUi(tool_names: set[str])` middleware.
- Interrupt payload: `{"type": "user_choice", "question": str, "options": [{"id": str, "label": str}], "multi": bool, "allow_other": bool}`.
- Resume value: `{"selected": [str], "other": str | None}`. The tool returns this as JSON text.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_user_choice.py
import json
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from langchain_core.messages import AIMessage

from app.agent.middleware import OnlyOnAgUi
from app.agent.tools import is_read_only
from app.agent.tools.user_choice import ask_user_choice_tool, build_choice_payload


def test_payload_shape_and_ids():
    p = build_choice_payload("Which client?", ["Ann Lee", "Ann Moss"], multi=False, allow_other=False)
    assert p == {"type": "user_choice", "question": "Which client?", "multi": False, "allow_other": False,
                 "options": [{"id": "0", "label": "Ann Lee"}, {"id": "1", "label": "Ann Moss"}]}


def test_payload_needs_two_options():
    with pytest.raises(ValueError):
        build_choice_payload("Q", ["only"], multi=False, allow_other=False)


def test_tool_interrupts_then_returns_resume_value():
    g = StateGraph(MessagesState)
    g.add_node("tools", ToolNode([ask_user_choice_tool]))
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    app = g.compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "c1"}}
    call = AIMessage(content="", tool_calls=[{"id": "t1", "name": "ask_user_choice",
                                              "args": {"question": "Which?", "options": ["A", "B"]}}])
    first = app.invoke({"messages": [call]}, cfg)
    assert first["__interrupt__"][0].value["type"] == "user_choice"
    done = app.invoke(Command(resume={"selected": ["1"], "other": None}), cfg)
    assert json.loads(done["messages"][-1].content) == {"selected": ["B"], "other": None}


def test_not_read_only_so_tool_retry_never_wraps_the_interrupt():
    assert not is_read_only("ask_user_choice")


def _request(state, names):
    tools = [SimpleNamespace(name=n) for n in names]
    captured = {}

    def override(**kw):
        captured.update(kw)
        return SimpleNamespace(tools=kw.get("tools", tools))

    return SimpleNamespace(state=state, tools=tools, override=override), captured


def test_gate_removes_choice_tool_without_ag_ui():
    mw = OnlyOnAgUi({"ask_user_choice"})
    req, _ = _request({}, ["read_query", "ask_user_choice"])
    seen = mw.wrap_model_call(req, lambda r: r)
    assert [t.name for t in seen.tools] == ["read_query"]


def test_gate_keeps_choice_tool_on_ag_ui():
    mw = OnlyOnAgUi({"ask_user_choice"})
    req, _ = _request({"ag-ui": {"context": []}}, ["read_query", "ask_user_choice"])
    seen = mw.wrap_model_call(req, lambda r: r)
    assert [t.name for t in seen.tools] == ["read_query", "ask_user_choice"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_user_choice.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# app/agent/tools/user_choice.py
"""`ask_user_choice` — pause the run and ask the user to pick from options.

Uses LangGraph interrupt(): the run stops, Market Desk renders a choice card
(useDeskInterrupt), and Command(resume={"selected": [...], "other": ...})
continues the SAME tool call through the checkpointer -- same mechanism as
HITL approvals. Only offered on the Market Desk AG-UI transport (see
middleware.OnlyOnAgUi). Deliberately NOT in READ_ONLY_TOOLS: tool_retry wraps
read-only tools and would catch the GraphInterrupt."""

from __future__ import annotations

import json

from langchain_core.tools import tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field


def build_choice_payload(question: str, options: list[str], *, multi: bool, allow_other: bool) -> dict:
    labels = [o.strip() for o in options if o and o.strip()]
    if len(labels) < 2:
        raise ValueError("ask_user_choice needs at least 2 options")
    return {
        "type": "user_choice",
        "question": question,
        "options": [{"id": str(i), "label": label} for i, label in enumerate(labels)],
        "multi": multi,
        "allow_other": allow_other,
    }


class AskUserChoiceInput(BaseModel):
    question: str = Field(description="The question to show, e.g. 'Which client did you mean?'.")
    options: list[str] = Field(min_length=2, max_length=12, description="The choices to show as buttons.")
    multi: bool = Field(default=False, description="True to let the user tick several options.")
    allow_other: bool = Field(default=False, description="True to add a free-text 'Other' answer.")


@tool("ask_user_choice", args_schema=AskUserChoiceInput)
def ask_user_choice_tool(question: str, options: list[str], multi: bool = False, allow_other: bool = False) -> str:
    """Ask the user to choose between options shown as buttons (or checkboxes
    when multi=True), and wait for the answer. Use it instead of asking in
    plain text when the choice is between known options: an ambiguous client
    name, a missing trade size, or which clients to include."""
    payload = build_choice_payload(question, options, multi=multi, allow_other=allow_other)
    answer = interrupt(payload) or {}
    by_id = {o["id"]: o["label"] for o in payload["options"]}
    return json.dumps({
        "selected": [by_id[i] for i in answer.get("selected", []) if i in by_id],
        "other": answer.get("other") or None,
    })
```

In `middleware.py`:

```python
class OnlyOnAgUi(AgentMiddleware):
    """Hide the named tools from the model unless the run came through
    Market Desk's AG-UI transport (state["ag-ui"] present). /stream, voice
    and AgentCore resume only HITL decisions, so they must never see a
    choice interrupt."""

    def __init__(self, tool_names: set[str]):
        super().__init__()
        self.tool_names = tool_names

    def _filter(self, request: ModelRequest) -> ModelRequest:
        from app.agent.orchestration.state import AG_UI_KEY

        if (request.state or {}).get(AG_UI_KEY) is not None:
            return request
        return request.override(tools=[t for t in request.tools if getattr(t, "name", None) not in self.tool_names])

    def wrap_model_call(self, request, handler):
        return handler(self._filter(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._filter(request))


def only_on_ag_ui() -> OnlyOnAgUi:
    return OnlyOnAgUi({"ask_user_choice"})
```

Wiring:
- add `ask_user_choice_tool` to `_TOOLS` in portfolio, finance and email;
- add `only_on_ag_ui()` to each of those three middleware lists, right after `*base_middleware(_TOOLS)`;
- in `tools/__init__.py`, add it to `TOOLS` and `__all__`, but NOT to `_BASE_READ_ONLY_TOOLS`.

If the email agent's tests assert an exact `_TOOLS` list, update them to include `ask_user_choice`.

Prompts:
- append to PORTFOLIO, FINANCE and EMAIL, each under its tools list:
  ```
  - `ask_user_choice` — when the next step depends on a choice between known options, ask with buttons instead of plain text (args: `question`, `options: list[str]`, optional `multi`, `allow_other`). Only call it when it is in your tool list.
  ```
- PORTFOLIO also gets:
  ```
  - Ambiguous client: when a tool says a name matches several clients, call `ask_user_choice` with those names, then continue with the chosen one.
  - What-if without a size ("simulate selling NVDA for Margaret"): call `ask_user_choice` with options "25%", "50%", "100%" and allow_other=true, then call `simulate_portfolio_change` with the answer.
  ```
- EMAIL also gets:
  ```
  - Emailing a group ("email the clients with triggered alerts"): ask with `ask_user_choice` (multi=true) listing the matching clients, then send to the selected ones (each send goes through the normal approval).
  ```

`docs/TOOLS.md` and `CLAUDE.md`: add an `ask_user_choice` row (type "interactive", not read-only) and a section that explains why it is excluded from `READ_ONLY_TOOLS`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_user_choice.py -v && uv run pytest tests/ -q`
Expected: all pass. If `ModelRequest.override` has a different name in the installed LangChain, use the documented one: `grep -n "def override" .venv/Lib/site-packages/langchain/agents/middleware/types.py`. Keep the test's `override` stub in sync.

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools/user_choice.py tests/unit/test_user_choice.py app/agent/middleware.py app/agent/tools/__init__.py app/agent/agents_specialist/portfolio_agent.py app/agent/agents_specialist/finance_agent.py app/agent/agents_specialist/email_agent.py app/agent/prompts/agents_specialist_prompts.py docs/TOOLS.md CLAUDE.md tests/unit
git commit -m "feat(agents): ask_user_choice interrupt tool, offered only on the AG-UI transport"
```

### Task 12: Choice card in the chat

**Files:**
- Create: `frontend/src/desk/ChoiceCard.tsx` (+ `.test.tsx`)
- Modify: `frontend/src/desk/useDeskInterrupt.tsx`
- Test: `frontend/src/desk/useDeskInterrupt.test.tsx` (append)

**Interfaces:**
- Consumes: the interrupt raw value at `interrupt.metadata.langgraph.raw`, the same path `readApproval` uses.
- Produces:
  - `readChoice(interrupt: unknown): ChoiceRequest | null`;
  - `ChoiceCard({ request, onSubmit })`, with `onSubmit(value: { selected: string[]; other: string | null })`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/desk/ChoiceCard.test.tsx
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ChoiceCard, readChoice } from "./ChoiceCard";

const raw = { type: "user_choice", question: "Which client?", multi: false, allow_other: false,
  options: [{ id: "0", label: "Ann Lee" }, { id: "1", label: "Ann Moss" }] };
const interrupt = { metadata: { langgraph: { raw } } };

describe("ChoiceCard", () => {
  it("reads only user_choice interrupts", () => {
    expect(readChoice(interrupt)?.question).toBe("Which client?");
    expect(readChoice({ metadata: { langgraph: { raw: { action_requests: [] } } } })).toBeNull();
  });

  it("single choice submits on click", () => {
    const onSubmit = vi.fn();
    render(<ChoiceCard request={readChoice(interrupt)!} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: "Ann Moss" }));
    expect(onSubmit).toHaveBeenCalledWith({ selected: ["1"], other: null });
  });

  it("multi choice submits the ticked options and other text", () => {
    const onSubmit = vi.fn();
    render(<ChoiceCard request={{ ...readChoice(interrupt)!, multi: true, allow_other: true }} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Ann Lee" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Other" }), { target: { value: "Bob" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onSubmit).toHaveBeenCalledWith({ selected: ["0"], other: "Bob" });
  });
});
```

Append to `useDeskInterrupt.test.tsx`. Add `vi.mock("./ChoiceCard", ...)` returning `ChoiceCard: () => <div>choice</div>` and the real `readChoice`; use `vi.importActual` for `readChoice`:

```tsx
  it("renders the choice card for user_choice interrupts and resumes with the answer", () => {
    render(<Harness onPendingChange={vi.fn()} />);
    const resolve = vi.fn();
    const card = render(interruptConfig.render({
      interrupt: { metadata: { langgraph: { raw: { type: "user_choice", question: "Q", multi: false, allow_other: false,
        options: [{ id: "0", label: "A" }, { id: "1", label: "B" }] } } } },
      resolve, cancel: vi.fn(),
    }));
    expect(card.getByText("choice")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/desk/ChoiceCard.test.tsx src/desk/useDeskInterrupt.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/desk/ChoiceCard.tsx
import { useState } from "react";

export interface ChoiceRequest {
  question: string;
  options: { id: string; label: string }[];
  multi: boolean;
  allow_other: boolean;
}
export type ChoiceAnswer = { selected: string[]; other: string | null };

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// ask_user_choice's interrupt payload, surfaced by ag-ui-langgraph at
// interrupt.metadata.langgraph.raw (same place readApproval looks).
export function readChoice(interrupt: unknown): ChoiceRequest | null {
  const raw = isRecord(interrupt) && isRecord(interrupt.metadata) && isRecord(interrupt.metadata.langgraph)
    ? interrupt.metadata.langgraph.raw : undefined;
  if (!isRecord(raw) || raw.type !== "user_choice" || !Array.isArray(raw.options)) return null;
  return {
    question: String(raw.question ?? ""),
    options: raw.options as ChoiceRequest["options"],
    multi: raw.multi === true,
    allow_other: raw.allow_other === true,
  };
}

export function ChoiceCard({ request, onSubmit }: { request: ChoiceRequest; onSubmit: (a: ChoiceAnswer) => void }) {
  const [ticked, setTicked] = useState<string[]>([]);
  const [other, setOther] = useState("");
  const otherValue = request.allow_other && other.trim() ? other.trim() : null;
  return (
    <div className="rounded-xl border border-terminal-accent/40 bg-terminal-panel card-shadow p-3 text-sm text-terminal-text">
      <div className="mb-2 font-semibold">{request.question}</div>
      <div className="flex flex-wrap gap-2">
        {request.options.map((o) =>
          request.multi ? (
            <label key={o.id} className="flex items-center gap-1.5 rounded-lg border border-terminal-border px-2 py-1">
              <input
                type="checkbox"
                aria-label={o.label}
                checked={ticked.includes(o.id)}
                onChange={() => setTicked((t) => (t.includes(o.id) ? t.filter((x) => x !== o.id) : [...t, o.id]))}
              />
              {o.label}
            </label>
          ) : (
            <button key={o.id} type="button" onClick={() => onSubmit({ selected: [o.id], other: null })}
              className="rounded-lg border border-terminal-border px-3 py-1 hover:border-terminal-accent">
              {o.label}
            </button>
          ),
        )}
      </div>
      {request.allow_other && (
        <input aria-label="Other" placeholder="Other…" value={other} onChange={(e) => setOther(e.target.value)}
          className="mt-2 w-full rounded-lg border border-terminal-border bg-terminal-bg px-2 py-1" />
      )}
      {(request.multi || request.allow_other) && (
        <button type="button" disabled={ticked.length === 0 && !otherValue}
          onClick={() => onSubmit({ selected: ticked, other: otherValue })}
          className="mt-2 rounded-lg bg-terminal-accent px-3 py-1 font-semibold text-terminal-bg disabled:opacity-40">
          Confirm
        </button>
      )}
    </div>
  );
}
```

In `useDeskInterrupt.tsx`, change the `render` body to branch:

```tsx
    render: ({ interrupt, resolve, cancel }) => {
      const choice = readChoice(interrupt);
      return (
        <PendingInterruptMarker onPendingChange={onPendingChange}>
          {choice ? (
            <ChoiceCard request={choice} onSubmit={(answer) => void resolve(answer)} />
          ) : (
            <ApprovalPanel
              approval={readApproval(interrupt)}
              onSubmit={(decisions) => void resolve({ decisions })}
              onCancel={() => void cancel()}
            />
          )}
        </PendingInterruptMarker>
      );
    },
```

and add `import { ChoiceCard, readChoice } from "./ChoiceCard";`.

`MarketDeskAgent._build_command_from_agui_resume` (`app/api/routers/copilot.py:58`) may reshape resume payloads for HITL. Read it first:

```bash
sed -n 45,80p app/api/routers/copilot.py
```

If it assumes a `decisions` key, make it pass a payload without `decisions` through unchanged. Add a test for that in `tests/unit/` next to the existing copilot router tests:

```bash
grep -rln "_build_command_from_agui_resume" tests
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src && npx tsc --noEmit -p .` and `uv run pytest tests/ -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/desk/ChoiceCard.tsx frontend/src/desk/ChoiceCard.test.tsx frontend/src/desk/useDeskInterrupt.tsx frontend/src/desk/useDeskInterrupt.test.tsx app/api/routers/copilot.py tests/unit
git commit -m "feat(desk): choice card for ask_user_choice interrupts"
```

### Task 13: Follow-up suggestions after each answer

**Files:**
- Create:
  - `app/agent/orchestration/followups.py`
  - `tests/unit/test_followups.py`
- Modify:
  - `app/agent/orchestration/graph.py` (node + edges)
  - `app/agent/orchestration/state.py` (`suggestions` key)
  - `frontend/src/desk/DeskView.tsx`
  - `frontend/src/desk/DeskView.test.tsx`

**Interfaces:**
- Produces:
  - `async suggest_followups(state) -> dict`, which returns `{"suggestions": [{"title", "message"}]}`;
  - `SupervisorState.suggestions: list[dict]`;
  - the frontend reads `agent.state.suggestions`.

- [ ] **Step 1: Verify that state reaches the browser first**

Run with the backend up. Post one AG-UI run (as in Task 9) and look for a `STATE_SNAPSHOT` event that contains a top-level graph key, `agent_hops`:

```bash
curl -s -N -X POST localhost:8000/copilot/market-desk -H 'Content-Type: application/json' -d '{"threadId":"qa_state_1","runId":"r1","state":{},"tools":[],"context":[],"forwardedProps":{},"messages":[{"id":"m1","role":"user","content":"What is AAPL trading at?"}]}' | grep -c '"agent_hops"'
```

- **Count ≥ 1:** graph state reaches the browser. Use `agent.state.suggestions` in Step 3.
- **Count 0:** use the fallback. Add `"suggestions": snapshot.values.get("suggestions", [])` to the payload of a new `GET /copilot/market-desk/state?thread_id=` endpoint in `copilot.py`, and fetch it in `DeskView` on `run_finished`, the same way `getThreadHistory` is used. Write that endpoint test-first, mirroring `market_desk_history`'s tests.

- [ ] **Step 2: Write the failing backend tests**

```python
# tests/unit/test_followups.py
import asyncio
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.orchestration import followups
from app.agent.orchestration.followups import FollowUps, Suggestion, suggest_followups

AG_UI = {"ag-ui": {"context": []}}


def _state(**extra):
    return {"messages": [HumanMessage("Compare NVDA vs AMD"), AIMessage("Here's the comparison.")], **extra}


def test_skips_without_ag_ui():
    assert asyncio.run(suggest_followups(_state())) == {}


def test_writes_three_suggestions():
    fake = AsyncMock(return_value=FollowUps(suggestions=[Suggestion(title=f"t{i}", message=f"m{i}") for i in range(3)]))
    with patch.object(followups, "_ask_model", fake):
        out = asyncio.run(suggest_followups(_state(**AG_UI)))
    assert out == {"suggestions": [{"title": f"t{i}", "message": f"m{i}"} for i in range(3)]}


def test_model_error_writes_empty_list():
    with patch.object(followups, "_ask_model", AsyncMock(side_effect=RuntimeError("boom"))):
        assert asyncio.run(suggest_followups(_state(**AG_UI))) == {"suggestions": []}


def test_no_answer_yet_writes_empty_list():
    state = {"messages": [HumanMessage("hi")], **AG_UI}
    assert asyncio.run(suggest_followups(state)) == {"suggestions": []}
```

- [ ] **Step 3: Implement**

```python
# app/agent/orchestration/followups.py
"""Follow-up suggestions after a Market Desk answer: one small structured
model call on the last question/answer. Runs only for AG-UI turns (the
pills live in CopilotKit) and never fails the turn."""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from app.agent.middleware import specialist_model
from app.agent.orchestration.state import AG_UI_KEY

logger = logging.getLogger(__name__)

_PROMPT = (
    "You suggest follow-up questions for a wealth-management advisor using a market research assistant. "
    "Given the last question and answer, propose exactly 3 short, specific follow-ups the assistant can do next "
    "(compare tickers, simulate a trade, check watchlist alerts, email a client, show news). "
    "title: at most 5 words. message: the full question to send."
)


class Suggestion(BaseModel):
    title: str = Field(max_length=60)
    message: str = Field(max_length=200)


class FollowUps(BaseModel):
    suggestions: list[Suggestion] = Field(min_length=1, max_length=3)


async def _ask_model(question: str, answer: str) -> FollowUps:
    model = specialist_model().with_structured_output(FollowUps).with_config(
        {"metadata": {"emit-messages": False, "emit-tool-calls": False}}
    )
    return await model.ainvoke([("system", _PROMPT), ("human", f"Question: {question}\n\nAnswer: {answer}")])


async def suggest_followups(state) -> dict:
    if state.get(AG_UI_KEY) is None:
        return {}
    messages = state.get("messages") or []
    if not messages or not isinstance(messages[-1], AIMessage) or not messages[-1].content:
        return {"suggestions": []}
    question = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), "")
    try:
        result = await _ask_model(str(question), str(messages[-1].content))
        return {"suggestions": [s.model_dump() for s in result.suggestions]}
    except Exception:
        logger.exception("follow-up suggestions failed")
        return {"suggestions": []}
```

Graph and state:
- in `state.py`, add `suggestions: list[dict]` to `SupervisorState`;
- in `graph.py`, replace `workflow.add_edge("finalize_turn", END)` with:
  ```python
  workflow.add_node("suggest_followups", suggest_followups)
  workflow.add_edge("finalize_turn", "suggest_followups")
  workflow.add_edge("suggest_followups", END)
  ```
- import `suggest_followups` from `app.agent.orchestration.followups`;
- if `/stream` filters nodes for `node` events, `suggest_followups` is a plain node with no LLM tokens on that transport (it returns `{}` there). Check `_STREAMABLE_NODES` in `app/api/routers/stream.py` and leave it out.

An interrupted turn never reaches `finalize_turn`, so no suggestions are produced while an approval is pending.

Frontend (`DeskView.tsx`, `DeskBody`), using `agent.state` if Step 1 found state in the snapshot:

```tsx
function FollowUpSuggestions() {
  const { agent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
  const suggestions = ((agent?.state as { suggestions?: StarterSuggestion[] } | undefined)?.suggestions ?? []);
  useConfigureSuggestions(
    suggestions.length ? { suggestions, available: "after-first-message" } : null,
    [JSON.stringify(suggestions)],
  );
  return null;
}
```

Render `<FollowUpSuggestions />` in `DeskBody`. Add a `DeskView.test.tsx` case: make the mocked `useAgent` return `{ agent: { state: { suggestions: [{ title: "T", message: "M" }] }, messages: [], subscribe: ... } }` and assert a config with `available: "after-first-message"` and those suggestions was registered.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/ -q` and `cd frontend && npx vitest run src && npx tsc --noEmit -p .`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/agent/orchestration/followups.py app/agent/orchestration/graph.py app/agent/orchestration/state.py tests/unit/test_followups.py frontend/src/desk/DeskView.tsx frontend/src/desk/DeskView.test.tsx
git commit -m "feat(desk): follow-up suggestions generated after each Market Desk answer"
```

### Task 14: Final live QA and memory

**Files:** none, except fixes.

- [ ] **Step 1: Restart the backend** (as in Task 8). The frontend dev server hot-reloads.

- [ ] **Step 2: Run the full browser pass** on fresh sessions

1. **Starters.** All 4 Research starters render their cards (re-check Task 8).
2. **Follow-ups.** After "Compare NVDA vs AMD", 3 follow-up pills appear. Clicking one runs it.
3. **Context on Research.** After the comparison, "add MSFT" gives a comparison of NVDA, AMD and MSFT.
4. **Ambiguous client.** Find a partial name that matches 2 clients:
   ```bash
   uv run python -c "import sqlite3; c=sqlite3.connect('customers.db'); print(c.execute('select name from clients').fetchall())"
   ```
   Ask for that partial name's portfolio. Expect a choice card with both names. Click one and the portfolio card follows.
5. **What-if without a size.** "Simulate selling NVDA for Margaret Collins" shows the 25 / 50 / 100 % card. Click 50 % and the what-if card appears.
6. **Client page.** On `/clients/<Margaret's id>`, click the NVDA chip and ask "explain this position". The answer is about NVDA.
   - Use the client page only if its thread holds no real conversation you care about.
   - Otherwise check this step through a `qa_` thread with a context entry, using the curl from Task 9.
7. **Other transports are unchanged.** A `/stream` question about an ambiguous client must not produce a choice interrupt:
   ```bash
   curl -s -N -X POST localhost:8000/stream -H 'Content-Type: application/json' -d '{"query":"Show the portfolio for <partial name>","thread_id":"qa_stream_choice"}' | grep -c user_choice
   ```
   Expected: `0`.

- [ ] **Step 3: Fix any failure in its owning task's files, re-run the tests, and commit.**

- [ ] **Step 4: Save a memory file** `project_desk_interactive_cards.md`:
  - what shipped, with commit range;
  - the state-snapshot finding from Task 13 Step 1;
  - any routing phrasings that needed prompt changes.

  Add its index line to `MEMORY.md`. Do not push.
