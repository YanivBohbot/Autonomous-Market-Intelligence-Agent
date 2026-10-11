# Briefing (chantier 4 of 4) — Design

**Status:** Approved by user, 2026-10-05. Ready for `writing-plans`.

**Roadmap context:** Last chantier of the nav-layout program. Chantiers 1-3
(nav shell, Clients, Reports) are merged to `master`. This closes the final
`/briefing` placeholder — the only remaining `ComingSoonPage` stub.

## Goal

A market dashboard in the style of Google Finance's home panel (major index
cards, sector performance, a written macro/micro market summary, recent
news) plus a cabinet-wide concentration-risk scan across every client — the
two things the original nav-shell stub's placeholder text already named
("concentration alerts, notable market moves, agent synthesis"), reframed
with the market panel the user asked for after seeing Google Finance.

## Why

Closes the nav-layout program's last placeholder. Gives an advisor one page
that answers "what's happening in the market today" and "which of my
clients need attention today" without opening the chat or clicking through
every client's report.

## Decisions (from brainstorming)

1. **Scope: both market-wide and client-wide**, not either alone. A market
   panel (indices, sectors, narrative, news) plus a "Client alerts" section
   (concentration breaches across every client, cabinet-wide). Confirmed by
   the user over the original stub-text-only framing.
2. **No new backend router.** Same lesson as the Reports spec: a new
   `/briefing` backend prefix next to the `/briefing` SPA route would risk
   the same Vite dev-proxy collision avoided there. The new endpoint lives
   on the existing `/data` router, as `GET /data/briefing`.
3. **`yfinance_get_top` (the dedicated "top sector ETFs/companies" MCP
   tool) is broken, confirmed by direct testing** — 15/15 calls across 5
   sectors × 3 `top_type` values all failed with the same root cause:
   Yahoo's own `sector.py`/`industry.py` scraping endpoint returns HTTP 404.
   This is broken in the underlying `yfinance` library's data source, not a
   parameter or retry problem — not worth building on, now or later unless
   that upstream endpoint comes back. **Sector performance instead uses the
   same already-proven `yf_quote_tool` on each sector's SPDR Select Sector
   ETF ticker** (the standard Google-Finance-equivalent proxy): Technology
   (XLK), Financial Services (XLF), Healthcare (XLV), Energy (XLE), Consumer
   Cyclical (XLY), Consumer Defensive (XLP), Industrials (XLI), Communication
   Services (XLC) — 8 of the 11 GICS sectors for v1 (Real Estate, Materials,
   Utilities dropped to bound the page's cold-load call count; adding them
   later is a one-line list change).
4. **Indices: 4 for v1** — S&P 500 (`^GSPC`), Dow Jones (`^DJI`), Nasdaq
   (`^IXIC`), VIX (`^VIX`). Russell 2000 dropped for v1 (same reasoning:
   bound the call count; trivial to add later).
5. **No per-index sparklines in v1.** Each index/sector card shows price +
   % change only, not a mini price-history chart — a sparkline would add 4
   more yfinance history calls on top of the already-heavy 12 quote calls
   this page makes. Revisit once the page's load time is proven acceptable
   live.
6. **A 10-minute cache TTL** for `_live_price` lookups made from this page
   (vs. the Reports/Clients pages' 30s) — the user confirmed a daily-summary
   page doesn't need near-real-time freshness. Implemented by extending the
   existing cache mechanism (`app/api/routers/data.py`'s `_price_cache`) to
   accept a longer TTL for this call site, not a second cache.
7. **The narrative section is explicitly "Résumé du marché macro-économique
   et micro-économique"** (the user's own wording, not a generic "market
   summary") — one LLM-written analysis covering both: macro movement
   (index levels, VIX as a fear-gauge signal) and micro movement (which
   sectors moved and by how much), grounded only in the indices/sectors
   data this endpoint already computed. Same lightweight direct-`ChatOpenAI`
   pattern as `portfolio_narrative.py` (chantier 3) and the supervisor's own
   `_router` — no tool-calling loop, no agent graph.
8. **News via Tavily directly, not the `web_search` agent tool.**
   `web_search_tool` (`app/agent/tools/knowledge_base.py`) collapses its
   results into one joined string (`"[SOURCE WEB: {url}] {content}\n\n..."`)
   built for an LLM to read, not structured `{title, url}` entries a
   frontend can render as a list — reusing it would mean re-parsing that
   string back apart. Call the same underlying `TavilyClient.search(query=
   ..., max_results=3, search_depth="advanced")` directly (deferred import,
   same convention as every yfinance call in `data.py`) and read `results[
   ].{title, url}` straight from Tavily's own response, with a fixed
   market-wide query (not a per-ticker one — this is a market page).
9. **Client alerts degrade per-ticker, not via a try/except around a
   fail-closed call.** `app/agent/tools/concentration.py`'s `screen_clients`
   is the wrong thing to call here even though it already does "scan every
   client" — its `run_sql` is wired to the MCP CRM tool
   (`app.agent.tools.mcp_clients.mcp_client.crm_tool`, a stdio subprocess
   call), and `data.py`'s own module docstring is explicit that this router
   deliberately bypasses that MCP indirection everywhere else in favor of a
   direct `sqlite3.connect(DB_PATH)` connection (same one `get_client_with_
   holdings` and every other `data.py` query already uses). Introducing an
   MCP CRM call into `data.py` for this one endpoint would be a new
   dependency type nothing else in the file has, for no benefit — the data
   is already reachable locally. It also fails closed (raises if *any*
   ticker across *any* client is unpriced), which is correct for the chat
   tool but wrong for a dashboard section.

   Instead: query every client's holdings-with-sector directly over the
   local `sqlite3` connection, reusing `build_holdings_query(risk_profile=
   None, client_names=None)` from `concentration.py` for the SQL text only
   (it's a pure string builder, no MCP involved) executed via `conn.execute
   (...)`. Fetch a live price per *distinct* ticker across the whole
   cabinet (`asyncio.gather(..., return_exceptions=True)`, same tolerate-
   failures pattern Reports' `GET .../report` already uses) — a ticker that
   fails to price is excluded from that one holding's position, not from
   the whole scan, same per-item degrade philosophy as everywhere else in
   this router. Build one `LabeledPortfolio` per client from whatever
   priced, then call `compute_concentration_screen` (the pure function,
   already imported in `data.py` since chantier 3) directly. `client_alerts.
   available` is `true` unless the DB query itself fails or zero clients
   have any priced holding at all — not flipped by one bad ticker among
   however many the whole cabinet holds.
10. **A fixed 6-ticker watchlist** (AAPL, NVDA, MSFT, GOOGL, AMZN, META) —
    same `yf_quote_tool` call as the index cards, added after the user
    asked to also see individual big-name stocks, not just indices and
    sectors. Fixed list, not derived from client holdings (a dynamic
    "most-held tickers across all clients" version was considered and
    explicitly deferred — more logic for a v1 that's already managing its
    call count). Brings the page's total yfinance quote calls from 12 to
    18; extending or swapping the list later is a one-line change.
    **Unlike the index/sector cards, each watchlist card also gets a
    sparkline** (90-day price history, same `yfinance_get_price_history`
    call and `_price_history`/markdown-table-parsing path chantier 3 built
    for Reports) — the one exception to Decision 5's no-sparkline rule,
    scoped to the watchlist specifically because the user asked for it
    there. Adds 6 more yfinance calls (24 total for the page). Rendered via
    a new compact variant: `PriceChart`'s existing chart (chantier 3,
    `frontend/src/desk/displays/PriceChart.tsx`) is sized for a full-width
    card with an axis and tooltip; the watchlist needs a small inline
    sparkline with no axis/labels inside a price card. Rather than
    overloading `PriceChart` with a size-variant prop, this is a new
    `frontend/src/briefing/Sparkline.tsx` (just a `Line` inside a
    `ResponsiveContainer`, no `XAxis`/`YAxis`/`Tooltip`) — small, focused,
    reuses the same `points: {date, close}[]` shape the backend already
    produces for price history, no new backend logic.
11. **No earnings-calendar section in v1.** Investigated: no market-wide
    earnings calendar tool exists in the yfinance MCP server's 9 tools.
    Per-stock earnings dates do exist (`yfinance_get_ticker_info`'s
    `earningsTimestampStart` field, confirmed present and populated on a
    real quote). A real "upcoming earnings" section would need to be scoped
    to tickers clients actually hold (resolved via the same
    `known_tickers`-style query already in `app/data_import/db.py`) and
    adds another N yfinance calls on top of an already 12-call page. Cut
    from v1 to keep the page's load time bounded; flagged as a natural
    follow-up once this page's real-world load time is known.

## Architecture

### Backend

- **`app/agent/tools/market_narrative.py`** (new, parallel to chantier 3's
  `portfolio_narrative.py`, not a shared/generalized module — keeps each
  file focused on one grounding shape): `generate_market_narrative(market:
  dict) -> str`, a direct `ChatOpenAI` call. `market` carries `indices`
  (list of `{name, price, change_pct}`) and `sectors` (list of `{name,
  change_pct}`) — the same numbers the endpoint already computed, nothing
  the LLM has to (or is allowed to) recompute. System prompt asks for 2-3
  short paragraphs covering both macro (index levels, VIX) and micro
  (sector dispersion) movement — this is the "macro-économique et
  micro-économique" framing the user asked for by name.
- **`app/api/routers/data.py`**: extend `_live_price` (or add a sibling
  `_live_price_long_ttl`, decided at plan time by whichever keeps the
  single-responsibility of the existing cache clean) so Briefing's calls
  use a 600s TTL instead of the existing 30s. New `GET /data/briefing`:
  1. Fetch all 4 index quotes + 8 sector-ETF quotes + 6 watchlist-ticker
     quotes (`AAPL`, `NVDA`, `MSFT`, `GOOGL`, `AMZN`, `META`) in parallel
     (`asyncio.gather`, tolerate individual failures the same way Reports'
     `GET .../report` already tolerates an unpriced ticker — a failed
     index/sector/watchlist entry is omitted from its list, not a 500).
  2. For whichever watchlist tickers priced successfully, concurrently
     fetch each one's 90-day price history (`_price_history`, same
     function chantier 3 built — reused as-is, not duplicated), tolerating
     individual failures the same way Reports already does: a ticker with
     no history just renders without a sparkline, not an error.
  3. Build `market = {"indices": [...], "sectors": [...]}` from whatever
     resolved (`watchlist` is separate — see the response shape below —
     since the narrative is grounded only in indices/sectors, not
     individual-stock moves).
  4. Concurrently (same `asyncio.gather`-two-things pattern chantier 3 used
     for price-history + narrative): call `generate_market_narrative
     (market)` and fetch news via a direct `TavilyClient.search(...)` call
     (deferred import, same convention as every yfinance call here).
  5. Separately: query every client's holdings-with-sector via `conn.execute
     (build_holdings_query(risk_profile=None, client_names=None))` over the
     router's own local `sqlite3` connection (not the MCP CRM tool — see
     Decision 9), fetch a live price per distinct ticker across the whole
     cabinet tolerating individual failures, build one `LabeledPortfolio`
     per client from whatever priced, call `compute_concentration_screen`
     directly. `client_alerts.available` is `false` only if the query
     itself fails or zero clients have any priced holding.
  6. Response: `{"indices": [...], "sectors": [...], "watchlist": [...],
     "narrative": str, "news": [{"title", "url"}...], "client_alerts":
     {"available": bool, "threshold_pct": 30.0, "breaches": [...]}}` —
     `indices`/`sectors` share `{"symbol", "name", "price", "change_pct"}`;
     each `watchlist` entry adds a `points: {date, close}[]` field (its
     sparkline data, `[]` when the history fetch failed for that ticker).

### Frontend

- **`frontend/src/briefing/BriefingPage.tsx`** (new, replaces the
  `ComingSoonPage` route): fetches `GET /data/briefing` on mount. Renders,
  top to bottom: index cards row (name, price, %, colored same as existing
  P&L conventions — green/red via `text-terminal-accent`/`text-terminal-
  danger`), a watchlist cards row (same price+% card as the index row, for
  the 6 fixed megacap tickers, plus a `Sparkline` under each card's price
  when that ticker's `points` is non-empty), sector performance list (same shape as `SectorAllocationChart`'s
  own HTML-legend pattern from chantier 3 — plain rows with a colored dot,
  name, %, not a new chart type, since this is a flat ranked list rather
  than a portfolio-weight breakdown), the "Résumé du marché macro-économique
  et micro-économique" narrative block (same `whitespace-pre-line` card
  chantier 3's Reports narrative uses), a news list, then "Client alerts" at
  the bottom reusing `ConcentrationAlert` as-is (it already supports
  multiple clients' breaches via each breach's own `label` field) — or an
  "Alerts unavailable" note when `client_alerts.available` is `false`.
- **`frontend/src/App.tsx`**: replace the `/briefing` `ComingSoonPage`
  route with `<BriefingPage />`.
- **`frontend/src/lib/api.ts`**: new `BriefingData` type + `getBriefing()`.

## Data flow

1. Advisor opens `/briefing`.
2. `BriefingPage` fetches `GET /data/briefing`.
3. Backend fetches 18 quotes (4 indices + 8 sector ETFs + 6 watchlist
   tickers) in parallel, then 6 more price-history calls for the watchlist
   tickers that priced successfully (24 yfinance calls total on a cold
   load),
   tolerating individual failures; concurrently generates the narrative
   (grounded on whatever quotes resolved) and fetches news; separately
   screens every client for concentration breaches, degrading to
   "unavailable" rather than failing the whole response on a bad ticker.
4. Page renders every section independently — a missing index, a failed
   news fetch, or an unavailable alerts section each show their own
   fallback, never block the rest of the page.
5. Repeat visits within 10 minutes hit the price cache — fast. A cold
   visit (or one after the cache expired) pays yfinance's own latency once
   per ticker, in parallel, same as Reports.

## Error handling

- Any of the 18 index/sector/watchlist quote fetches failing → that one
  entry is omitted from its list (`indices`/`sectors`/`watchlist`), never a
  500 for the whole page. If *every* index fails, `indices: []`; same for
  sectors and the watchlist — the frontend shows an empty-state note for
  that section, not a crash.
- `generate_market_narrative`: if `indices` and `sectors` are both empty,
  skip the LLM call and return a fixed "Market data unavailable right now."
  string (same no-call-on-empty-input rule `portfolio_narrative.py`
  already follows).
- The Tavily search call raising → `news: []`, frontend shows "No news
  available." rather than erroring the page.
- A ticker failing to price in the cabinet-wide scan → that one holding is
  excluded from its client's position list, same as every other per-ticker
  degrade in this router — never flips `client_alerts.available`. Only the
  holdings query itself failing, or zero clients having any priced
  holding, sets `client_alerts: {"available": false, ...}`; frontend shows
  an inline note, not an error banner — the rest of the page still renders.
- Frontend `/briefing` itself has no error-prone params (no `:id`), so
  there is no 404/invalid-id case to handle, unlike Clients/Reports.

## Testing

**Backend (pytest):**
- `generate_market_narrative`: grounds the prompt in given indices/sectors
  (assert the prompt text contains the given numbers, same technique
  chantier 3's `test_generate_portfolio_narrative_grounds_the_prompt_in_
  computed_numbers` uses); skips the LLM call and returns the fixed string
  when both `indices` and `sectors` are empty.
- `GET /data/briefing`: happy path with all 18 quotes + 6 history fetches
  mocked → correct `indices`/`sectors`/`watchlist` (each with non-empty
  `points`)/`narrative`/`news`/`client_alerts`; one index quote failing →
  that index omitted, rest present; one watchlist ticker's history fetch
  failing → that ticker's `points: []`, the rest of its quote data still
  present; all quotes failing → empty lists, narrative is the fixed
  unavailable string, no 500; one client's ticker failing to price in the
  cabinet scan → that holding excluded, rest of `client_alerts` still
  computed from the others (`available` stays `true`); the holdings query
  itself raising → `client_alerts.available == False`; the Tavily call
  raising → `news == []`, rest of the response still present.
- The 10-minute TTL: a test proving Briefing's price lookups use the longer
  TTL constant, not Reports/Clients' 30s one (whatever mechanism the plan
  picks — sibling function or a parameter — must be directly testable, not
  inferred from timing).

**Frontend (Vitest):**
- `BriefingPage.test.tsx`: renders all sections from a mocked `getBriefing`;
  omits/shows-fallback for each section when its field is empty/unavailable;
  `ConcentrationAlert` receives the cabinet-wide breaches correctly shaped.
- `Sparkline.test.tsx`: renders a line for a non-empty `points` array;
  renders nothing (or an empty-state, decided at plan time) for an empty
  one — same pattern `SectorAllocationChart.test.tsx` (chantier 3) already
  uses for its own null-input case.
- `App.test.tsx`: routing assertion for `/briefing` now renders
  `BriefingPage`, not `ComingSoonPage` (the Briefing-specific case in the
  existing "one not-yet-built section" test moves out, since after this
  chantier there are zero stub sections left).

**Live QA (one grounded pass, in actual Chrome — chantier 3 showed jsdom
misses real rendering bugs):** load `/briefing` cold, time it and confirm
every section renders something (even degraded) within a reasonable wait;
reload within 10 minutes and confirm it's fast (cache hit); confirm the
narrative text actually reads as macro+micro analysis, not a restated list
of numbers; confirm the client-alerts section matches what
`concentration_screen` already reports for the same cabinet via chat — that
logic is already unit-tested, this pass is about the visual integration,
not re-proving the math.

## Out of scope (explicitly, for this chantier)

- Earnings calendar (no reliable data source found — see Decision 11).
- Index/sector sparklines (Decision 5 — revisit after real load-time data).
- Auto-refresh/polling while the page is open (manual reload only for v1).
- An embedded chat panel on this page (Google Finance's own screenshot has
  one on the right, but this app already has a dedicated Research section
  for that — duplicating chat UI here would be redundant with the existing
  5-section nav).
- Russell 2000 and the remaining 3 GICS sectors (Real Estate, Materials,
  Utilities) — trivial list additions once v1's load time is proven
  acceptable.
