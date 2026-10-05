# Reports Workspace (chantier 3 of 4) — Design

**Status:** Approved by user, 2026-10-05. Ready for `writing-plans`.

**Roadmap context:** Chantier 1 shipped the 5-section `AppLayout`. Chantier 2 shipped
Clients (list + chat workspace). This spec is chantier 3: the real Reports section,
replacing the `ComingSoonPage` stub at `/reports`. Chantier 4 (Briefing) remains a
stub, not started.

## Goal

Turn `/reports` into a client-scoped portfolio report dashboard: profile header,
P&L totals, sector allocation, concentration alerts, price history for the largest
positions, and the client's history of generated Excel reports with a button to
generate a new one — without going through the chat.

## Why

Today a portfolio report only exists as a side effect of asking the chat agent to
"save/export" it (`save_portfolio_report` tool), and the richer data (sector mix,
concentration, price trends) that the chat's own display components already render
per-tool-call is scattered across the conversation scroll instead of available as
one dashboard. This closes chantier 1's Reports placeholder and gives an advisor a
single place to see a client's full picture and pull a file, instead of hunting
through chat history.

## Decisions (from brainstorming)

1. **Scope:** list + per-client dashboard (same shape as chantier 2's Clients), not
   a flat list of files and not a cross-client comparison view.
2. **Entry point:** `/reports` is its own top-level section with its own client
   picker — independent of `/clients`, not a tab inside the client chat workspace.
3. **Dashboard content**, beyond the pie chart already built for chat: sector
   allocation (bar chart, new), price history for the client's largest positions
   (reuses the chat's `price_chart` display), and concentration alerts (reuses the
   chat's `concentration_alert` display) — plus the existing positions table and
   totals.
4. **No MCP needed.** Everything the dashboard needs already exists as deterministic
   Python (`finance_calc.compute_portfolio_metrics`, `compute_concentration_screen`)
   or an existing direct-call tool (`yfinance_get_price_history`, same pattern
   `concentration_screen`/`client_portfolio` already use to call yfinance outside
   the agent graph).
5. **Backend endpoints live under the existing `/data` prefix**, not a new
   `/reports` router — see "Why not a new router" below. This is a spec-time
   correction from the brainstorming chat (which proposed `app/api/routers/reports.py`
   before the proxy collision was checked).
6. **Generation is a direct deterministic call**, not a chat round-trip: the
   dashboard's "Generate report" button calls a new endpoint that builds the same
   Excel file `save_portfolio_report` builds for the chat tool, but resolves the
   client by `client_id` (unambiguous) instead of the tool's fuzzy name match.

## Why not a new router (`/reports` prefix collision)

`frontend/vite.config.ts` proxies whole path prefixes to the backend (`/data`,
`/copilot`, `/workspace`, etc.) — not specific routes. The SPA route
`/reports/:id` is client-side only (React Router); it is never itself proxied,
*unless* `/reports` is added to the proxy list to reach a new backend router. If it
were added, a hard reload at `/reports/12` would send `GET /reports/12` to the dev
server, the proxy would match the `/reports` prefix and forward it to the backend,
and the backend has no route at exactly `/reports/12` (only, say,
`/reports/clients/12`) — a 404 JSON body instead of the SPA shell. `/data` already
has this latent collision (nothing has hit it because nobody hard-reloads mid-import),
but this chantier does not need to add a second instance of it.

**Resolution:** the new backend endpoints live under `/data/clients/{id}/report` and
`/data/clients/{id}/report/generate` — `/data` is already proxied and already a
safe prefix (it's a real backend router, not a path the SPA also claims below the
collection level the way `/reports/:id` and a would-be `/reports/clients/:id` would).
The frontend route stays `/reports/:id`; it is not and must not be added to the
Vite proxy list.

## Architecture

### Backend (`app/api/routers/data.py` — same file as chantier 1/2's client
endpoints, same deterministic CRUD philosophy, no agent involvement)

**`app/data_import/db.py`**: extend `get_client_with_holdings` to also select each
holding's sector:

```sql
SELECT h.ticker, h.shares, h.avg_cost, co.sector
FROM holdings h
LEFT JOIN companies co ON co.ticker = h.ticker
WHERE h.client_id = ?
```

`LEFT JOIN`, not the inner join `concentration.py`'s `build_holdings_query` uses for
the agent tools — SQLite does not enforce the `holdings.ticker REFERENCES
companies.ticker` foreign key unless `PRAGMA foreign_keys=ON` is set (it isn't,
here), so an inner join would silently drop any holding whose ticker isn't in
`companies`. That would regress chantier 2's existing `/data/clients/{id}/summary`
header totals, which calls this same function. `sector` becomes `None` for such a
holding instead of vanishing. This is additive — `build_client_summary` (chantier
2) ignores the new key, unaffected.

**`app/agent/tools/portfolio_report.py`**: rename `_slugify` to `slugify` (drop the
leading underscore — it's a cross-module utility now, not module-private). Update
its one call site in the same file. No test currently imports it by name.

**New: `GET /data/clients/{client_id}/report`** — 404 if the client doesn't exist.
Otherwise:

1. Load the client + holdings (now sector-joined) via `get_client_with_holdings`.
2. Zero holdings → `{..., totals: None, positions: [], sector_allocation: None,
   concentration: None, price_history: {}, unpriced_tickers: [],
   generated_reports: [...]}` (reports can still exist from a since-sold position;
   list them regardless — see "Report listing" below).
3. Otherwise, fetch a live price per held ticker (`yf_quote_tool.ainvoke`, same
   `asyncio.gather(..., return_exceptions=True)` tolerance chantier 2's
   `build_client_summary` already uses). Build a `Position` per *priced* ticker
   (including its `sector`, possibly `None`); unpriced tickers go into
   `unpriced_tickers` and are excluded from every computation below — same
   degrade-not-fail philosophy as `/data/clients/{id}/summary`.
4. If at least one position is priced: `compute_portfolio_metrics(positions)` for
   `totals`, `positions` (with `sector`), and `sector_allocation` (which is itself
   `None` unless *every included* position has a non-`None` sector — this is
   `compute_portfolio_metrics`'s own existing rule, unchanged).
5. **Concentration is computed over the same priced subset**, via
   `compute_concentration_screen([LabeledPortfolio(label=client.name,
   positions=priced_positions)], threshold_pct=30.0)` — not skipped when some
   tickers are unpriced, for the same reason totals aren't: a partial answer is
   more useful than none. The frontend is responsible for showing
   `unpriced_tickers` next to every computed section so "concentration: no
   breaches" is never read as "fully priced, no breaches" when it might be
   "90% priced, no breaches in that 90%." This applies to `sector_allocation` too.
6. **Price history**: take the top 3 priced positions by `weight_pct`, call
   `yfinance_get_price_history` (`yf_price_history_tool.ainvoke({<ticker_arg>:
   ticker, "period": "3mo"})`, same `symbol`/`ticker` arg-name detection
   `client_portfolio.py` already does) for each, in parallel, tolerating individual
   failures (a ticker whose history fetch fails is just missing from the result
   dict — not an error, not in `unpriced_tickers` either, since its *current*
   price did resolve fine). Result: `price_history: {ticker: [{date, close}, ...]}`
   for whichever of the 3 succeeded.
7. **Report listing**: `generated_reports` lists every file in
   `<WORKSPACE_ROOT>/reports/` whose name starts with the client's
   `f"{slugify(client.name)}-portfolio-brief-"` prefix (not the bare slug — see
   "Report filename semantics" below), sorted newest first by file mtime. Each
   entry: `{filename, generated_at: <mtime, ISO 8601 UTC>, download_url:
   f"/workspace/files/{filename}"}` (the download route already exists, built in
   chantier 2's prep — `app/api/routers/workspace.py`'s `get_report_file`).

Response shape:
```json
{
  "client_id": 12, "name": "...", "email": "...", "segment": "...",
  "risk_profile": "...", "advisor": "...", "city": "...",
  "totals": {"market_value": 0, "cost_basis": 0, "unrealized_pnl": 0, "unrealized_pnl_pct": 0} | null,
  "positions": [{"ticker": "...", "shares": 0, "price": 0, "sector": "..." | null,
                 "market_value": 0, "cost_basis": 0, "unrealized_pnl": 0,
                 "unrealized_pnl_pct": 0, "weight_pct": 0}],
  "sector_allocation": {"Technology": 42.1, ...} | null,
  "concentration": {"threshold_pct": 30.0, "breach_count": 0,
                     "breaches": [{"label": "...", "ticker": "...", "weight_pct": 0,
                                   "market_value": 0}]} | null,
  "price_history": {"AAPL": [{"date": "...", "close": 0.0}, ...]},
  "unpriced_tickers": ["..."],
  "generated_reports": [{"filename": "...", "generated_at": "...", "download_url": "..."}]
}
```

**New: `POST /data/clients/{client_id}/report/generate`**:

1. Gateway guard first, copied from `save_portfolio_report_tool`: if
   `settings.MCP_TRANSPORT.lower() == "gateway"`, return 503 with the same
   explanatory message the chat tool returns (no S3 write path for this yet).
2. 404 if the client doesn't exist.
3. Load holdings (sector not needed here) and fetch live prices, same gather
   pattern. **Unlike the dashboard above, generation fails closed**: any unpriced
   ticker → 502 with `{"detail": "could not price: TICK1, TICK2"}` — a generated
   report is a document someone may rely on; a silently-partial one is worse than
   a clear failure, matching `save_portfolio_report`'s own existing
   fail-closed `ValueError`. Zero holdings → 400
   (`build_portfolio_report_xlsx`'s own `ValueError`, "needs at least one
   position", surfaced as the detail).
4. Resolve the client by `client_id`, not name: build the `portfolio` dict
   `build_portfolio_report_xlsx` expects directly from the id-resolved positions
   (`compute_portfolio_metrics` + `client_name`), instead of calling
   `load_client_portfolio`/`save_portfolio_report` (both name-matching, both would
   raise "matches multiple clients" if this client's name is a substring of
   another's, or resolve the wrong one if two clients share a name — `clients.name`
   has no uniqueness constraint, only `email` does). Then call
   `build_portfolio_report_xlsx(portfolio)` and write the bytes to
   `<WORKSPACE_ROOT>/reports/<slug>-portfolio-brief-<today>.xlsx` exactly as
   `save_portfolio_report` already does.
5. Returns `{"filename": "..."}`.

### Report filename semantics (documented limitations, not fixed this chantier)

- **Same-day regeneration overwrites.** Clicking "Generate report" twice in one day
  replaces the earlier file, not append a second. Acceptable — a report is a
  snapshot, not a history of edits.
- **Prefix matching, not bare-slug matching**, when listing a client's reports:
  `f"{slug}-portfolio-brief-"` as the filter, so a client slugified to
  `john-smith` never picks up a file that happens to belong to `john-smithson`
  (bare-slug `startswith` would).
- **Same-name collision is a known, unfixed limitation.** `clients.name` has no
  uniqueness constraint (only `email` does). Two clients who happen to share a
  full name produce the same slug and therefore the same filename, so one's
  generated report overwrites the other's. Fixing this would mean keying the
  filename by `client_id` instead of slug — but the existing chat tool
  (`save_portfolio_report_tool`) only ever has a `client_name` in scope (the LLM
  never knows a `client_id`), so a filename scheme change would need to touch that
  already-shipped tool too. Out of scope here; flagged for a future chantier if it
  ever bites in practice (unlikely in the current ~25-client seed data).

### Frontend

- **`frontend/src/clients/ClientsList.tsx`**: add an optional `basePath` prop
  (default `"/clients"`), used in place of the hardcoded `/clients/${id}` in the
  row's `navigate(...)` call. Additive, default preserves chantier 2's behavior
  exactly.
- **`frontend/src/reports/ReportsPage.tsx`** (new): same shape as chantier 2's
  `ClientsPage.tsx` — fetches `GET /data/clients`, renders `<ClientsList
  basePath="/reports" />`.
- **`frontend/src/reports/ReportWorkspace.tsx`** (new): reads `:id` from
  `useParams`, fetches `GET /data/clients/:id/report` on mount (and again after a
  successful generate). Renders:
  - Header: name, segment, risk profile, advisor, totals — same layout chantier
    2's `ClientWorkspace` header uses, plus a visible note of `unpriced_tickers`
    when non-empty (reused verbatim from chantier 2's existing "excl. TICK" pattern).
  - `PortfolioPieChart` (`frontend/src/desk/displays/PortfolioPieChart.tsx`),
    given `{ type: "portfolio_chart", slices: positions.map(p => ({ticker: p.ticker,
    weight_pct: p.weight_pct})) }` — a one-line adapter in `ReportWorkspace`, not a
    component change; the component's prop type is a tagged `DisplayPayload`
    member, confirmed by reading `desk/displays/types.ts`.
  - **New `SectorAllocationChart.tsx`** (`frontend/src/reports/` — no existing
    `DisplayPayload` variant covers sector allocation, confirmed by reading
    `types.ts`; this one isn't a reuse). A Recharts horizontal bar chart, one bar
    per sector, same color palette constant (`#34d399, #fbbf24, #f87171, #6b7a8d,
    #1e3a5f, #2563eb`) the other display components already use, for visual
    consistency. Renders nothing (not an empty-state message — just omitted) when
    `sector_allocation` is `null`.
  - `PortfolioTable` (`displays/PortfolioTable.tsx`), given `{ type:
    "portfolio_table", positions, totals }` — the endpoint's `positions` already
    carry every field `PortfolioPosition` needs (`ticker, shares, price, sector,
    market_value, cost_basis, unrealized_pnl, unrealized_pnl_pct, weight_pct`); the
    extra `avg_cost` the endpoint also returns is simply not read by the
    component.
  - `ConcentrationAlert` (`displays/ConcentrationAlert.tsx`), given `{ type:
    "concentration_alert", threshold_pct, breaches }` straight from the
    endpoint's `concentration` field — skipped (rendered not at all) when
    `concentration` is `null` (zero priced positions).
  - `PriceChart` (`displays/PriceChart.tsx`) once per ticker in `price_history`,
    each given `{ type: "price_chart", ticker, points }` — a `.map` over
    `Object.entries(price_history)`, not a single combined chart.
  - Generated reports: one `ReportFileCard` (`displays/ReportFileCard.tsx`,
    unchanged) per entry in `generated_reports`, given `{ type: "report_file",
    filename, url: download_url }`.
  - A "Generate report" button: `POST`s to `/report/generate`, disabled while
    in flight, shows the backend's error detail inline on failure (502/400/503),
    and re-fetches the dashboard on success so the new file appears in the list
    immediately.
  - "Back to list" link to `/reports` (same English copy chantier 2's
    `ClientWorkspace` already uses for `/clients`).
- **`frontend/src/App.tsx`**: replace the `/reports` `ComingSoonPage` route with
  `<ReportsPage />`; add `/reports/:id` → `<ReportWorkspace />`.
- **`frontend/src/lib/api.ts`**: new `ClientReport` type (mirrors the response
  shape above) and `GeneratedReportFile` type; `getClientReport(clientId)` and
  `generateClientReport(clientId): Promise<{filename: string}>`, same
  fetch-throw-on-`!res.ok` convention every other function in this file already
  follows — `generateClientReport` surfaces the response body's `detail` text in
  the thrown `Error` (not just the status code) so the frontend can show the
  backend's specific unpriced/zero-holdings/gateway message.

## Data flow

1. User on `/reports` clicks a client (id 12) → navigates `/reports/12`.
2. `ReportWorkspace` fetches `GET /data/clients/12/report`.
3. Backend loads holdings (now sector-joined), fetches live prices, computes
   totals/sector allocation/concentration over the priced subset, fetches price
   history for the top 3 positions, lists existing report files for this client.
4. Dashboard renders: header, pie chart, sector bar chart, concentration alerts,
   price history, positions table, report file list.
5. User clicks "Generate report" → `POST /data/clients/12/report/generate` →
   backend fails closed on any unpriced ticker or zero holdings, otherwise builds
   and writes the Excel file → frontend re-fetches step 2-4, new file appears.
6. User clicks a report file's Download → browser hits `/workspace/files/<filename>`
   directly (existing route, unchanged).

## Error handling

- `GET /data/clients/{id}/report`: unknown `client_id` → 404. Degrades like
  chantier 2's summary endpoint: never 500s on a priceable-but-partial portfolio.
  Zero holdings → all-empty/null payload, not an error — same "Aucune position" ↔
  English "No position" precedent, just via `totals === null` the frontend already
  knows how to render from chantier 2.
- `POST /data/clients/{id}/report/generate`: unknown `client_id` → 404; gateway
  deployment → 503; zero holdings → 400; any unpriced ticker → 502 with the
  specific tickers named. Frontend shows the `detail` text inline, doesn't
  silently fail or retry.
- Frontend `/reports/:id` with a 404 or non-numeric id → inline error banner with
  a link back to `/reports` — same pattern chantier 2's `ClientWorkspace` uses.

## Testing

**Backend (pytest):**
- `get_client_with_holdings`: holding whose ticker isn't in `companies` → `sector:
  None` for that holding, doesn't drop the row (regression guard for the
  `LEFT JOIN` choice).
- `GET /data/clients/{id}/report`: client with holdings + all prices resolve →
  correct `totals`, `sector_allocation`, `concentration`, `price_history` for the
  top 3 by weight; one ticker's price fetch raising → that ticker in
  `unpriced_tickers`, everything else computed from the rest; zero holdings →
  all-null/empty payload, no crash; unknown id → 404; a client with existing
  report files on disk → `generated_reports` lists them, prefix-matched (add a
  decoy file for a different client whose slug is a prefix of this one's, assert
  it's excluded).
- `POST /data/clients/{id}/report/generate`: happy path → file written to
  `reports_dir`, response names it; one unpriced ticker → 502, no file written;
  zero holdings → 400; `MCP_TRANSPORT=gateway` → 503, no file written; unknown id
  → 404.
- `slugify` (renamed from `_slugify`): existing apostrophe/case tests still pass
  under the new name.

**Frontend (Vitest):**
- `ReportsPage.test.tsx`: list renders, row click navigates to `/reports/:id`
  (not `/clients/:id`) — proves the `basePath` prop actually changes the
  navigation target.
- `ClientsList.test.tsx`: add one case asserting the default (`basePath` omitted)
  still navigates to `/clients/:id` — regression guard for chantier 2.
- `ReportWorkspace.test.tsx`: renders header + all six sections from a mocked
  `getClientReport`; omits the sector chart and concentration alert when their
  fields are `null`; "Generate report" button calls `generateClientReport` and
  re-fetches on success; shows the thrown error's message on failure.
- `App.test.tsx`: routing assertions for `/reports` and `/reports/:id`.

**Live QA (one grounded pass):** open a client with holdings from `/reports`,
confirm every section renders with real numbers; click Generate, confirm the new
file appears in the list and downloads; hard-reload the browser at `/reports/12`
directly (not via in-app navigation) and confirm the SPA still loads — the
specific check for the proxy-collision risk this spec avoided by design; open a
client with zero holdings, confirm the dashboard renders without crashing;
restart the backend first (it runs without `--reload`).

## Out of scope (explicitly, for this chantier)

- PDF/Word export (Excel only, same as today).
- Editing a client's profile from this view.
- A cross-client "all reports" or "all breaches" view.
- Fixing the same-name filename collision or the pre-existing `/data` hard-reload
  proxy collision (documented, not introduced by this chantier).
- Briefing (chantier 4, separate future spec).
