# CopilotKit rich displays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render tables, charts, screenshots and source cards inside Market Desk's chat for the 7 tools whose output is naturally visual, plus starter suggestions and a bounded file-attachment path — all without touching the single-agent graph (Streamlit, voice, `/stream`).

**Architecture:** A single backend middleware (`MarketDeskDisplayMiddleware`) reshapes a `ToolMessage`'s content into `{"summary": <original text, unchanged>, "displays": [...]}` right after the (shared) tool runs, but only inside the 4 multi-agent specialists that own a displayable tool. The frontend registers one `useRenderTool` per tool name; each parses `displays` and renders a typed component in the same chat slot the generic tool card used before.

**Tech Stack:** Python 3 / LangChain `AgentMiddleware` / pytest; React 18 / `@copilotkit/react-core` v2 / `recharts` / Vitest.

**Spec:** `docs/superpowers/specs/2026-09-27-copilotkit-rich-displays-design.md`

## Global Constraints

- `summary` in the envelope is the **original tool text, verbatim** (never a hand-written rewrite) — the LLM's reasoning must be provably unaffected. A normalizer only ever produces `displays`.
- A normalizer that raises, or an unregistered tool, must leave `ToolMessage.content` **exactly as it was** — the middleware fails open, never breaks the answer.
- The middleware is wired into `portfolio_agent`, `finance_agent`, `rag_agent`, `browser_agent` only. It must never be imported by `app/agent/graph.py` (single-agent) or anything Streamlit/voice touches.
- `search_knowledge_base_tool` and `browser_screenshot_tool` are the **same tool instances** the single-agent graph uses — verified in the spec. Never change their own return value; only the middleware, scoped to the multi-agent graph, may reshape what a specialist's `ToolMessage` carries.
- In `browser_agent.py`, the display middleware must run **after** `StripToolImages` has already removed the image content block — `AgentMiddleware.wrap_tool_call` chains "first = outermost" (`langchain/agents/factory.py`, `_chain_tool_call_wrappers`), so the display middleware must be listed **before** `strip_tool_images` in that specialist's middleware list.
- Wire format keys are snake_case, matching the Python source dicts 1:1 (`market_value`, `weight_pct`, …) — this codebase's own `ApproveResponse.next_step` already does the same on the frontend, so no case-mapping layer is needed.
- `POST /copilot/uploads` is gated by `COPILOT_ENABLED` exactly like the rest of `copilot.py`'s router (404 when disabled).
- New frontend dependency: `recharts` pinned exact (`"3.10.1"`), matching how `@copilotkit/react-core` is already pinned exact in `frontend/package.json`.
- No GET route for uploaded files — the agent reads them back with the existing `read_text_file`/`list_directory` tools, which already resolve under `WORKSPACE_ROOT`.

## Review Focus

1. **A tool result the normalizer can't turn into anything useful** (no breaches, no RAG matches, no price rows, no price field on a delisted-looking ticker) — the answer must still show normally, with zero displays, not a broken or empty card.
2. **A normalizer bug must never take down the answer** — fail-open, pinned in Task 1 with a normalizer that deliberately raises.
3. **The single-agent graph (Streamlit, voice) must never see this middleware** — pinned by asserting `app/agent/graph.py` and its own tool wiring are untouched (Task 6).
4. **The upload endpoint is a new unauthenticated write path** — path traversal (`../../etc/passwd`), oversized file, and `COPILOT_ENABLED=false` must all be rejected, pinned in Task 7.
5. **A `displays` array with one good entry and one malformed entry** must keep the good one and drop only the bad one — pinned in Task 8 (`parseDisplay`).

---

## File map

**Python**
- Create: `app/agent/multi_agent/display.py` — `DISPLAY_NORMALIZERS` registry, 7 normalizers, `MarketDeskDisplayMiddleware`.
- Modify: `app/agent/multi_agent/portfolio_agent.py`, `finance_agent.py`, `rag_agent.py`, `browser_agent.py` — wire the middleware.
- Modify: `app/api/routers/copilot.py` — add `POST /copilot/uploads`.
- Tests: `tests/unit/test_display_middleware.py`, `tests/unit/test_display_normalizers.py`, `tests/unit/test_copilot_uploads.py`, an addition to `tests/unit/test_copilot_endpoint.py`.

**Frontend (`frontend/`)**
- Create: `src/desk/displays/types.ts`, `parseDisplay.ts`, `useToolDisplay.tsx`, `PortfolioTable.tsx`, `PortfolioPieChart.tsx`, `PriceChart.tsx`, `TickerInfoCard.tsx`, `TickerNewsList.tsx`, `ConcentrationAlert.tsx`, `ScreenshotCard.tsx`, `RagSourceCards.tsx`.
- Modify: `src/desk/DeskView.tsx`, `src/lib/api.ts`, `package.json`.
- Tests: one `*.test.ts(x)` per new file above.

---

### Task 1: Display envelope mechanism (middleware skeleton, registry, fail-open)

**Files:**
- Create: `app/agent/multi_agent/display.py`
- Test: `tests/unit/test_display_middleware.py`

**Interfaces:**
- Produces:
  - `Normalizer = Callable[[str, dict], list[dict]]` — `(original_text, tool_call_args) -> displays`
  - `DISPLAY_NORMALIZERS: dict[str, Normalizer]` — module-level, empty until Tasks 2-5 populate it
  - `market_desk_display = MarketDeskDisplayMiddleware()` — the singleton instance every specialist file imports
  - `_content_text(content) -> str` — internal helper, exported for the other normalizer tasks to reuse

- [ ] **Step 1: Write the failing tests**

```python
"""MarketDeskDisplayMiddleware: reshapes a registered tool's ToolMessage into
{"summary": <original text>, "displays": [...]}; everything else (unregistered
tools, a failing normalizer) passes through untouched — the answer must never
break because a display couldn't be built."""
import json
from unittest.mock import patch

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from app.agent.multi_agent import display


def _request(name: str, args: dict) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"id": "c1", "name": name, "args": args},
        tool=None,
        state={"messages": []},
        runtime=None,
    )


def _handler_returning(content):
    def handler(request):
        return ToolMessage(content=content, name=request.tool_call["name"], tool_call_id=request.tool_call["id"])
    return handler


async def _ahandler_returning(content):
    async def handler(request):
        return ToolMessage(content=content, name=request.tool_call["name"], tool_call_id=request.tool_call["id"])
    return handler


def test_unregistered_tool_passes_through_untouched():
    result = display.market_desk_display.wrap_tool_call(_request("read_query", {}), _handler_returning("raw text"))
    assert result.content == "raw text"


def test_registered_tool_gets_the_envelope():
    with patch.dict(display.DISPLAY_NORMALIZERS, {"fake_tool": lambda text, args: [{"type": "fake", "n": len(text)}]}):
        result = display.market_desk_display.wrap_tool_call(_request("fake_tool", {}), _handler_returning("hello"))
    envelope = json.loads(result.content)
    assert envelope == {"summary": "hello", "displays": [{"type": "fake", "n": 5}]}


def test_a_raising_normalizer_leaves_content_untouched():
    def boom(text, args):
        raise ValueError("no")
    with patch.dict(display.DISPLAY_NORMALIZERS, {"fake_tool": boom}):
        result = display.market_desk_display.wrap_tool_call(_request("fake_tool", {}), _handler_returning("hello"))
    assert result.content == "hello"


def test_normalizer_receives_the_tool_call_args():
    seen = {}
    def spy(text, args):
        seen.update(args)
        return []
    with patch.dict(display.DISPLAY_NORMALIZERS, {"fake_tool": spy}):
        display.market_desk_display.wrap_tool_call(_request("fake_tool", {"symbol": "AAPL"}), _handler_returning("x"))
    assert seen == {"symbol": "AAPL"}


def test_list_content_is_flattened_to_text_before_normalizing():
    # yfinance/browser MCP tools return [{"type": "text", "text": "..."}], not a plain string.
    list_content = [{"type": "text", "text": "hello", "id": "x"}]
    with patch.dict(display.DISPLAY_NORMALIZERS, {"fake_tool": lambda text, args: [{"type": "fake", "text": text}]}):
        result = display.market_desk_display.wrap_tool_call(_request("fake_tool", {}), _handler_returning(list_content))
    envelope = json.loads(result.content)
    assert envelope == {"summary": "hello", "displays": [{"type": "fake", "text": "hello"}]}


def test_a_non_toolmessage_result_passes_through():
    # HumanInTheLoopMiddleware and others can return a Command instead of a ToolMessage.
    sentinel = object()
    result = display.market_desk_display.wrap_tool_call(_request("read_query", {}), lambda request: sentinel)
    assert result is sentinel


@pytest.mark.anyio
async def test_async_path_mirrors_the_sync_path():
    with patch.dict(display.DISPLAY_NORMALIZERS, {"fake_tool": lambda text, args: [{"type": "fake"}]}):
        result = await display.market_desk_display.awrap_tool_call(_request("fake_tool", {}), await _ahandler_returning("hi"))
    assert json.loads(result.content) == {"summary": "hi", "displays": [{"type": "fake"}]}
```

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/unit/test_display_middleware.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.agent.multi_agent.display'`).

- [ ] **Step 3: Implement** — create `app/agent/multi_agent/display.py`:

```python
"""Market Desk display envelope: reshapes a specialist's ToolMessage into
{"summary": <original text, unchanged>, "displays": [...]} so the frontend can
render a table/chart/card instead of a plain-text tool card.

Scoped to the multi-agent graph only, via MarketDeskDisplayMiddleware, wired
per-specialist in portfolio_agent.py / finance_agent.py / rag_agent.py /
browser_agent.py. Never imported by app/agent/graph.py (single-agent): the two
tools this touches that ARE shared instances with the single-agent graph
(search_knowledge_base_tool, browser_screenshot_tool) must keep their own
return value untouched for Streamlit/voice — this middleware only ever
rewrites the copy of ToolMessage.content that flows through this graph.

The `summary` field is always the original tool text, verbatim — never a
normalizer's own rewrite — so the LLM's next-turn reasoning is provably
unaffected by any of this. A normalizer's only job is to produce `displays`
from that same text; if it fails, the ToolMessage is left exactly as it was
(fail open — a broken display must never break the answer).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

ToolResult = ToolMessage | Command[Any]
# (original text, tool call args) -> list of {"type": ..., ...} display payloads
Normalizer = Callable[[str, dict], list[dict]]

# Populated by Tasks 2-5, one entry per displayable tool name.
DISPLAY_NORMALIZERS: dict[str, Normalizer] = {}


def _content_text(content: Any) -> str:
    """ToolMessage.content is a plain string for tools that return a Python
    str/dict directly (portfolio_metrics, concentration_screen,
    search_knowledge_base), but a list of MCP content blocks for MCP-backed
    tools (yfinance_*, browser_take_screenshot) — [{"type": "text", "text":
    ...}, ...]. Every normalizer receives plain text either way."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)


class MarketDeskDisplayMiddleware(AgentMiddleware):
    """Looks up the tool name in DISPLAY_NORMALIZERS; if found, replaces
    ToolMessage.content with the envelope. Unregistered tools and non-
    ToolMessage results (e.g. a Command from another middleware) pass
    through untouched."""

    @staticmethod
    def _envelope(result: ToolResult, args: dict) -> ToolResult:
        if not isinstance(result, ToolMessage):
            return result
        normalizer = DISPLAY_NORMALIZERS.get(result.name or "")
        if normalizer is None:
            return result
        text = _content_text(result.content)
        try:
            displays = normalizer(text, args)
        except Exception:
            logger.exception("display normalizer failed for tool %r", result.name)
            return result
        result.content = json.dumps({"summary": text, "displays": displays})
        return result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolResult],
    ) -> ToolResult:
        return self._envelope(handler(request), request.tool_call.get("args", {}))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolResult]],
    ) -> ToolResult:
        return self._envelope(await handler(request), request.tool_call.get("args", {}))


market_desk_display = MarketDeskDisplayMiddleware()
```

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/unit/test_display_middleware.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/multi_agent/display.py tests/unit/test_display_middleware.py
git commit -m "feat(multi-agent): Market Desk display envelope middleware (fail-open, registry-based)"
```

---

### Task 2: `normalize_portfolio` (portfolio_table + portfolio_chart)

**Files:**
- Modify: `app/agent/multi_agent/display.py`
- Test: `tests/unit/test_display_normalizers.py` (new)

**Interfaces:**
- Consumes: `display.DISPLAY_NORMALIZERS` (Task 1).
- Produces: `normalize_portfolio` registered under `"portfolio_metrics"`. Display shapes:
  - `{"type": "portfolio_table", "positions": [{"ticker", "shares", "price", "market_value", "cost_basis", "unrealized_pnl", "unrealized_pnl_pct", "weight_pct", "sector"}], "totals": {"market_value", "cost_basis", "unrealized_pnl", "unrealized_pnl_pct"}}`
  - `{"type": "portfolio_chart", "slices": [{"ticker", "weight_pct"}]}`

- [ ] **Step 1: Write the failing test** — create `tests/unit/test_display_normalizers.py`:

```python
"""Pure str -> list[dict] normalizers, each tested against the real shape its
tool actually produces (captured live where the tool is MCP-backed and this
repo has no fixture of its own)."""
import json

from app.agent.multi_agent import display

# Trimmed real output of compute_portfolio_metrics (finance_calc.py) for one
# client — field names and value shapes copied verbatim.
PORTFOLIO_METRICS_JSON = json.dumps({
    "positions": [
        {"ticker": "BND", "shares": 300.0, "avg_cost": 73.33, "price": 70.63, "sector": "ETF",
         "market_value": 21189.0, "cost_basis": 21999.0, "unrealized_pnl": -810.0,
         "unrealized_pnl_pct": -3.68, "weight_pct": 13.62},
        {"ticker": "NVDA", "shares": 71.0, "avg_cost": 172.96, "price": 1259.66, "sector": "Technology",
         "market_value": 89436.0, "cost_basis": 12280.0, "unrealized_pnl": 77156.0,
         "unrealized_pnl_pct": 628.31, "weight_pct": 57.5},
    ],
    "totals": {"market_value": 155564.81, "cost_basis": 64179.0, "unrealized_pnl": 91385.81,
               "unrealized_pnl_pct": 142.39},
    "sector_allocation": {"ETF": 13.62, "Technology": 57.5},
})


def test_normalize_portfolio_produces_table_and_chart():
    displays = display.DISPLAY_NORMALIZERS["portfolio_metrics"](PORTFOLIO_METRICS_JSON, {})
    assert [d["type"] for d in displays] == ["portfolio_table", "portfolio_chart"]

    table = displays[0]
    assert table["totals"] == {"market_value": 155564.81, "cost_basis": 64179.0,
                                "unrealized_pnl": 91385.81, "unrealized_pnl_pct": 142.39}
    assert table["positions"][0] == {
        "ticker": "BND", "shares": 300.0, "price": 70.63, "market_value": 21189.0,
        "cost_basis": 21999.0, "unrealized_pnl": -810.0, "unrealized_pnl_pct": -3.68,
        "weight_pct": 13.62, "sector": "ETF",
    }

    chart = displays[1]
    assert chart["slices"] == [{"ticker": "BND", "weight_pct": 13.62}, {"ticker": "NVDA", "weight_pct": 57.5}]
```

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/unit/test_display_normalizers.py -v`
Expected: FAIL (`KeyError: 'portfolio_metrics'` — nothing registered yet).

- [ ] **Step 3: Implement** — append to `app/agent/multi_agent/display.py`:

```python
def normalize_portfolio(text: str, args: dict) -> list[dict]:
    data = json.loads(text)
    positions = data["positions"]
    table = {
        "type": "portfolio_table",
        "positions": [
            {
                "ticker": p["ticker"], "shares": p["shares"], "price": p["price"],
                "market_value": p["market_value"], "cost_basis": p["cost_basis"],
                "unrealized_pnl": p["unrealized_pnl"], "unrealized_pnl_pct": p["unrealized_pnl_pct"],
                "weight_pct": p["weight_pct"], "sector": p["sector"],
            }
            for p in positions
        ],
        "totals": data["totals"],
    }
    chart = {
        "type": "portfolio_chart",
        "slices": [{"ticker": p["ticker"], "weight_pct": p["weight_pct"]} for p in positions],
    }
    return [table, chart]


DISPLAY_NORMALIZERS["portfolio_metrics"] = normalize_portfolio
```

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/unit/test_display_normalizers.py tests/unit/test_display_middleware.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/multi_agent/display.py tests/unit/test_display_normalizers.py
git commit -m "feat(multi-agent): normalize_portfolio (portfolio_table + portfolio_chart displays)"
```

---

### Task 3: `normalize_concentration`

**Files:**
- Modify: `app/agent/multi_agent/display.py`, `tests/unit/test_display_normalizers.py`

**Interfaces:**
- Produces: `normalize_concentration` registered under `"concentration_screen"`. Display: `{"type": "concentration_alert", "threshold_pct", "breaches": [{"label", "ticker", "weight_pct", "market_value"}]}` — omitted entirely when there are no breaches.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_display_normalizers.py`:

```python
# Real shape of screen_clients()'s return (concentration.py) — "prices" is
# dropped by the normalizer, it's not display-relevant.
CONCENTRATION_JSON = json.dumps({
    "threshold_pct": 30.0, "screened_count": 2, "screened_labels": ["Margaret Collins", "Martin Levy"],
    "breach_count": 1,
    "breaches": [{"label": "Margaret Collins", "ticker": "NVDA", "weight_pct": 57.5,
                  "market_value": 89436.0, "portfolio_market_value": 155564.81}],
    "prices": {"NVDA": 1259.66},
})

CONCENTRATION_NO_BREACHES_JSON = json.dumps({
    "threshold_pct": 30.0, "screened_count": 1, "screened_labels": ["Diversified Dan"],
    "breach_count": 0, "breaches": [], "prices": {},
})


def test_normalize_concentration_produces_an_alert_per_breach():
    displays = display.DISPLAY_NORMALIZERS["concentration_screen"](CONCENTRATION_JSON, {})
    assert displays == [{
        "type": "concentration_alert", "threshold_pct": 30.0,
        "breaches": [{"label": "Margaret Collins", "ticker": "NVDA", "weight_pct": 57.5, "market_value": 89436.0}],
    }]


def test_normalize_concentration_with_no_breaches_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["concentration_screen"](CONCENTRATION_NO_BREACHES_JSON, {}) == []
```

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/unit/test_display_normalizers.py -k concentration -v`
Expected: FAIL (`KeyError: 'concentration_screen'`).

- [ ] **Step 3: Implement** — append to `app/agent/multi_agent/display.py`:

```python
def normalize_concentration(text: str, args: dict) -> list[dict]:
    data = json.loads(text)
    breaches = data.get("breaches") or []
    if not breaches:
        return []
    return [{
        "type": "concentration_alert",
        "threshold_pct": data["threshold_pct"],
        "breaches": [
            {"label": b["label"], "ticker": b["ticker"], "weight_pct": b["weight_pct"], "market_value": b["market_value"]}
            for b in breaches
        ],
    }]


DISPLAY_NORMALIZERS["concentration_screen"] = normalize_concentration
```

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/unit/test_display_normalizers.py tests/unit/test_display_middleware.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/multi_agent/display.py tests/unit/test_display_normalizers.py
git commit -m "feat(multi-agent): normalize_concentration (concentration_alert display)"
```

---

### Task 4: yfinance normalizers (price_chart, ticker_info, ticker_news)

**Files:**
- Modify: `app/agent/multi_agent/display.py`, `tests/unit/test_display_normalizers.py`

**Interfaces:**
- Produces: `normalize_price_history` → `"yfinance_get_price_history"`, `normalize_ticker_info` → `"yfinance_get_ticker_info"`, `normalize_ticker_news` → `"yfinance_get_ticker_news"`.
- Display shapes:
  - `{"type": "price_chart", "ticker", "points": [{"date", "close"}]}`
  - `{"type": "ticker_info", "ticker", "name", "sector", "industry", "current_price", "currency", "market_cap", "fifty_two_week_low", "fifty_two_week_high"}`
  - `{"type": "ticker_news", "items": [{"title", "summary", "source", "url", "published_at"}]}`

All three yfinance tools return `ToolMessage.content = [{"type": "text", "text": "<...>", "id": "..."}]` (an MCP content-block list, not a plain string) — confirmed by a live call to each tool during planning. `_content_text` (Task 1) already flattens this before any normalizer runs, so every normalizer here still takes plain text.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_display_normalizers.py`:

```python
# Real (trimmed) yfinance_get_price_history text — a markdown table, not
# JSON. Captured live: the raw MCP result is
# [{"type": "text", "text": THIS_STRING, "id": "..."}]; _content_text already
# extracts THIS_STRING before the normalizer runs. No ticker column exists in
# the table itself — the tool call's own args carry it.
PRICE_HISTORY_TEXT = (
    "| Date                      |   Open |   High |    Low |   Close |      Volume |   Dividends |   Stock Splits |\n"
    "|:--------------------------|-------:|-------:|-------:|--------:|------------:|------------:|---------------:|\n"
    "| 2026-09-21 00:00:00-04:00 | 335.28 | 339.64 | 333.05 |  338.98 | 3.49992e+07 |           0 |              0 |\n"
    "| 2026-09-22 00:00:00-04:00 | 340.14 | 345.34 | 338.75 |  339.75 | 4.07118e+07 |           0 |              0 |\n"
    "| 2026-09-23 00:00:00-04:00 | 341.08 | 341.8  | 335.5  |  337.02 | 3.16588e+07 |           0 |              0 |"
)


def test_normalize_price_history_parses_the_markdown_table():
    displays = display.DISPLAY_NORMALIZERS["yfinance_get_price_history"](PRICE_HISTORY_TEXT, {"symbol": "AAPL"})
    assert displays == [{
        "type": "price_chart", "ticker": "AAPL",
        "points": [
            {"date": "2026-09-21", "close": 338.98},
            {"date": "2026-09-22", "close": 339.75},
            {"date": "2026-09-23", "close": 337.02},
        ],
    }]


def test_normalize_price_history_falls_back_to_the_ticker_arg_name():
    displays = display.DISPLAY_NORMALIZERS["yfinance_get_price_history"](PRICE_HISTORY_TEXT, {"ticker": "aapl"})
    assert displays[0]["ticker"] == "AAPL"


def test_normalize_price_history_with_no_rows_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["yfinance_get_price_history"]("no data available", {"symbol": "XXXX"}) == []


# Trimmed real yfinance_get_ticker_info JSON text (captured live for AAPL) —
# only the fields the display needs, but with the exact real key names.
TICKER_INFO_JSON = json.dumps({
    "shortName": "Apple Inc.", "longName": "Apple Inc.", "sector": "Technology",
    "industry": "Consumer Electronics", "currentPrice": 341.07, "regularMarketPrice": 341.07,
    "currency": "USD", "marketCap": 4977636933632, "fiftyTwoWeekLow": 243.42, "fiftyTwoWeekHigh": 345.34,
})


def test_normalize_ticker_info():
    displays = display.DISPLAY_NORMALIZERS["yfinance_get_ticker_info"](TICKER_INFO_JSON, {"symbol": "AAPL"})
    assert displays == [{
        "type": "ticker_info", "ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology",
        "industry": "Consumer Electronics", "current_price": 341.07, "currency": "USD",
        "market_cap": 4977636933632, "fifty_two_week_low": 243.42, "fifty_two_week_high": 345.34,
    }]


def test_normalize_ticker_info_with_no_price_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["yfinance_get_ticker_info"](json.dumps({"shortName": "Delisted Co"}), {"symbol": "XXXX"}) == []


# Trimmed real yfinance_get_ticker_news JSON text (captured live for AAPL) —
# real nesting (content.title, content.provider.displayName, ...), one item
# missing a canonicalUrl to prove the clickThroughUrl fallback, one item
# missing a title entirely to prove it gets dropped rather than crashing.
TICKER_NEWS_JSON = json.dumps([
    {"id": "1", "content": {
        "title": "Does the S&P 500 Have a Magnificent Seven Problem?",
        "summary": "If the AI revolution doesn't live up to the hype, the whole market feels it.",
        "pubDate": "2026-09-27T13:09:00Z",
        "provider": {"displayName": "Motley Fool"},
        "canonicalUrl": {"url": "https://www.fool.com/a"},
        "clickThroughUrl": {"url": "https://finance.yahoo.com/a"},
    }},
    {"id": "2", "content": {
        "title": "Apple stock ticks up", "summary": "", "pubDate": "2026-09-27T10:00:00Z",
        "provider": {"displayName": "Reuters"}, "canonicalUrl": None,
        "clickThroughUrl": {"url": "https://finance.yahoo.com/b"},
    }},
    {"id": "3", "content": {"title": None, "summary": "no title, must be dropped", "provider": {}}},
])


def test_normalize_ticker_news():
    displays = display.DISPLAY_NORMALIZERS["yfinance_get_ticker_news"](TICKER_NEWS_JSON, {"symbol": "AAPL"})
    assert displays == [{"type": "ticker_news", "items": [
        {"title": "Does the S&P 500 Have a Magnificent Seven Problem?",
         "summary": "If the AI revolution doesn't live up to the hype, the whole market feels it.",
         "source": "Motley Fool", "url": "https://www.fool.com/a", "published_at": "2026-09-27T13:09:00Z"},
        {"title": "Apple stock ticks up", "summary": "", "source": "Reuters",
         "url": "https://finance.yahoo.com/b", "published_at": "2026-09-27T10:00:00Z"},
    ]}]


def test_normalize_ticker_news_with_no_usable_items_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["yfinance_get_ticker_news"]("[]", {"symbol": "XXXX"}) == []
```

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/unit/test_display_normalizers.py -v`
Expected: the 7 new tests FAIL with `KeyError` (nothing registered under these names yet).

- [ ] **Step 3: Implement** — append to `app/agent/multi_agent/display.py`:

```python
def _row_ticker(args: dict) -> str:
    return str(args.get("symbol") or args.get("ticker") or "").upper()


def normalize_price_history(text: str, args: dict) -> list[dict]:
    points = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or not cells[0][:4].isdigit():
            continue  # skips the header row ("Date") and the ":---" separator row
        try:
            close = float(cells[4])
        except ValueError:
            continue
        points.append({"date": cells[0][:10], "close": close})
    if not points:
        return []
    return [{"type": "price_chart", "ticker": _row_ticker(args), "points": points}]


def normalize_ticker_info(text: str, args: dict) -> list[dict]:
    data = json.loads(text)
    price = data.get("currentPrice") or data.get("regularMarketPrice")
    if price is None:
        return []
    return [{
        "type": "ticker_info", "ticker": _row_ticker(args) or str(data.get("symbol") or ""),
        "name": data.get("shortName") or data.get("longName") or "",
        "sector": data.get("sector"), "industry": data.get("industry"),
        "current_price": float(price), "currency": data.get("currency") or "USD",
        "market_cap": data.get("marketCap"), "fifty_two_week_low": data.get("fiftyTwoWeekLow"),
        "fifty_two_week_high": data.get("fiftyTwoWeekHigh"),
    }]


def normalize_ticker_news(text: str, args: dict) -> list[dict]:
    entries = json.loads(text)
    items = []
    for entry in entries:
        content = entry.get("content", {}) if isinstance(entry, dict) else {}
        title = content.get("title")
        url = (content.get("canonicalUrl") or {}).get("url") or (content.get("clickThroughUrl") or {}).get("url")
        if not title or not url:
            continue
        items.append({
            "title": title, "summary": content.get("summary") or "",
            "source": (content.get("provider") or {}).get("displayName") or "",
            "url": url, "published_at": content.get("pubDate") or "",
        })
    if not items:
        return []
    return [{"type": "ticker_news", "items": items}]


DISPLAY_NORMALIZERS["yfinance_get_price_history"] = normalize_price_history
DISPLAY_NORMALIZERS["yfinance_get_ticker_info"] = normalize_ticker_info
DISPLAY_NORMALIZERS["yfinance_get_ticker_news"] = normalize_ticker_news
```

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/unit/test_display_normalizers.py tests/unit/test_display_middleware.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/multi_agent/display.py tests/unit/test_display_normalizers.py
git commit -m "feat(multi-agent): yfinance display normalizers (price_chart, ticker_info, ticker_news)"
```

---

### Task 5: `normalize_rag_sources` and `normalize_screenshot`

**Files:**
- Modify: `app/agent/multi_agent/display.py`, `tests/unit/test_display_normalizers.py`

**Interfaces:**
- Produces: `normalize_rag_sources` → `"search_knowledge_base"`, `normalize_screenshot` → `"browser_take_screenshot"`.
- Display shapes:
  - `{"type": "rag_sources", "sources": [{"filename", "page", "excerpt"}]}`
  - `{"type": "screenshot", "url"}` — `url` is `/workspace/screenshots/<filename>`, matching the existing `GET /workspace/screenshots/{filename}` route (`app/api/routers/workspace.py`).

`search_knowledge_base_tool` joins chunks with `\n\n` (`app/agent/tools/knowledge_base.py`), each prefixed `[Source: {filename}, page {page}] {excerpt}`. A chunk's own excerpt can itself contain blank lines, so the parser must **not** split on `\n\n` — it anchors on the `[Source: ..., page ...]` headers and slices between them.

`browser_take_screenshot`'s `ToolMessage.content` (after `StripToolImages` removes the image block, verified in `tests/unit/test_tool_output_image_stripping.py`) is `[{"type": "text", "text": "### Result\n- [Screenshot of viewport](screenshots/x.png)"}]` — already flattened to that text by `_content_text` before this normalizer runs.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_display_normalizers.py`:

```python
# Real format from search_knowledge_base_tool (knowledge_base.py): chunks
# joined by "\n\n", each "[Source: F, page N] excerpt". One excerpt here
# contains an internal blank line, to prove the parser doesn't split on it.
RAG_TEXT = (
    "[Source: Amazon-2024-10K.pdf, page 12] Net sales increased 11% to $637.9 billion.\n\n"
    "This growth was\n\ndriven by AWS.\n\n"
    "[Source: Amazon-2024-10K.pdf, page 45] Operating income was $68.6 billion."
)


def test_normalize_rag_sources_anchors_on_source_headers_not_blank_lines():
    displays = display.DISPLAY_NORMALIZERS["search_knowledge_base"](RAG_TEXT, {})
    assert displays == [{"type": "rag_sources", "sources": [
        {"filename": "Amazon-2024-10K.pdf", "page": "12",
         "excerpt": "Net sales increased 11% to $637.9 billion.\n\nThis growth was\n\ndriven by AWS."},
        {"filename": "Amazon-2024-10K.pdf", "page": "45", "excerpt": "Operating income was $68.6 billion."},
    ]}]


def test_normalize_rag_sources_with_no_results_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["search_knowledge_base"](
        "No relevant results found in the knowledge base for this query.", {}) == []


def test_normalize_rag_sources_on_a_search_failure_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["search_knowledge_base"]("Knowledge base search failed: timeout", {}) == []


# Real (post-StripToolImages) text for the local @playwright/mcp backend —
# verified in tests/unit/test_tool_output_image_stripping.py's own fixture.
SCREENSHOT_TEXT = "### Result\n- [Screenshot of viewport](screenshots/evidence.png)"


def test_normalize_screenshot_extracts_the_png_path():
    displays = display.DISPLAY_NORMALIZERS["browser_take_screenshot"](SCREENSHOT_TEXT, {})
    assert displays == [{"type": "screenshot", "url": "/workspace/screenshots/evidence.png"}]


def test_normalize_screenshot_with_no_png_shows_nothing():
    assert display.DISPLAY_NORMALIZERS["browser_take_screenshot"]("no page loaded yet", {}) == []
```

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/unit/test_display_normalizers.py -v`
Expected: the 5 new tests FAIL with `KeyError`.

- [ ] **Step 3: Implement** — append to `app/agent/multi_agent/display.py`:

```python
import re
from pathlib import Path

_SOURCE_HEADER = re.compile(r"\[Source: (.*?), page (.*?)\]\s*")
_PNG_PATH = re.compile(r"([\w./\\-]+\.png)")


def normalize_rag_sources(text: str, args: dict) -> list[dict]:
    matches = list(_SOURCE_HEADER.finditer(text))
    if not matches:
        return []
    sources = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sources.append({"filename": m.group(1), "page": m.group(2), "excerpt": text[start:end].strip()})
    return [{"type": "rag_sources", "sources": sources}]


def normalize_screenshot(text: str, args: dict) -> list[dict]:
    match = _PNG_PATH.search(text)
    if not match:
        return []
    filename = Path(match.group(1)).name
    return [{"type": "screenshot", "url": f"/workspace/screenshots/{filename}"}]


DISPLAY_NORMALIZERS["search_knowledge_base"] = normalize_rag_sources
DISPLAY_NORMALIZERS["browser_take_screenshot"] = normalize_screenshot
```

(Move the `import re` and `from pathlib import Path` to the top of the file, alongside the existing `import json`/`import logging`, rather than inline — Python style, not a functional difference.)

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/unit/test_display_normalizers.py tests/unit/test_display_middleware.py -v`
Expected: all PASS (18 tests total across both files).

- [ ] **Step 5: Commit**

```bash
git add app/agent/multi_agent/display.py tests/unit/test_display_normalizers.py
git commit -m "feat(multi-agent): normalize_rag_sources and normalize_screenshot"
```

---

### Task 6: Wire the middleware into the 4 specialists

**Files:**
- Modify: `app/agent/multi_agent/portfolio_agent.py`, `finance_agent.py`, `rag_agent.py`, `browser_agent.py`
- Modify: `tests/unit/test_copilot_endpoint.py`
- Test: `tests/unit/test_display_middleware.py` (browser ordering regression)

**Interfaces:**
- Consumes: `display.market_desk_display` (Task 1), the 7 registered normalizers (Tasks 2-5).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_display_middleware.py` — this is the ordering regression named in the Global Constraints (display middleware must see the *already-stripped* content in `browser_agent`, not the raw image block). It composes the two middleware instances exactly in the order Step 3 wires them in `browser_agent.py` (display middleware before `strip_tool_images`), without needing to import the built agent itself:

```python
def test_browser_agent_strips_images_before_enveloping():
    # Regression: AgentMiddleware.wrap_tool_call chains "first = outermost"
    # (langchain/agents/factory.py, _chain_tool_call_wrappers) — the display
    # middleware must be listed BEFORE strip_tool_images in browser_agent's
    # middleware list, so it only ever sees text, never a raw image block.
    from app.agent.multi_agent.common import strip_tool_images

    image_and_text = [
        {"type": "text", "text": "### Result\n- [Screenshot of viewport](screenshots/x.png)"},
        {"type": "image", "data": "base64...", "mimeType": "image/png"},
    ]

    def raw_handler(request):
        return ToolMessage(content=image_and_text, name="browser_take_screenshot", tool_call_id="c1")

    # Simulate the chain exactly as build_browser_agent() wires it: display
    # middleware listed before strip_tool_images -> display's handler(request)
    # call resolves through strip_tool_images first.
    def strip_then_raw(request):
        return strip_tool_images.wrap_tool_call(request, raw_handler)

    result = display.market_desk_display.wrap_tool_call(_request("browser_take_screenshot", {}), strip_then_raw)
    envelope = json.loads(result.content)
    assert envelope["displays"] == [{"type": "screenshot", "url": "/workspace/screenshots/x.png"}]
    assert "base64" not in result.content
```

Also append to `tests/unit/test_copilot_endpoint.py` (end-to-end, per the spec's testing section) — a fixture mirroring the existing `finance_client` one, but routing to `portfolio_agent` with a fake `portfolio_metrics_tool`:

```python
@pytest.fixture
def portfolio_client():
    call = {"id": "p1", "name": "portfolio_metrics",
            "args": {"positions": [{"ticker": "BND", "shares": 300, "avg_cost": 73.33, "price": 70.63, "sector": "ETF"}]}}
    fake = StreamingFakeToolModel([AIMessage(content="", tool_calls=[call]),
                                    AIMessage(content="BND is worth $21,189.")])
    with ExitStack() as stack:
        stack.enter_context(patch.object(portfolio_mod, "specialist_model", return_value=fake))
        client, _ = _client_with(stack, "portfolio_agent")
        yield client


def test_portfolio_result_is_enveloped_for_the_frontend(portfolio_client):
    events = _events(portfolio_client.post(PATH, json=_run_input(
        "t9", "r1", [{"id": "u1", "role": "user", "content": "BND value?"}])).text)
    results = [e for e in events if e["type"] == "TOOL_CALL_RESULT"]
    assert results, "expected a TOOL_CALL_RESULT event"
    envelope = json.loads(results[0]["content"])
    assert envelope["displays"][0]["type"] == "portfolio_table"
    assert envelope["displays"][1]["type"] == "portfolio_chart"
```

Add the matching import near the top of `tests/unit/test_copilot_endpoint.py`: `from app.agent.multi_agent import portfolio_agent as portfolio_mod`.

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/unit/test_display_middleware.py -k browser_agent -v`
Run: `uv run pytest tests/unit/test_copilot_endpoint.py -k portfolio_result -v`
Expected: the ordering test FAILs on `AttributeError`/`ImportError` if `strip_tool_images` import path is wrong (it isn't — verify against `app/agent/multi_agent/common.py`); the endpoint test FAILs because `portfolio_metrics`'s content is still plain JSON, not an envelope (`envelope["displays"]` → `KeyError`/`json.JSONDecodeError` won't trigger — content is valid JSON already, but has no `"displays"` key, so this assertion fails with `KeyError: 'displays'`).

- [ ] **Step 3: Implement** — wire each specialist:

`app/agent/multi_agent/portfolio_agent.py` — add the import and middleware:

```python
from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.multi_agent.display import market_desk_display
```

```python
        middleware=[*base_middleware(), market_desk_display],
```

`app/agent/multi_agent/finance_agent.py`:

```python
from app.agent.multi_agent.common import base_middleware, redact_emails, specialist_model
from app.agent.multi_agent.display import market_desk_display
```

```python
        middleware=[*base_middleware(), redact_emails(), market_desk_display],
```

`app/agent/multi_agent/rag_agent.py`:

```python
from app.agent.multi_agent.common import base_middleware, redact_emails, specialist_model
from app.agent.multi_agent.display import market_desk_display
```

```python
        middleware=[*base_middleware(), redact_emails(), market_desk_display],
```

`app/agent/multi_agent/browser_agent.py` — **order matters**: `market_desk_display` goes *before* `strip_tool_images`, so it runs on already-stripped content:

```python
from app.agent.multi_agent.common import base_middleware, redact_emails, specialist_model, strip_tool_images
from app.agent.multi_agent.display import market_desk_display
```

```python
        middleware=[*base_middleware(), redact_emails(), market_desk_display, strip_tool_images],
```

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/unit/test_display_middleware.py tests/unit/test_copilot_endpoint.py tests/unit/test_multi_agent_portfolio_agent.py tests/unit/test_multi_agent_finance_agent.py tests/unit/test_multi_agent_rag_agent.py tests/unit/test_multi_agent_browser_agent.py -v`
Expected: all PASS. The 4 existing `test_multi_agent_*_agent.py` files must still pass unchanged — they assert tool *names*, not middleware lists, so adding a middleware entry doesn't touch what they check.

- [ ] **Step 5: Assert the single-agent graph is untouched**

Run: `uv run python -c "import app.agent.graph, sys; assert 'app.agent.multi_agent.display' not in sys.modules, 'single-agent graph pulled in the Market Desk display middleware'; print('ok')"`
Expected: prints `ok` — importing the single-agent graph module must never import `display.py` as a side effect.

- [ ] **Step 6: Full backend suite**

Run: `uv run pytest tests/ -q -p no:cacheprovider`
Expected: all pass (255 + ~25 new ≈ 280).

- [ ] **Step 7: Commit**

```bash
git add app/agent/multi_agent/portfolio_agent.py app/agent/multi_agent/finance_agent.py app/agent/multi_agent/rag_agent.py app/agent/multi_agent/browser_agent.py tests/unit/test_display_middleware.py tests/unit/test_copilot_endpoint.py
git commit -m "feat(multi-agent): wire the display middleware into the 4 specialists (browser ordering verified)"
```

---

### Task 7: `POST /copilot/uploads`

**Files:**
- Modify: `app/api/routers/copilot.py`
- Test: `tests/unit/test_copilot_uploads.py`

**Interfaces:**
- Produces: `POST /copilot/uploads` (multipart `file` field) → `{"path": "uploads/<safe-name>"}`. Gated by `COPILOT_ENABLED` (same router as the rest of `copilot.py`).

- [ ] **Step 1: Write the failing tests** — create `tests/unit/test_copilot_uploads.py`:

```python
"""POST /copilot/uploads: lands a chat attachment on disk under
WORKSPACE_ROOT/uploads/ so the agent can read it back with the existing
read_text_file/list_directory tools. No GET route — only the agent reads it."""
import io

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.copilot import router
from app.core.config import settings


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", tmp_path)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_saves_the_file_under_uploads(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/copilot/uploads", files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")})
    assert resp.status_code == 200
    path = resp.json()["path"]
    assert path.startswith("uploads/") and path.endswith("_report.pdf")
    assert (tmp_path / path).read_bytes() == b"%PDF-1.4 fake"


def test_sanitizes_a_path_traversal_filename(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/copilot/uploads", files={"file": ("../../etc/passwd", io.BytesIO(b"x"), "text/plain")})
    assert resp.status_code == 200
    path = resp.json()["path"]
    assert ".." not in path
    saved = tmp_path / path
    assert saved.is_relative_to(tmp_path / "uploads")


def test_rejects_an_oversized_file(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr("app.api.routers.copilot.MAX_UPLOAD_BYTES", 10)
    resp = client.post("/copilot/uploads", files={"file": ("big.txt", io.BytesIO(b"x" * 100), "text/plain")})
    assert resp.status_code == 413


def test_two_uploads_with_the_same_filename_do_not_collide(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    p1 = client.post("/copilot/uploads", files={"file": ("notes.txt", io.BytesIO(b"a"), "text/plain")}).json()["path"]
    p2 = client.post("/copilot/uploads", files={"file": ("notes.txt", io.BytesIO(b"b"), "text/plain")}).json()["path"]
    assert p1 != p2
    assert (tmp_path / p1).read_bytes() == b"a"
    assert (tmp_path / p2).read_bytes() == b"b"
```

Also append to `tests/unit/test_copilot_wiring.py` (the disabled-by-default gate the rest of the router already gets):

```python
def test_uploads_route_absent_when_disabled_returns_404(monkeypatch):
    monkeypatch.setattr(server.settings, "COPILOT_ENABLED", False)
    app = FastAPI()
    server.include_market_desk_routes(app)
    resp = TestClient(app).post("/copilot/uploads", files={"file": ("x.txt", b"x")})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/unit/test_copilot_uploads.py -v`
Expected: FAIL — `404 Not Found` (the route doesn't exist yet) instead of the expected status codes.

- [ ] **Step 3: Implement** — in `app/api/routers/copilot.py`, add imports and the route:

```python
from uuid import uuid4

from fastapi import File, UploadFile

from app.core.config import settings
```

```python
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # matches the frontend's AttachmentsConfig.maxSize


@router.post("/copilot/uploads")
async def upload_to_workspace(file: UploadFile = File(...)) -> dict:
    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large.")
    safe_name = Path(file.filename or "upload").name  # strips ".." / directory components
    unique_name = f"{uuid4().hex[:8]}_{safe_name}"
    uploads_dir = Path(settings.WORKSPACE_ROOT) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / unique_name).write_bytes(body)
    return {"path": f"uploads/{unique_name}"}
```

Add `from pathlib import Path` to the existing import block if not already present (it isn't, in the current file).

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/unit/test_copilot_uploads.py tests/unit/test_copilot_wiring.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/copilot.py tests/unit/test_copilot_uploads.py tests/unit/test_copilot_wiring.py
git commit -m "feat(api): POST /copilot/uploads lands chat attachments in the workspace"
```

---

### Task 8: Frontend display contract (`types.ts`, `parseDisplay.ts`)

**Files:**
- Create: `frontend/src/desk/displays/types.ts`, `frontend/src/desk/displays/parseDisplay.ts`
- Test: `frontend/src/desk/displays/parseDisplay.test.ts`

**Interfaces:**
- Produces (consumed by every later frontend task):

```ts
export type DisplayPayload =
  | { type: "portfolio_table"; positions: {ticker: string; shares: number; price: number; market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number; weight_pct: number; sector: string | null}[]; totals: {market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number} }
  | { type: "portfolio_chart"; slices: {ticker: string; weight_pct: number}[] }
  | { type: "price_chart"; ticker: string; points: {date: string; close: number}[] }
  | { type: "ticker_info"; ticker: string; name: string; sector: string | null; industry: string | null; current_price: number; currency: string; market_cap: number | null; fifty_two_week_low: number | null; fifty_two_week_high: number | null }
  | { type: "ticker_news"; items: {title: string; summary: string; source: string; url: string; published_at: string}[] }
  | { type: "concentration_alert"; threshold_pct: number; breaches: {label: string; ticker: string; weight_pct: number; market_value: number}[] }
  | { type: "screenshot"; url: string }
  | { type: "rag_sources"; sources: {filename: string; page: string; excerpt: string}[] };

export interface DisplayEnvelope { summary: string; displays: DisplayPayload[] }
export function parseDisplay(raw: unknown): DisplayEnvelope | null;
```

- [ ] **Step 1: Write the failing test** — create `frontend/src/desk/displays/parseDisplay.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { parseDisplay } from "./parseDisplay";

const portfolioTable = {
  type: "portfolio_table",
  positions: [{ ticker: "BND", shares: 300, price: 70.63, market_value: 21189, cost_basis: 21999,
                unrealized_pnl: -810, unrealized_pnl_pct: -3.68, weight_pct: 13.62, sector: "ETF" }],
  totals: { market_value: 21189, cost_basis: 21999, unrealized_pnl: -810, unrealized_pnl_pct: -3.68 },
};

describe("parseDisplay", () => {
  it("returns the envelope for a valid payload", () => {
    const envelope = parseDisplay(JSON.stringify({ summary: "text", displays: [portfolioTable] }));
    expect(envelope).toEqual({ summary: "text", displays: [portfolioTable] });
  });

  it("returns null for text that isn't JSON", () => {
    expect(parseDisplay("plain tool text, no envelope")).toBeNull();
  });

  it("returns null when there is no displays array", () => {
    expect(parseDisplay(JSON.stringify({ summary: "text" }))).toBeNull();
  });

  it("drops an entry with an unknown type but keeps the valid ones", () => {
    const envelope = parseDisplay(JSON.stringify({
      summary: "text",
      displays: [portfolioTable, { type: "some_future_type", whatever: 1 }],
    }));
    expect(envelope?.displays).toEqual([portfolioTable]);
  });

  it("drops an entry of a known type missing a required field", () => {
    const envelope = parseDisplay(JSON.stringify({
      summary: "text",
      displays: [portfolioTable, { type: "screenshot" }],  // missing "url"
    }));
    expect(envelope?.displays).toEqual([portfolioTable]);
  });

  it("returns an envelope with an empty displays list rather than null", () => {
    expect(parseDisplay(JSON.stringify({ summary: "text", displays: [] }))).toEqual({ summary: "text", displays: [] });
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd frontend && npx vitest run parseDisplay`
Expected: FAIL — cannot resolve `./parseDisplay`.

- [ ] **Step 3: Implement** — create `frontend/src/desk/displays/types.ts`:

```ts
// Wire contract with app/agent/multi_agent/display.py's DISPLAY_NORMALIZERS.
// Keys are snake_case, matching the Python source dicts 1:1 (no case-mapping
// layer), the same convention this codebase's ApproveResponse already uses.

export interface PortfolioPosition {
  ticker: string;
  shares: number;
  price: number;
  market_value: number;
  cost_basis: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  weight_pct: number;
  sector: string | null;
}

export type DisplayPayload =
  | { type: "portfolio_table"; positions: PortfolioPosition[]; totals: { market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number } }
  | { type: "portfolio_chart"; slices: { ticker: string; weight_pct: number }[] }
  | { type: "price_chart"; ticker: string; points: { date: string; close: number }[] }
  | { type: "ticker_info"; ticker: string; name: string; sector: string | null; industry: string | null; current_price: number; currency: string; market_cap: number | null; fifty_two_week_low: number | null; fifty_two_week_high: number | null }
  | { type: "ticker_news"; items: { title: string; summary: string; source: string; url: string; published_at: string }[] }
  | { type: "concentration_alert"; threshold_pct: number; breaches: { label: string; ticker: string; weight_pct: number; market_value: number }[] }
  | { type: "screenshot"; url: string }
  | { type: "rag_sources"; sources: { filename: string; page: string; excerpt: string }[] };

export interface DisplayEnvelope {
  summary: string;
  displays: DisplayPayload[];
}
```

Create `frontend/src/desk/displays/parseDisplay.ts`:

```ts
import type { DisplayEnvelope, DisplayPayload } from "./types";

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// One predicate per type, checking only the fields the frontend actually
// reads — enough to catch a malformed/future entry without over-validating.
const VALIDATORS: Record<DisplayPayload["type"], (d: Record<string, unknown>) => boolean> = {
  portfolio_table: (d) => Array.isArray(d.positions) && isRecord(d.totals),
  portfolio_chart: (d) => Array.isArray(d.slices),
  price_chart: (d) => typeof d.ticker === "string" && Array.isArray(d.points),
  ticker_info: (d) => typeof d.name === "string" && typeof d.current_price === "number",
  ticker_news: (d) => Array.isArray(d.items),
  concentration_alert: (d) => Array.isArray(d.breaches),
  screenshot: (d) => typeof d.url === "string",
  rag_sources: (d) => Array.isArray(d.sources),
};

function isValidDisplay(entry: unknown): entry is DisplayPayload {
  if (!isRecord(entry) || typeof entry.type !== "string") return false;
  const validate = VALIDATORS[entry.type as DisplayPayload["type"]];
  return validate ? validate(entry) : false;
}

export function parseDisplay(raw: unknown): DisplayEnvelope | null {
  if (typeof raw !== "string") return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(data) || typeof data.summary !== "string" || !Array.isArray(data.displays)) return null;
  return { summary: data.summary, displays: data.displays.filter(isValidDisplay) };
}
```

- [ ] **Step 4: Run, expect PASS**

Run: `cd frontend && npx vitest run parseDisplay`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/desk/displays/types.ts frontend/src/desk/displays/parseDisplay.ts frontend/src/desk/displays/parseDisplay.test.ts
git commit -m "feat(frontend): Market Desk display envelope contract (types + parseDisplay)"
```

---

### Task 9: `PortfolioTable` and `PortfolioPieChart`

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json`
- Create: `frontend/src/desk/displays/PortfolioTable.tsx`, `frontend/src/desk/displays/PortfolioPieChart.tsx`
- Test: `frontend/src/desk/displays/PortfolioTable.test.tsx`, `frontend/src/desk/displays/PortfolioPieChart.test.tsx`

**Interfaces:**
- Consumes: `PortfolioPosition`, the `portfolio_table`/`portfolio_chart` variants of `DisplayPayload` (Task 8).
- Produces: `export function PortfolioTable({ display }: { display: Extract<DisplayPayload, {type: "portfolio_table"}> })`, `export function PortfolioPieChart({ display }: { display: Extract<DisplayPayload, {type: "portfolio_chart"}> })`.

- [ ] **Step 1: Add the dependency**

Run (from `frontend/`): `npm install --save-exact recharts@3.10.1`
Expected: `package.json` has `"recharts": "3.10.1"` (exact), matching how `@copilotkit/react-core` is pinned.

- [ ] **Step 2: Write the failing tests** — create `frontend/src/desk/displays/PortfolioTable.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PortfolioTable } from "./PortfolioTable";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "portfolio_table" }> = {
  type: "portfolio_table",
  positions: [
    { ticker: "BND", shares: 300, price: 70.63, market_value: 21189, cost_basis: 21999,
      unrealized_pnl: -810, unrealized_pnl_pct: -3.68, weight_pct: 13.62, sector: "ETF" },
    { ticker: "NVDA", shares: 71, price: 1259.66, market_value: 89436, cost_basis: 12280,
      unrealized_pnl: 77156, unrealized_pnl_pct: 628.31, weight_pct: 57.5, sector: "Technology" },
  ],
  totals: { market_value: 155564.81, cost_basis: 64179, unrealized_pnl: 91385.81, unrealized_pnl_pct: 142.39 },
};

describe("PortfolioTable", () => {
  it("shows one row per position with ticker and weight", () => {
    render(<PortfolioTable display={display} />);
    expect(screen.getByText("BND")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("13.62%")).toBeInTheDocument();
  });

  it("shows the portfolio total market value", () => {
    render(<PortfolioTable display={display} />);
    expect(screen.getByText("$155,564.81")).toBeInTheDocument();
  });

  it("colors a losing position's P&L differently from a winning one", () => {
    render(<PortfolioTable display={display} />);
    const loss = screen.getByText("-$810.00");
    const gain = screen.getByText("$77,156.00");
    expect(loss.className).toContain("terminal-danger");
    expect(gain.className).toContain("terminal-accent");
  });
});
```

Create `frontend/src/desk/displays/PortfolioPieChart.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PortfolioPieChart } from "./PortfolioPieChart";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "portfolio_chart" }> = {
  type: "portfolio_chart",
  slices: [{ ticker: "BND", weight_pct: 13.62 }, { ticker: "NVDA", weight_pct: 57.5 }],
};

describe("PortfolioPieChart", () => {
  it("renders a legend entry per slice", () => {
    render(<PortfolioPieChart display={display} />);
    expect(screen.getByText(/BND/)).toBeInTheDocument();
    expect(screen.getByText(/NVDA/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run, expect FAIL**

Run: `cd frontend && npx vitest run PortfolioTable PortfolioPieChart`
Expected: FAIL — cannot resolve the two component modules.

- [ ] **Step 4: Implement** — create `frontend/src/desk/displays/PortfolioTable.tsx`:

```tsx
import type { DisplayPayload } from "./types";

const money = (n: number) =>
  (n < 0 ? "-" : "") + "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function PortfolioTable({ display }: { display: Extract<DisplayPayload, { type: "portfolio_table" }> }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-terminal-border bg-terminal-panel p-3 font-mono text-xs text-terminal-text">
      <table className="w-full">
        <thead>
          <tr className="text-left text-terminal-muted">
            <th className="pb-1.5 pr-3">Ticker</th>
            <th className="pb-1.5 pr-3">Shares</th>
            <th className="pb-1.5 pr-3">Value</th>
            <th className="pb-1.5 pr-3">P&amp;L</th>
            <th className="pb-1.5">Weight</th>
          </tr>
        </thead>
        <tbody>
          {display.positions.map((p) => (
            <tr key={p.ticker} className="border-t border-terminal-border/50">
              <td className="py-1 pr-3 font-semibold">{p.ticker}</td>
              <td className="py-1 pr-3">{p.shares}</td>
              <td className="py-1 pr-3">{money(p.market_value)}</td>
              <td className={`py-1 pr-3 ${p.unrealized_pnl < 0 ? "text-terminal-danger" : "text-terminal-accent"}`}>
                {money(p.unrealized_pnl)}
              </td>
              <td className="py-1">{p.weight_pct.toFixed(2)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 border-t border-terminal-border pt-2 text-terminal-accent">
        Total: {money(display.totals.market_value)}
      </div>
    </div>
  );
}
```

Create `frontend/src/desk/displays/PortfolioPieChart.tsx`:

```tsx
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { DisplayPayload } from "./types";

// Terminal palette, cycled per slice — no new colors introduced.
const COLORS = ["#34d399", "#fbbf24", "#f87171", "#6b7a8d", "#1e3a5f", "#2563eb"];

export function PortfolioPieChart({ display }: { display: Extract<DisplayPayload, { type: "portfolio_chart" }> }) {
  const data = display.slices.map((s) => ({ name: s.ticker, value: s.weight_pct }));
  return (
    <div className="h-56 w-full rounded-xl border border-terminal-border bg-terminal-panel p-2">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={40} outerRadius={70}>
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip contentStyle={{ background: "#0f1620", border: "1px solid #1c2733", fontSize: 11 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 5: Run, expect PASS**

Run: `cd frontend && npx vitest run PortfolioTable PortfolioPieChart`
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/desk/displays/PortfolioTable.tsx frontend/src/desk/displays/PortfolioTable.test.tsx frontend/src/desk/displays/PortfolioPieChart.tsx frontend/src/desk/displays/PortfolioPieChart.test.tsx
git commit -m "feat(frontend): PortfolioTable and PortfolioPieChart display components"
```

---

### Task 10: `PriceChart`

**Files:**
- Create: `frontend/src/desk/displays/PriceChart.tsx`
- Test: `frontend/src/desk/displays/PriceChart.test.tsx`

**Interfaces:**
- Consumes: the `price_chart` variant of `DisplayPayload` (Task 8), `recharts` (Task 9).
- Produces: `export function PriceChart({ display }: { display: Extract<DisplayPayload, {type: "price_chart"}> })`.

- [ ] **Step 1: Write the failing test** — create `frontend/src/desk/displays/PriceChart.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PriceChart } from "./PriceChart";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "price_chart" }> = {
  type: "price_chart",
  ticker: "AAPL",
  points: [
    { date: "2026-09-21", close: 338.98 },
    { date: "2026-09-22", close: 339.75 },
    { date: "2026-09-23", close: 337.02 },
  ],
};

describe("PriceChart", () => {
  it("shows the ticker in the title", () => {
    render(<PriceChart display={display} />);
    expect(screen.getByText(/AAPL/)).toBeInTheDocument();
  });

  it("renders a chart container for each point (smoke test via recharts' surface)", () => {
    const { container } = render(<PriceChart display={display} />);
    expect(container.querySelector(".recharts-responsive-container")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd frontend && npx vitest run PriceChart`
Expected: FAIL — cannot resolve `./PriceChart`.

- [ ] **Step 3: Implement** — create `frontend/src/desk/displays/PriceChart.tsx`:

```tsx
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DisplayPayload } from "./types";

export function PriceChart({ display }: { display: Extract<DisplayPayload, { type: "price_chart" }> }) {
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel p-3">
      <div className="mb-2 font-mono text-xs font-semibold text-terminal-text">{display.ticker || "Price history"}</div>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={display.points}>
            <XAxis dataKey="date" tick={{ fill: "#6b7a8d", fontSize: 10 }} />
            <YAxis domain={["auto", "auto"]} tick={{ fill: "#6b7a8d", fontSize: 10 }} width={50} />
            <Tooltip contentStyle={{ background: "#0f1620", border: "1px solid #1c2733", fontSize: 11 }} />
            <Line type="monotone" dataKey="close" stroke="#34d399" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run, expect PASS**

Run: `cd frontend && npx vitest run PriceChart`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/desk/displays/PriceChart.tsx frontend/src/desk/displays/PriceChart.test.tsx
git commit -m "feat(frontend): PriceChart display component"
```

---

### Task 11: `TickerInfoCard` and `TickerNewsList`

**Files:**
- Create: `frontend/src/desk/displays/TickerInfoCard.tsx`, `frontend/src/desk/displays/TickerNewsList.tsx`
- Test: `frontend/src/desk/displays/TickerInfoCard.test.tsx`, `frontend/src/desk/displays/TickerNewsList.test.tsx`

**Interfaces:**
- Consumes: the `ticker_info`/`ticker_news` variants of `DisplayPayload` (Task 8).
- Produces: `export function TickerInfoCard({ display }: {...})`, `export function TickerNewsList({ display }: {...})`.

- [ ] **Step 1: Write the failing tests** — create `frontend/src/desk/displays/TickerInfoCard.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TickerInfoCard } from "./TickerInfoCard";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "ticker_info" }> = {
  type: "ticker_info", ticker: "AAPL", name: "Apple Inc.", sector: "Technology",
  industry: "Consumer Electronics", current_price: 341.07, currency: "USD",
  market_cap: 4977636933632, fifty_two_week_low: 243.42, fifty_two_week_high: 345.34,
};

describe("TickerInfoCard", () => {
  it("shows the name, ticker and current price", () => {
    render(<TickerInfoCard display={display} />);
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText(/AAPL/)).toBeInTheDocument();
    expect(screen.getByText("$341.07")).toBeInTheDocument();
  });

  it("shows the 52-week range", () => {
    render(<TickerInfoCard display={display} />);
    expect(screen.getByText(/243.42/)).toBeInTheDocument();
    expect(screen.getByText(/345.34/)).toBeInTheDocument();
  });

  it("handles a null sector/industry without crashing", () => {
    render(<TickerInfoCard display={{ ...display, sector: null, industry: null }} />);
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
  });
});
```

Create `frontend/src/desk/displays/TickerNewsList.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TickerNewsList } from "./TickerNewsList";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "ticker_news" }> = {
  type: "ticker_news",
  items: [
    { title: "Apple stock ticks up", summary: "Shares rose 1%.", source: "Reuters",
      url: "https://finance.yahoo.com/b", published_at: "2026-09-27T10:00:00Z" },
  ],
};

describe("TickerNewsList", () => {
  it("shows the headline as a link to the article", () => {
    render(<TickerNewsList display={display} />);
    const link = screen.getByRole("link", { name: /Apple stock ticks up/ });
    expect(link).toHaveAttribute("href", "https://finance.yahoo.com/b");
  });

  it("shows the source", () => {
    render(<TickerNewsList display={display} />);
    expect(screen.getByText("Reuters")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd frontend && npx vitest run TickerInfoCard TickerNewsList`
Expected: FAIL — cannot resolve the two modules.

- [ ] **Step 3: Implement** — create `frontend/src/desk/displays/TickerInfoCard.tsx`:

```tsx
import type { DisplayPayload } from "./types";

export function TickerInfoCard({ display }: { display: Extract<DisplayPayload, { type: "ticker_info" }> }) {
  return (
    <div className="rounded-xl border border-terminal-border bg-terminal-panel p-3 font-mono text-xs text-terminal-text">
      <div className="flex items-baseline justify-between">
        <span className="font-semibold">{display.name}</span>
        <span className="text-terminal-muted">{display.ticker}</span>
      </div>
      <div className="mt-1 text-lg text-terminal-accent">
        ${display.current_price.toFixed(2)} <span className="text-xs text-terminal-muted">{display.currency}</span>
      </div>
      {(display.sector || display.industry) && (
        <div className="mt-1 text-terminal-muted">
          {[display.sector, display.industry].filter(Boolean).join(" · ")}
        </div>
      )}
      {(display.fifty_two_week_low != null && display.fifty_two_week_high != null) && (
        <div className="mt-1 text-terminal-muted">
          52w range: {display.fifty_two_week_low.toFixed(2)} – {display.fifty_two_week_high.toFixed(2)}
        </div>
      )}
    </div>
  );
}
```

Create `frontend/src/desk/displays/TickerNewsList.tsx`:

```tsx
import type { DisplayPayload } from "./types";

export function TickerNewsList({ display }: { display: Extract<DisplayPayload, { type: "ticker_news" }> }) {
  return (
    <div className="flex flex-col gap-2">
      {display.items.map((item, i) => (
        <a
          key={i}
          href={item.url}
          target="_blank"
          rel="noreferrer"
          className="rounded-xl border border-terminal-border bg-terminal-panel p-3 font-mono text-xs text-terminal-text hover:border-terminal-accent/40"
        >
          <div className="font-semibold">{item.title}</div>
          {item.summary && <div className="mt-1 text-terminal-muted">{item.summary}</div>}
          <div className="mt-1 text-[10px] text-terminal-muted">{item.source}</div>
        </a>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run, expect PASS**

Run: `cd frontend && npx vitest run TickerInfoCard TickerNewsList`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/desk/displays/TickerInfoCard.tsx frontend/src/desk/displays/TickerInfoCard.test.tsx frontend/src/desk/displays/TickerNewsList.tsx frontend/src/desk/displays/TickerNewsList.test.tsx
git commit -m "feat(frontend): TickerInfoCard and TickerNewsList display components"
```

---

### Task 12: `ConcentrationAlert`, `ScreenshotCard`, `RagSourceCards`

**Files:**
- Create: `frontend/src/desk/displays/ConcentrationAlert.tsx`, `frontend/src/desk/displays/ScreenshotCard.tsx`, `frontend/src/desk/displays/RagSourceCards.tsx`
- Test: one `*.test.tsx` per component

**Interfaces:**
- Consumes: the `concentration_alert`/`screenshot`/`rag_sources` variants of `DisplayPayload` (Task 8).
- Produces: `ConcentrationAlert`, `ScreenshotCard`, `RagSourceCards`, each `({ display }: {...})`.

- [ ] **Step 1: Write the failing tests** — create `frontend/src/desk/displays/ConcentrationAlert.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConcentrationAlert } from "./ConcentrationAlert";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "concentration_alert" }> = {
  type: "concentration_alert", threshold_pct: 30,
  breaches: [{ label: "Margaret Collins", ticker: "NVDA", weight_pct: 57.5, market_value: 89436 }],
};

describe("ConcentrationAlert", () => {
  it("shows the client, ticker and weight for each breach", () => {
    render(<ConcentrationAlert display={display} />);
    expect(screen.getByText(/Margaret Collins/)).toBeInTheDocument();
    expect(screen.getByText(/NVDA/)).toBeInTheDocument();
    expect(screen.getByText(/57.5%/)).toBeInTheDocument();
  });
});
```

Create `frontend/src/desk/displays/ScreenshotCard.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScreenshotCard } from "./ScreenshotCard";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "screenshot" }> = { type: "screenshot", url: "/workspace/screenshots/evidence.png" };

describe("ScreenshotCard", () => {
  it("renders an image pointing at the workspace route", () => {
    render(<ScreenshotCard display={display} />);
    expect(screen.getByRole("img")).toHaveAttribute("src", "/workspace/screenshots/evidence.png");
  });
});
```

Create `frontend/src/desk/displays/RagSourceCards.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RagSourceCards } from "./RagSourceCards";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "rag_sources" }> = {
  type: "rag_sources",
  sources: [{ filename: "Amazon-2024-10K.pdf", page: "12", excerpt: "Net sales increased 11%." }],
};

describe("RagSourceCards", () => {
  it("shows the filename and page, collapsed by default", () => {
    render(<RagSourceCards display={display} />);
    expect(screen.getByText(/Amazon-2024-10K.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/page 12/)).toBeInTheDocument();
    expect(screen.queryByText("Net sales increased 11%.")).not.toBeInTheDocument();
  });

  it("expands the excerpt on click", async () => {
    const user = userEvent.setup();
    render(<RagSourceCards display={display} />);
    await user.click(screen.getByText(/Amazon-2024-10K.pdf/));
    expect(screen.getByText("Net sales increased 11%.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd frontend && npx vitest run ConcentrationAlert ScreenshotCard RagSourceCards`
Expected: FAIL — cannot resolve the three modules.

- [ ] **Step 3: Implement** — create `frontend/src/desk/displays/ConcentrationAlert.tsx`:

```tsx
import type { DisplayPayload } from "./types";

export function ConcentrationAlert({ display }: { display: Extract<DisplayPayload, { type: "concentration_alert" }> }) {
  return (
    <div className="rounded-xl border border-terminal-warn/40 bg-terminal-panel p-3 font-mono text-xs text-terminal-text">
      <div className="mb-2 text-terminal-warn">Concentration &gt; {display.threshold_pct}%</div>
      <div className="flex flex-col gap-1.5">
        {display.breaches.map((b, i) => (
          <div key={i} className="flex justify-between">
            <span>{b.label} — {b.ticker}</span>
            <span className="text-terminal-warn">{b.weight_pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

Create `frontend/src/desk/displays/ScreenshotCard.tsx`:

```tsx
import type { DisplayPayload } from "./types";

export function ScreenshotCard({ display }: { display: Extract<DisplayPayload, { type: "screenshot" }> }) {
  return (
    <div className="overflow-hidden rounded-xl border border-terminal-border bg-terminal-panel p-2">
      <a href={display.url} target="_blank" rel="noreferrer">
        <img src={display.url} alt="Browser screenshot" className="w-full rounded" />
      </a>
    </div>
  );
}
```

Create `frontend/src/desk/displays/RagSourceCards.tsx`:

```tsx
import { useState } from "react";
import type { DisplayPayload } from "./types";

export function RagSourceCards({ display }: { display: Extract<DisplayPayload, { type: "rag_sources" }> }) {
  return (
    <div className="flex flex-col gap-1.5">
      {display.sources.map((s, i) => (
        <SourceCard key={i} source={s} />
      ))}
    </div>
  );
}

function SourceCard({ source }: { source: { filename: string; page: string; excerpt: string } }) {
  const [open, setOpen] = useState(false);
  return (
    <button
      type="button"
      onClick={() => setOpen((v) => !v)}
      className="rounded-xl border border-terminal-border bg-terminal-panel p-2.5 text-left font-mono text-xs text-terminal-text hover:border-terminal-accent/40"
    >
      <div className="text-terminal-muted">
        {source.filename} · page {source.page}
      </div>
      {open && <div className="mt-1.5">{source.excerpt}</div>}
    </button>
  );
}
```

- [ ] **Step 4: Run, expect PASS**

Run: `cd frontend && npx vitest run ConcentrationAlert ScreenshotCard RagSourceCards`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/desk/displays/ConcentrationAlert.tsx frontend/src/desk/displays/ConcentrationAlert.test.tsx frontend/src/desk/displays/ScreenshotCard.tsx frontend/src/desk/displays/ScreenshotCard.test.tsx frontend/src/desk/displays/RagSourceCards.tsx frontend/src/desk/displays/RagSourceCards.test.tsx
git commit -m "feat(frontend): ConcentrationAlert, ScreenshotCard and RagSourceCards display components"
```

---

### Task 13: `useToolDisplay` — wire the 7 tools into `DeskBody`

**Files:**
- Create: `frontend/src/desk/displays/useToolDisplay.tsx`
- Modify: `frontend/src/desk/DeskView.tsx`
- Test: `frontend/src/desk/displays/useToolDisplay.test.tsx`

**Interfaces:**
- Consumes: `parseDisplay` (Task 8), all 8 display components (Tasks 9-12).
- Produces: `export function useToolDisplay(): void`, called once from `DeskBody`.

- [ ] **Step 1: Write the failing test** — create `frontend/src/desk/displays/useToolDisplay.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Capture every useRenderTool registration instead of a real CopilotKit
// provider — mirrors sub-project 1's DeskActivityRail.test.tsx pattern of
// mocking the SDK boundary and driving it directly.
const registrations: Record<string, (props: { status: string; result?: string }) => unknown> = {};
vi.mock("@copilotkit/react-core/v2", () => ({
  useRenderTool: (config: { name: string; render: (props: { status: string; result?: string }) => unknown }) => {
    registrations[config.name] = config.render;
  },
}));

import { useToolDisplay } from "./useToolDisplay";

function Harness() {
  useToolDisplay();
  return null;
}

describe("useToolDisplay", () => {
  it("registers a renderer for all 7 displayable tools", () => {
    render(<Harness />);
    expect(Object.keys(registrations).sort()).toEqual([
      "browser_take_screenshot", "concentration_screen", "portfolio_metrics",
      "search_knowledge_base", "yfinance_get_price_history", "yfinance_get_ticker_info",
      "yfinance_get_ticker_news",
    ]);
  });

  it("renders nothing while the tool call is still executing", () => {
    render(<Harness />);
    const result = registrations["portfolio_metrics"]({ status: "executing" });
    expect(result).toBeNull();
  });

  it("renders the matching component once the tool call completes", () => {
    render(<Harness />);
    const envelope = JSON.stringify({
      summary: "text",
      displays: [{ type: "portfolio_table", positions: [], totals: { market_value: 0, cost_basis: 0, unrealized_pnl: 0, unrealized_pnl_pct: 0 } }],
    });
    const { container } = render(<>{registrations["portfolio_metrics"]({ status: "complete", result: envelope })}</>);
    expect(container.querySelector("table")).toBeInTheDocument();
  });

  it("renders nothing when the result doesn't parse as a display envelope", () => {
    render(<Harness />);
    const result = registrations["portfolio_metrics"]({ status: "complete", result: "plain text answer" });
    expect(result).toBeNull();
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd frontend && npx vitest run useToolDisplay`
Expected: FAIL — cannot resolve `./useToolDisplay`.

- [ ] **Step 3: Implement** — create `frontend/src/desk/displays/useToolDisplay.tsx`:

```tsx
import { z } from "zod";
import { useRenderTool } from "@copilotkit/react-core/v2";
import { parseDisplay } from "./parseDisplay";
import { PortfolioTable } from "./PortfolioTable";
import { PortfolioPieChart } from "./PortfolioPieChart";
import { PriceChart } from "./PriceChart";
import { TickerInfoCard } from "./TickerInfoCard";
import { TickerNewsList } from "./TickerNewsList";
import { ConcentrationAlert } from "./ConcentrationAlert";
import { ScreenshotCard } from "./ScreenshotCard";
import { RagSourceCards } from "./RagSourceCards";
import type { DisplayPayload } from "./types";

function Rendered({ displays }: { displays: DisplayPayload[] }) {
  return (
    <div className="flex flex-col gap-2">
      {displays.map((d, i) => {
        switch (d.type) {
          case "portfolio_table": return <PortfolioTable key={i} display={d} />;
          case "portfolio_chart": return <PortfolioPieChart key={i} display={d} />;
          case "price_chart": return <PriceChart key={i} display={d} />;
          case "ticker_info": return <TickerInfoCard key={i} display={d} />;
          case "ticker_news": return <TickerNewsList key={i} display={d} />;
          case "concentration_alert": return <ConcentrationAlert key={i} display={d} />;
          case "screenshot": return <ScreenshotCard key={i} display={d} />;
          case "rag_sources": return <RagSourceCards key={i} display={d} />;
        }
      })}
    </div>
  );
}

function renderDisplayResult(props: { status: string; result?: string }) {
  // The activity rail already covers "still running"; nothing extra to show
  // here until the tool call actually has a result.
  if (props.status !== "complete") return null;
  const envelope = parseDisplay(props.result);
  if (!envelope || envelope.displays.length === 0) return null;
  return <Rendered displays={envelope.displays} />;
}

// Mirrors app/agent/multi_agent/display.py's DISPLAY_NORMALIZERS keys exactly.
const DISPLAYABLE_TOOLS = [
  "portfolio_metrics",
  "concentration_screen",
  "yfinance_get_price_history",
  "yfinance_get_ticker_info",
  "yfinance_get_ticker_news",
  "search_knowledge_base",
  "browser_take_screenshot",
] as const;

// One named registration per tool — leaves every other tool call (read_query,
// write_file, save_memory, browser_navigate, browser_snapshot, ...) to
// CopilotKit's own default card, completely untouched.
export function useToolDisplay(): void {
  for (const name of DISPLAYABLE_TOOLS) {
    // eslint-disable-next-line react-hooks/rules-of-hooks -- DISPLAYABLE_TOOLS is a fixed compile-time list, never conditional or reordered across renders.
    useRenderTool({ name, parameters: z.any(), render: renderDisplayResult });
  }
}
```

- [ ] **Step 4: Run, expect PASS**

Run: `cd frontend && npx vitest run useToolDisplay`
Expected: 4 PASS.

- [ ] **Step 5: Wire it into `DeskView.tsx`**

```tsx
import { useToolDisplay } from "./displays/useToolDisplay";
```

```tsx
function DeskBody({ threadId }: { threadId: string }) {
  useDeskInterrupt();
  useToolDisplay();
  return (
```

- [ ] **Step 6: Run the whole frontend suite and type-check**

Run: `cd frontend && npx vitest run && npx tsc -b`
Expected: all PASS, `tsc` exits 0.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/desk/displays/useToolDisplay.tsx frontend/src/desk/displays/useToolDisplay.test.tsx frontend/src/desk/DeskView.tsx
git commit -m "feat(frontend): wire the 7 display renderers into Market Desk chat"
```

---

### Task 14: Suggestions and file attachments

**Files:**
- Modify: `frontend/src/lib/api.ts`, `frontend/src/desk/DeskView.tsx`
- Test: `frontend/src/lib/api.test.ts` (new), `frontend/src/desk/DeskView.test.tsx` (new)

**Interfaces:**
- Consumes: `POST /copilot/uploads` (Task 7).
- Produces: `export async function uploadToWorkspace(file: File, base?: string): Promise<{ path: string }>` in `api.ts`.

- [ ] **Step 1: Write the failing tests** — create `frontend/src/lib/api.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadToWorkspace } from "./api";

describe("uploadToWorkspace", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ path: "uploads/ab12cd34_report.pdf" }),
    }));
  });

  it("posts the file as multipart form data and returns the saved path", async () => {
    const file = new File(["content"], "report.pdf", { type: "application/pdf" });
    const result = await uploadToWorkspace(file);
    expect(result).toEqual({ path: "uploads/ab12cd34_report.pdf" });

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/copilot/uploads");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("throws when the upload fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 413, text: async () => "too big" }));
    const file = new File(["x"], "big.bin");
    await expect(uploadToWorkspace(file)).rejects.toThrow("413");
  });
});
```

Create `frontend/src/desk/DeskView.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

const chatProps: Record<string, unknown>[] = [];
vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotKitProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  CopilotChat: (props: Record<string, unknown>) => {
    chatProps.push(props);
    return null;
  },
  HttpAgent: class {},
  useRenderTool: () => undefined,
  useConfigureSuggestions: () => undefined,
}));
vi.mock("./useDeskInterrupt", () => ({ useDeskInterrupt: () => undefined }));
vi.mock("./displays/useToolDisplay", () => ({ useToolDisplay: () => undefined }));

import { DeskView } from "./DeskView";

describe("DeskView", () => {
  it("enables chat attachments with an onUpload handler", () => {
    render(<DeskView threadId="t1" />);
    const props = chatProps[chatProps.length - 1];
    const attachments = props.attachments as { enabled: boolean; onUpload: unknown };
    expect(attachments.enabled).toBe(true);
    expect(typeof attachments.onUpload).toBe("function");
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd frontend && npx vitest run api.test DeskView.test`
Expected: FAIL — `uploadToWorkspace` doesn't exist; `DeskView` doesn't pass `attachments`.

- [ ] **Step 3: Implement** — append to `frontend/src/lib/api.ts`:

```ts
export async function uploadToWorkspace(file: File, base = API_BASE): Promise<{ path: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${base}/copilot/uploads`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`upload ${res.status}: ${await res.text()}`);
  return res.json();
}
```

Modify `frontend/src/desk/DeskView.tsx`:

```tsx
import { useMemo } from "react";
import { CopilotChat, CopilotKitProvider, HttpAgent, useConfigureSuggestions } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { MARKET_DESK_AGENT_ID, MARKET_DESK_URL } from "./constants";
import { DeskActivityRail } from "./DeskActivityRail";
import { useDeskInterrupt } from "./useDeskInterrupt";
import { useToolDisplay } from "./displays/useToolDisplay";
import { uploadToWorkspace } from "../lib/api";
```

```tsx
function DeskBody({ threadId }: { threadId: string }) {
  useDeskInterrupt();
  useToolDisplay();
  useConfigureSuggestions({
    suggestions: [
      { title: "Portfolio value", message: "What is the total value of a client's portfolio?" },
      { title: "Stock price", message: "What is AAPL trading at?" },
      { title: "Concentration risk", message: "Are any clients over-concentrated in one stock?" },
    ],
  }, []);
  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <CopilotChat
          agentId={MARKET_DESK_AGENT_ID}
          threadId={threadId}
          className="h-full"
          attachments={{
            enabled: true,
            maxSize: 20 * 1024 * 1024,
            onUpload: async (file) => {
              const { path } = await uploadToWorkspace(file);
              return { type: "url", value: path, metadata: { filename: file.name } };
            },
          }}
        />
      </main>
      <DeskActivityRail />
    </div>
  );
}
```

- [ ] **Step 4: Run, expect PASS**

Run: `cd frontend && npx vitest run api.test DeskView.test`
Expected: all PASS.

- [ ] **Step 5: Full frontend check**

Run: `cd frontend && npx vitest run && npx tsc -b && npm run build`
Expected: all PASS, `tsc` exits 0, build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts frontend/src/desk/DeskView.tsx frontend/src/desk/DeskView.test.tsx
git commit -m "feat(frontend): starter suggestions and chat file attachments (land in workspace/uploads)"
```

---

### Task 15: The upload note the agent actually reads

**Files:**
- Modify: `frontend/src/desk/DeskView.tsx`
- Test: `frontend/src/desk/DeskView.test.tsx`

**Interfaces:**
- Consumes: nothing new — this closes the loop the spec calls for: the agent must learn an attached file's path regardless of how the binary part itself is handled upstream.

**Mechanism (verified against `@copilotkit/shared`'s own type declaration, not guessed):** `AttachmentsConfig.onUpload`'s return value has an optional `metadata` field, documented as "Custom metadata from onUpload, included in the InputContent part." That means whatever `onUpload` returns in `metadata` is already placed inside the content part the model receives — no separate message-composition hook is needed. Task 14's `onUpload` currently returns `metadata: { filename: file.name }`, which tells the model a name but not where to find it. This task adds the actual instruction the specialist needs: the workspace-relative path and which existing tool to read it with.

- [ ] **Step 1: Write the failing test** — extend `frontend/src/desk/DeskView.test.tsx`:

```tsx
it("includes the saved workspace path as attachment metadata the model can read", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ path: "uploads/ab12_report.pdf" }) }));
  render(<DeskView threadId="t1" />);
  const props = chatProps[chatProps.length - 1];
  const attachments = props.attachments as { onUpload: (f: File) => Promise<{ type: string; value: string; metadata?: Record<string, unknown> }> };
  const file = new File(["x"], "report.pdf", { type: "application/pdf" });
  const result = await attachments.onUpload(file);
  expect(result).toEqual({
    type: "url",
    value: "uploads/ab12_report.pdf",
    metadata: { filename: "report.pdf", note: "Read this with read_text_file at path uploads/ab12_report.pdf if relevant." },
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd frontend && npx vitest run DeskView.test -t "attachment metadata"`
Expected: FAIL — the current `onUpload` only sets `metadata: { filename: file.name }`, no `note`.

- [ ] **Step 3: Implement** — in `frontend/src/desk/DeskView.tsx`, extend the `onUpload` handler:

```tsx
            onUpload: async (file) => {
              const { path } = await uploadToWorkspace(file);
              return {
                type: "url",
                value: path,
                metadata: { filename: file.name, note: `Read this with read_text_file at path ${path} if relevant.` },
              };
            },
```

- [ ] **Step 4: Run, expect PASS**

Run: `cd frontend && npx vitest run DeskView.test`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/desk/DeskView.tsx frontend/src/desk/DeskView.test.tsx
git commit -m "feat(frontend): attachment metadata tells the agent exactly how to read the uploaded file"
```

---

### Task 16: Live pass (one run, end of branch)

**Files:** none changed unless a bug is found (then: fix with a regression test, separate commit).

- [ ] **Step 1: Start the stack** (`COPILOT_ENABLED=true` already set from sub-project 1's local `.env`):

```bash
uv run uvicorn app.api.server:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev
```

- [ ] **Step 2: Playwright-driven browser run** on `http://localhost:5173` (Market Desk is the default mode):
  1. **Portfolio table + chart:** ask "What is the total value of Sarah Levi's portfolio?" (or any real client name from `SELECT name FROM clients LIMIT 1`). Expected: a table with one row per position and a pie chart of weights render in the chat, in addition to the answer text.
  2. **Price chart:** ask "Show me AAPL's price history over the last month." Expected: a line chart renders.
  3. **Ticker info + news:** ask "What's Apple's current price and any recent news?" Expected: a ticker card and a list of headline links render (the specialist may call both tools in one turn or two — either is fine).
  4. **Concentration alert:** ask "Are any clients over 30% concentrated in one stock?" Expected: if any breach exists, an alert card renders; if none, no card and a plain "no clients" answer — not a broken render.
  5. **RAG sources:** ask a question the ingested knowledge base can answer (e.g. about the ingested company's 2024 results). Expected: source cards render, collapsed, expandable.
  6. **Screenshot:** ask the agent to navigate to a URL and take a screenshot. Expected: the image renders inline.
  7. **Suggestions:** confirm the 3 starter suggestion chips appear under an empty chat and clicking one sends it.
  8. **Attachment:** attach a small `.txt` file from the chat's attachment button, then ask "what's in the file I just attached?". Expected: the agent reads it back via `read_text_file` (it now knows the path from the attachment metadata) and answers correctly.
- [ ] **Step 3:** Save screenshots of each rendered display type in the scratchpad and report results in plain words. Check the browser console for errors during all of the above.
- [ ] **Step 4:** Update memory (`project_copilotkit_roadmap.md`: sub-project 2 status) and stop. Do NOT push, do NOT open a PR unless the user asks.
