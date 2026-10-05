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
8. **News via the existing `web_search` (Tavily) tool**, called directly
   (same deferred-import, direct-call pattern as every other yfinance call
   in `data.py`) with a fixed market-wide query, not a per-ticker query —
   this is a market page, not a single-stock page.
9. **Client alerts degrade, they don't fail closed.** `app/agent/tools/
   concentration.py`'s `screen_clients` (already built, already scans every
   client when `client_names=None`) raises `ValueError` if *any* ticker
   across *any* client fails to price — correct for the chat tool (an
   agent answer must never silently drop a client), wrong for a dashboard
   section (one bad ticker must not blank the whole Briefing page). The
   endpoint catches that `ValueError` and reports the alerts section as
   unavailable instead of 500ing the whole response — same "a view degrades,
   a tool fails closed" split the Reports spec already established between
   its GET and POST endpoints.
10. **No earnings-calendar section in v1.** Investigated: no market-wide
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
  1. Fetch all 4 index quotes + 8 sector-ETF quotes in parallel
     (`asyncio.gather`, tolerate individual failures the same way Reports'
     `GET .../report` already tolerates an unpriced ticker — a failed
     index/sector is omitted from its list, not a 500).
  2. Build `market = {"indices": [...], "sectors": [...]}` from whatever
     resolved.
  3. Concurrently (same `asyncio.gather`-two-things pattern chantier 3 used
     for price-history + narrative): call `generate_market_narrative
     (market)` and fetch news via `web_search` directly.
  4. Separately, call `screen_clients(run_sql=..., get_price=_live_price,
     client_names=None, threshold_pct=30.0)` (the 10-minute-TTL price
     cache applies here too, so this mostly reuses prices the market
     section's own calls — or a prior Reports/Clients visit — already
     warmed) inside a `try/except ValueError`; on failure, the alerts
     section reports `{"available": False}` instead of raising.
  5. Response: `{"indices": [...], "sectors": [...], "narrative": str,
     "news": [{"title", "url", "source"}...], "client_alerts":
     {"available": bool, "threshold_pct": 30.0, "breaches": [...]}}`.

### Frontend

- **`frontend/src/briefing/BriefingPage.tsx`** (new, replaces the
  `ComingSoonPage` route): fetches `GET /data/briefing` on mount. Renders,
  top to bottom: index cards row (name, price, %, colored same as existing
  P&L conventions — green/red via `text-terminal-accent`/`text-terminal-
  danger`), sector performance list (same shape as `SectorAllocationChart`'s
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
3. Backend fetches 12 quotes (4 indices + 8 sector ETFs) in parallel,
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

- Any of the 12 index/sector quote fetches failing → that one entry is
  omitted from its list (`indices`/`sectors`), never a 500 for the whole
  page. If *every* index fails, `indices: []`; same for sectors — the
  frontend shows an empty-state note for that section, not a crash.
- `generate_market_narrative`: if `indices` and `sectors` are both empty,
  skip the LLM call and return a fixed "Market data unavailable right now."
  string (same no-call-on-empty-input rule `portfolio_narrative.py`
  already follows).
- `web_search` failing → `news: []`, frontend shows "No news available."
  rather than erroring the page.
- `screen_clients` raising (any client's ticker unpriced) → `client_alerts:
  {"available": false, ...}`, frontend shows an inline note, not an error
  banner — the rest of the page still renders.
- Frontend `/briefing` itself has no error-prone params (no `:id`), so
  there is no 404/invalid-id case to handle, unlike Clients/Reports.

## Testing

**Backend (pytest):**
- `generate_market_narrative`: grounds the prompt in given indices/sectors
  (assert the prompt text contains the given numbers, same technique
  chantier 3's `test_generate_portfolio_narrative_grounds_the_prompt_in_
  computed_numbers` uses); skips the LLM call and returns the fixed string
  when both `indices` and `sectors` are empty.
- `GET /data/briefing`: happy path with all 12 quotes mocked → correct
  `indices`/`sectors`/`narrative`/`news`/`client_alerts`; one index quote
  failing → that index omitted, rest present; all quotes failing → empty
  lists, narrative is the fixed unavailable string, no 500; `screen_clients`
  raising (monkeypatch it to raise `ValueError`) → `client_alerts.available
  == False`, rest of the response still present; `web_search` raising →
  `news == []`, rest of the response still present.
- The 10-minute TTL: a test proving Briefing's price lookups use the longer
  TTL constant, not Reports/Clients' 30s one (whatever mechanism the plan
  picks — sibling function or a parameter — must be directly testable, not
  inferred from timing).

**Frontend (Vitest):**
- `BriefingPage.test.tsx`: renders all sections from a mocked `getBriefing`;
  omits/shows-fallback for each section when its field is empty/unavailable;
  `ConcentrationAlert` receives the cabinet-wide breaches correctly shaped.
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

- Earnings calendar (no reliable data source found — see Decision 10).
- Index/sector sparklines (Decision 5 — revisit after real load-time data).
- Auto-refresh/polling while the page is open (manual reload only for v1).
- An embedded chat panel on this page (Google Finance's own screenshot has
  one on the right, but this app already has a dedicated Research section
  for that — duplicating chat UI here would be redundant with the existing
  5-section nav).
- Russell 2000 and the remaining 3 GICS sectors (Real Estate, Materials,
  Utilities) — trivial list additions once v1's load time is proven
  acceptable.
