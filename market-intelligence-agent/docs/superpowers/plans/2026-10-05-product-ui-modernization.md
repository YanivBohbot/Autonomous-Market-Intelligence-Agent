# Multi-Agent Finance Desk UI Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modernize the entire React product around the approved Briefing visual language, add the Multi-Agent Finance Desk shell and global ticker, and preserve all existing client, report, import, chat, approval, and agent behavior.

**Architecture:** Build presentation-only primitives first, then add an independently cached market-ticker endpoint and a shell that owns only global UI state. Feature pages retain their existing data ownership and progressive loading boundaries; CopilotKit and AG-UI integrations remain intact while their presentation is upgraded.

**Tech Stack:** React 19, TypeScript 5.5, React Router 7, Tailwind CSS 3.4, CopilotKit 1.74 v2 UI, Vitest/Testing Library, FastAPI, Python 3.12, pytest, yfinance.

**Spec:** `docs/superpowers/specs/2026-10-05-product-ui-modernization-design.md`

## Global Constraints

- Preserve the current uncommitted Briefing implementation. Do not reset, stash, overwrite, or re-create it; integrate it only in Task 12.
- Keep `/classic` functional and absent from primary navigation.
- Do not change LangGraph routing, AG-UI event transport, approval semantics, CopilotKit provider/agent/thread boundaries, or backend report/import contracts.
- Shared components in `frontend/src/ui/` are presentation-only and never fetch data.
- Sans-serif is the default. Use monospace only for symbols, timestamps, session IDs, token counts, and raw technical values.
- Loading and failure are local to each surface. Background refreshes retain the last successful data.
- Use TDD for every behavior change: add a failing assertion, observe the expected failure, implement the smallest change, then rerun the focused suite.
- Follow Context7's current CopilotKit guidance: keep the v2 entrypoint and stylesheet, retain explicit `threadId`, use `useConfigureSuggestions`, and customize through supported `className`, `input`, and configuration props.
- After every completed product-code task (Tasks 0-12), restart both backend and frontend with the Per-Task Runtime Protocol below so the user can test the current increment immediately.

## File Structure Map

```text
app/api/routers/data.py                         # market ticker endpoint/cache
tests/unit/test_data_endpoints.py               # endpoint/cache/provider tests
frontend/src/lib/api.ts                         # MarketTickerItem + fetch function
frontend/src/lib/api.test.ts                    # frontend API contract
frontend/src/ui/                                # new shared visual primitives
frontend/src/layout/AppLayout.tsx               # brand, nav, global state, responsive rails
frontend/src/layout/GlobalMarketTicker.tsx      # independent polling surface
frontend/src/layout/ProfilePreview.tsx          # non-persistent settings preview
frontend/src/layout/ResponsiveRail.tsx          # accessible mobile/desktop rail
frontend/src/desk/activity.ts                   # reducer + pure run grouping
frontend/src/desk/DeskActivityRail.tsx          # timeline renderer
frontend/src/clients/                           # client overview/workspace migration
frontend/src/reports/                           # report overview/workspace migration
frontend/src/data/                              # library/import migration
frontend/src/desk/DeskView.tsx                  # Research identity and supported chat styling
frontend/src/briefing/BriefingPage.tsx          # equivalent shared primitives only
frontend/src/index.css                          # semantic tokens, ticker/chat motion/styles
frontend/tailwind.config.ts                     # shared animations/token aliases
```

## Review Focus

1. **No behavior regression in agent workflows.** Pinned to Tasks 6, 8, and 11 regression tests.
2. **No return of whole-page loading for independent data.** Pinned to Tasks 3, 5, 7, 9, 10, and 12 tests.
3. **Ticker resilience and request deduplication.** Pinned to Tasks 2 and 3 cache/failure tests.
4. **Accessible drawers, profile panel, drag/drop, and reduced motion.** Pinned to Tasks 3, 4, 5, and 10 interaction tests.
5. **Existing Briefing performance architecture remains intact.** Pinned to Task 12 and the final full-suite gate.

## Per-Task Runtime Protocol

After the task's focused tests and commit, inspect listeners on ports 8000 and 5173. Stop a listener only when its `Win32_Process.CommandLine` contains this repository path and the expected `uvicorn` or `vite` command; abort instead of stopping an unrelated process. Then launch both services in hidden windows:

```powershell
$projectRoot = "F:\langchain-langgraph-mcp\market-agent\market-intelligence-agent"
$frontendRoot = Join-Path $projectRoot "frontend"
Start-Process -FilePath "uv" -ArgumentList "run","uvicorn","app.api.server:app","--host","0.0.0.0","--port","8000","--reload" -WorkingDirectory $projectRoot -WindowStyle Hidden
Start-Process -FilePath "npm.cmd" -ArgumentList "run","dev","--","--host","0.0.0.0","--port","5173" -WorkingDirectory $frontendRoot -WindowStyle Hidden
```

Poll for at most 30 seconds, then require `GET http://127.0.0.1:8000/health` to return 200 and `GET http://127.0.0.1:5173/` to return 200. After Task 2, also require `GET http://127.0.0.1:8000/data/market-ticker` to return a JSON `items` array. Report the running URLs after each task.

---

### Task 0: Preserve and checkpoint the existing Briefing baseline

**Files:**

- Verify and commit: `app/api/routers/data.py`
- Verify and commit: `tests/unit/test_data_endpoints.py`
- Verify and commit: `frontend/src/lib/api.ts`
- Verify and commit: `frontend/src/briefing/`

- [ ] **Step 1: Review the existing dirty diff before changing it.** Confirm every hunk belongs to the componentized Briefing already approved in the preceding feature and that no unrelated user change is included.

```powershell
git status --short
git diff -- app/api/routers/data.py tests/unit/test_data_endpoints.py frontend/src/lib/api.ts frontend/src/briefing
```

- [ ] **Step 2: Run the existing focused regression gates.**

```powershell
uv run pytest tests/unit/test_data_endpoints.py -v
Set-Location frontend
npm test -- src/briefing src/lib/api.test.ts
npm run build
Set-Location ..
```

Expected: the current Briefing endpoint/component tests and production build pass before modernization starts. If a test fails, fix only the current Briefing behavior and rerun this same gate.

- [ ] **Step 3: Commit the verified baseline as one isolated checkpoint.**

```powershell
git add app/api/routers/data.py tests/unit/test_data_endpoints.py frontend/src/lib/api.ts frontend/src/briefing
git commit -m "feat(briefing): build componentized global dashboard"
```

This checkpoint prevents later ticker or shared-primitive commits from accidentally mixing with the user's existing Briefing work.

### Task 1: Create the shared visual primitives and semantic tokens

**Files:**

- Create: `frontend/src/ui/Icon.tsx`
- Create: `frontend/src/ui/PageHeader.tsx`
- Create: `frontend/src/ui/SurfaceCard.tsx`
- Create: `frontend/src/ui/SectionHeader.tsx`
- Create: `frontend/src/ui/MetricCard.tsx`
- Create: `frontend/src/ui/StatusBadge.tsx`
- Create: `frontend/src/ui/FeedbackStates.tsx`
- Create: `frontend/src/ui/ui.test.tsx`
- Modify: `frontend/src/index.css`
- Modify: `frontend/tailwind.config.ts`

- [ ] **Step 1: Write failing primitive contract tests.**

```tsx
render(<PageHeader eyebrow="Client intelligence" title="Clients" description="Monitor every relationship." />);
expect(screen.getByRole("heading", { name: "Clients" })).toBeInTheDocument();

render(<StatusBadge tone="success">Operational</StatusBadge>);
expect(screen.getByText("Operational")).toHaveAttribute("data-tone", "success");

render(<ErrorState title="Clients unavailable" actionLabel="Retry" onAction={retry} />);
await user.click(screen.getByRole("button", { name: "Retry" }));
expect(retry).toHaveBeenCalledOnce();
```

- [ ] **Step 2: Run `cd frontend; npm test -- src/ui/ui.test.tsx`.** Expect failure because the modules do not exist.
- [ ] **Step 3: Implement these exact public contracts.**

```tsx
export type SurfaceTone = "default" | "soft" | "gradient";
export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";
export type IconName = "briefing" | "clients" | "research" | "reports" | "data" | "menu" | "activity" | "profile" | "theme" | "settings" | "close" | "document" | "upload" | "check" | "warning";

export function PageHeader(props: {
  eyebrow?: string; title: string; description?: string;
  actions?: React.ReactNode; children?: React.ReactNode;
}): React.ReactElement;
export function SurfaceCard(props: React.PropsWithChildren<{ className?: string; tone?: SurfaceTone; padding?: "none" | "sm" | "md" | "lg" }>): React.ReactElement;
export function SectionHeader(props: { title: string; description?: string; action?: React.ReactNode }): React.ReactElement;
export function MetricCard(props: { label: string; value: React.ReactNode; detail?: string; tone?: StatusTone }): React.ReactElement;
export function StatusBadge(props: React.PropsWithChildren<{ tone?: StatusTone }>): React.ReactElement;
export function Skeleton(props: { className?: string; label?: string }): React.ReactElement;
export function EmptyState(props: { title: string; description?: string; icon?: IconName }): React.ReactElement;
export function ErrorState(props: { title: string; description?: string; actionLabel?: string; onAction?: () => void }): React.ReactElement;
```

Use `rounded-2xl border border-terminal-border bg-terminal-panel card-shadow`, a `focus-visible:ring-2 focus-visible:ring-blue-500` control treatment, and new `--brand-blue`, `--surface-elevated`, and `--surface-soft` variables in both themes. Remove the `.scan-lines` rule and add a global `@media (prefers-reduced-motion: reduce)` rule that disables non-essential animations.

- [ ] **Step 4: Rerun the focused test and `npm run build`.** Expect both to pass.
- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/ui frontend/src/index.css frontend/tailwind.config.ts
git commit -m "feat(ui): add shared finance desk primitives"
```

### Task 2: Add the resilient global market ticker backend

**Files:**

- Modify: `app/api/routers/data.py`
- Modify: `tests/unit/test_data_endpoints.py`

- [ ] **Step 1: Add failing tests for ordering, cache reuse, partial data, provider failure, and malformed rows.**

```python
def test_market_ticker_returns_the_world_instrument_set(client, monkeypatch):
    async def fake_ticker():
        return [_fake_quote(symbol, name=name) for name, symbol in data_router_module._MARKET_TICKER_SPECS]
    monkeypatch.setattr(data_router_module, "_cached_market_ticker", fake_ticker)
    response = client.get("/data/market-ticker")
    assert response.status_code == 200
    assert [item["symbol"] for item in response.json()["items"]] == [symbol for _, symbol in data_router_module._MARKET_TICKER_SPECS]

def test_cached_market_ticker_uses_one_download_for_two_callers(monkeypatch):
    data_router_module._market_ticker_cache = None
    data_router_module._market_ticker_inflight = None
    calls = []

    def fake_download(specs):
        calls.append(specs)
        return [
            {**_fake_quote(symbol, name=name), "points": []}
            for name, symbol in specs
        ]

    monkeypatch.setattr(data_router_module, "_download_briefing_batch", fake_download)
    first = asyncio.run(data_router_module._cached_market_ticker())
    second = asyncio.run(data_router_module._cached_market_ticker())
    assert calls == [data_router_module._MARKET_TICKER_SPECS]
    assert first == second
```

Add separate tests where the downloader returns one valid row plus one malformed row, raises an exception, and returns only eight symbols; the endpoint must return valid rows in configured order and never 500.

- [ ] **Step 2: Run `uv run pytest tests/unit/test_data_endpoints.py -k market_ticker -v`.** Expect missing symbol/function/route failures.
- [ ] **Step 3: Implement a cache isolated from Briefing.**

```python
_MARKET_TICKER_SPECS = [
    ("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Dow Jones", "^DJI"),
    ("DAX", "^GDAXI"), ("Nikkei 225", "^N225"), ("Bitcoin", "BTC-USD"),
    ("EUR/USD", "EURUSD=X"), ("Gold", "GC=F"), ("Crude Oil", "CL=F"),
]
_MARKET_TICKER_CACHE_TTL_S = 60.0
_market_ticker_cache: tuple[list[dict], float] | None = None
_market_ticker_inflight: asyncio.Task | None = None
```

`_cached_market_ticker()` must call `_download_briefing_batch(_MARKET_TICKER_SPECS)` once through `asyncio.to_thread`, strip `points` and `volume`, validate `symbol/name` as strings and `price/change_pct` as finite numbers, retain configured order, cache even an empty result for 60 seconds, and clear the matching in-flight task in `finally`.

```python
@router.get("/market-ticker")
async def get_market_ticker() -> dict:
    return {"items": await _cached_market_ticker()}
```

- [ ] **Step 4: Run the focused tests, then `uv run pytest tests/unit/test_data_endpoints.py -v`.** Expect all tests to pass.
- [ ] **Step 5: Commit.**

```powershell
git add app/api/routers/data.py tests/unit/test_data_endpoints.py
git commit -m "feat(data): add cached global market ticker"
```

### Task 3: Build the independent frontend ticker data surface

**Files:**

- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/api.test.ts`
- Create: `frontend/src/layout/GlobalMarketTicker.tsx`
- Create: `frontend/src/layout/GlobalMarketTicker.test.tsx`
- Modify: `frontend/src/index.css`
- Modify: `frontend/tailwind.config.ts`

- [ ] **Step 1: Add failing API and component tests.** Cover initial skeleton, nine-item success, signed changes with text labels, duplicated `aria-hidden` loop, quiet first-load failure, retaining rows after a refresh failure, 60-second visible polling, and a non-animated reduced-motion class.

```tsx
export interface MarketTickerItem { symbol: string; name: string; price: number; change_pct: number }
export async function getMarketTicker(base = API_BASE): Promise<{ items: MarketTickerItem[] }>;

expect(fetchMock).toHaveBeenCalledWith("/data/market-ticker");
expect(await screen.findByText("S&P 500")).toBeInTheDocument();
expect(screen.getByText(/up 1.25%/i)).toBeInTheDocument();
expect(screen.getByTestId("ticker-copy")).toHaveAttribute("aria-hidden", "true");
```

- [ ] **Step 2: Run `cd frontend; npm test -- src/lib/api.test.ts src/layout/GlobalMarketTicker.test.tsx`.** Expect missing exports/component failures.
- [ ] **Step 3: Implement `GlobalMarketTicker`.** It calls immediately, schedules a 60,000 ms interval, refreshes on `visibilitychange` only when `document.visibilityState === "visible"`, keeps the last successful items on failure, exposes `Updated HH:MM:SS`, and renders `Market feed unavailable` only when no successful data exists. The moving content contains one accessible list plus one `aria-hidden` copy.

```css
.market-ticker-track { animation: market-ticker-scroll 42s linear infinite; width: max-content; }
.market-ticker:hover .market-ticker-track { animation-play-state: paused; }
@media (prefers-reduced-motion: reduce) {
  .market-ticker-track { animation: none; transform: none; }
  .market-ticker-copy { display: none; }
}
```

- [ ] **Step 4: Rerun the focused tests and `npm run build`.** Expect both to pass.
- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts frontend/src/layout/GlobalMarketTicker.tsx frontend/src/layout/GlobalMarketTicker.test.tsx frontend/src/index.css frontend/tailwind.config.ts
git commit -m "feat(layout): add resilient global market ticker"
```

### Task 4: Add accessible responsive rails and the profile preview

**Files:**

- Create: `frontend/src/layout/ResponsiveRail.tsx`
- Create: `frontend/src/layout/ResponsiveRail.test.tsx`
- Create: `frontend/src/layout/ProfilePreview.tsx`
- Create: `frontend/src/layout/ProfilePreview.test.tsx`

- [ ] **Step 1: Write failing interaction tests.** Verify Escape closes, Tab/Shift+Tab cycle inside an open mobile rail, focus returns to the opener, overlay click closes, disabled profile controls cannot change, every future option says `Coming soon`, and the active theme is displayed.
- [ ] **Step 2: Run `cd frontend; npm test -- src/layout/ResponsiveRail.test.tsx src/layout/ProfilePreview.test.tsx`.** Expect missing component failures.
- [ ] **Step 3: Implement exact contracts.**

```tsx
export function ResponsiveRail(props: React.PropsWithChildren<{
  open: boolean; side: "left" | "right"; title: string;
  onClose: () => void; openerRef: React.RefObject<HTMLButtonElement | null>;
  className?: string;
}>): React.ReactElement;

export function ProfilePreview(props: {
  open: boolean; onClose: () => void; theme: Theme;
  openerRef: React.RefObject<HTMLButtonElement | null>;
}): React.ReactElement | null;
```

The profile panel shows `Desk Operator`, Theme, Language (`English`), Default market (`United States`), Refresh interval (`60 seconds`), and Notifications. Only the existing header theme button remains actionable; all settings controls use the native `disabled` attribute and an adjacent `Coming soon` badge. Use `role="dialog"`, `aria-modal="true"`, a labelled heading, initial focus on Close, a focus trap, body-scroll lock while open, and focus restoration.

- [ ] **Step 4: Rerun both focused tests.** Expect all tests to pass.
- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/layout/ResponsiveRail.tsx frontend/src/layout/ResponsiveRail.test.tsx frontend/src/layout/ProfilePreview.tsx frontend/src/layout/ProfilePreview.test.tsx
git commit -m "feat(layout): add accessible rails and profile preview"
```

### Task 5: Rebuild the global application shell

**Files:**

- Modify: `frontend/src/layout/AppLayout.tsx`
- Modify: `frontend/src/layout/AppLayout.test.tsx`
- Modify: `frontend/src/layout/IntelligenceSlot.test.tsx`

- [ ] **Step 1: Extend shell tests.** Assert `Multi-Agent Finance Desk` and the `MF` mark are present; `MIA`, `Dev Console`, and the backend version are absent; all five links retain their routes and receive icons; ticker renders without blocking the outlet; Profile opens; mobile navigation/activity controls open and close their rails; and the empty right rail says `System ready`.
- [ ] **Step 2: Run `cd frontend; npm test -- src/layout/AppLayout.test.tsx src/layout/IntelligenceSlot.test.tsx`.** Expect branding/profile/mobile failures.
- [ ] **Step 3: Refactor `AppLayout` while preserving its public props.**

```tsx
interface AppLayoutProps { threadId: string; onNewSession: () => void }
const NAV_ITEMS = [
  { to: "/briefing", label: "Briefing", icon: "briefing" },
  { to: "/clients", label: "Clients", icon: "clients" },
  { to: "/research", label: "Research", icon: "research" },
  { to: "/reports", label: "Reports", icon: "reports" },
  { to: "/data", label: "Data", icon: "data" },
] as const;
```

Keep health polling but discard version state. Header order is brand, health, theme, Profile. Put `GlobalMarketTicker` below it. Use a single responsive left rail and one responsive right rail so the Intelligence portal target never duplicates. On desktop the layout is navigation/center/activity; below `xl`, each rail is fixed only while open. `System ready` explains that activity appears after a Research or client-workspace run.

- [ ] **Step 4: Rerun focused tests plus `npm test -- src/App.test.tsx`, then `npm run build`.** Expect all to pass.
- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/layout/AppLayout.tsx frontend/src/layout/AppLayout.test.tsx frontend/src/layout/IntelligenceSlot.test.tsx
git commit -m "feat(layout): launch Multi-Agent Finance Desk shell"
```

### Task 6: Convert agent activity into a grouped run timeline

**Files:**

- Modify: `frontend/src/desk/activity.ts`
- Modify: `frontend/src/desk/activity.test.ts`
- Modify: `frontend/src/desk/DeskActivityRail.tsx`
- Modify: `frontend/src/desk/DeskActivityRail.test.tsx`

- [ ] **Step 1: Write failing pure and rendering tests.** Add supervisor mapping tests for both `supervisor` and `supervisor_agent`; run grouping after `done`, `error`, or `awaiting`; current-run status; humanized tool names; durations; approval; completion/token count; and transport errors. Retain the existing subscription/unsubscribe assertions.
- [ ] **Step 2: Run `cd frontend; npm test -- src/desk/activity.test.ts src/desk/DeskActivityRail.test.tsx`.** Expect missing grouping/supervisor/timeline failures.
- [ ] **Step 3: Add these types and pure helpers.**

```ts
export type SpecialistLabel = "SUPERVISOR" | "RAG" | "FINANCE" | "PORTFOLIO" | "BROWSER" | "EMAIL" | "FILES" | "MEMORY";
export interface ActivityRun {
  id: string; startedAt: number; items: DeskActivity[];
  status: "running" | "awaiting" | "done" | "error";
}
export function groupActivityRuns(items: DeskActivity[]): ActivityRun[];
export function humanizeToolName(name: string): string;
```

Start a new group after a terminal `done`, `error`, or `awaiting` item. Render newest run first, label it `Current run` when running/awaiting, use a vertical line with nodes, and keep timestamps/tokens in monospace. Empty copy is `System ready`; do not add a second event subscription or alter AG-UI transport.

- [ ] **Step 4: Rerun both focused tests.** Expect all to pass.
- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/desk/activity.ts frontend/src/desk/activity.test.ts frontend/src/desk/DeskActivityRail.tsx frontend/src/desk/DeskActivityRail.test.tsx
git commit -m "feat(desk): present activity as run timeline"
```

### Task 7: Modernize the Clients overview without extra market requests

**Files:**

- Create: `frontend/src/clients/useClients.ts`
- Create: `frontend/src/clients/useClients.test.tsx`
- Modify: `frontend/src/clients/ClientsPage.tsx`
- Modify: `frontend/src/clients/ClientsPage.test.tsx`
- Modify: `frontend/src/clients/ClientsList.tsx`
- Modify: `frontend/src/clients/ClientsList.test.tsx`

- [ ] **Step 1: Add failing tests.** Verify one `/data/clients` request, local search by name/email/ticker, segment and risk filters, clear filters, four derived metrics, holding preview capped at three plus an overflow count, retry on failure, empty results, and existing `/clients/:id` navigation.
- [ ] **Step 2: Run `cd frontend; npm test -- src/clients/useClients.test.tsx src/clients/ClientsPage.test.tsx src/clients/ClientsList.test.tsx`.** Expect missing hook/controls/metrics failures.
- [ ] **Step 3: Move fetch ownership into the hook and make the list presentational.**

```ts
export function useClients(): {
  clients: ClientWithHoldings[]; loading: boolean; error: string | null; retry: () => void;
};

export interface ClientsListProps {
  clients: ClientWithHoldings[]; query: string; segment: string; riskProfile: string;
  onQueryChange: (value: string) => void;
  onSegmentChange: (value: string) => void;
  onRiskProfileChange: (value: string) => void;
  onClearFilters: () => void;
}
```

`ClientsPage` renders `PageHeader`, metrics for clients, holding rows, unique segments, and a textual risk-profile distribution. It passes the single loaded array into `ClientsList`; no price, summary, or report endpoint may be called. Cards show identity, advisor/city, segment/risk badges, holding count, and at most three holdings.

- [ ] **Step 4: Rerun focused tests and use the fetch mock to assert exactly one request.** Expect all to pass.
- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/clients
git commit -m "feat(clients): modernize searchable client overview"
```

### Task 8: Modernize the client workspace while preserving its scoped Desk

**Files:**

- Modify: `frontend/src/clients/ClientWorkspace.tsx`
- Modify: `frontend/src/clients/ClientWorkspace.test.tsx`

- [ ] **Step 1: Add failing tests for skeleton, hero KPIs, risk/advisor badges, partial pricing copy, retry/back error state, and the existing scoped Desk contract.** Keep assertions that route changes remount and that `threadId` is exactly `clients_<id>`.
- [ ] **Step 2: Run `cd frontend; npm test -- src/clients/ClientWorkspace.test.tsx`.** Expect new presentation/state failures while legacy behavior remains green.
- [ ] **Step 3: Replace only the header/error/loading markup.** Use `PageHeader`, `MetricCard`, `StatusBadge`, `Skeleton`, and `ErrorState`; show Market value, Unrealized P&L, Return, and Priced positions. Preserve the keyed `ClientWorkspaceBody`, `getClientSummary(clientId)`, and the unchanged `<DeskView threadId={`clients_${clientId}`} />` below the hero.
- [ ] **Step 4: Rerun the focused test and `npm test -- src/desk/DeskView.test.tsx`.** Expect all to pass.
- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/clients/ClientWorkspace.tsx frontend/src/clients/ClientWorkspace.test.tsx
git commit -m "feat(clients): modernize client workspace hero"
```

### Task 9: Modernize Reports while preserving the explicit heavy-load gate

**Files:**

- Modify: `frontend/src/reports/ReportsPage.tsx`
- Modify: `frontend/src/reports/ReportsPage.test.tsx`
- Modify: `frontend/src/reports/ReportsList.tsx`
- Modify: `frontend/src/reports/ReportsList.test.tsx`
- Modify: `frontend/src/reports/ReportWorkspace.tsx`
- Modify: `frontend/src/reports/ReportWorkspace.test.tsx`

- [ ] **Step 1: Add failing overview and workspace tests.** Cover shared header/metrics, structured report-selection cards, skeleton/error states, summary hero, and card headings `Analysis`, `Portfolio allocation`, `Sector exposure`, `Price trends`, `Concentration risk`, `Positions`, and `Generated reports`. Assert `/report` is not fetched before `View full report`, is fetched once after click, and generation still refetches it.
- [ ] **Step 2: Run `cd frontend; npm test -- src/reports`.** Expect presentation failures; the progressive-load assertions must already pass.
- [ ] **Step 3: Reuse `useClients()` in `ReportsPage`, pass clients to a presentational `ReportsList`, and wrap loaded report sections in `SurfaceCard`/`SectionHeader`.** Keep `loadFull()` and `onGenerate()` behavior unchanged. Use summary KPIs for value, P&L, return, and price coverage. Show a local full-report skeleton after the explicit click without hiding the summary hero.
- [ ] **Step 4: Rerun `npm test -- src/reports` and confirm the test has exactly zero `/report` calls before the gate.** Expect all to pass.
- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/reports
git commit -m "feat(reports): modernize progressive report workspace"
```

### Task 10: Modernize Data and add accessible drag-and-drop import

**Files:**

- Modify: `frontend/src/data/DataPage.tsx`
- Modify: `frontend/src/data/DataPage.test.tsx`
- Modify: `frontend/src/data/DocumentsList.tsx`
- Modify: `frontend/src/data/DocumentsList.test.tsx`
- Modify: `frontend/src/data/ImportPanel.tsx`
- Modify: `frontend/src/data/ImportPanel.test.tsx`

- [ ] **Step 1: Add failing tests.** Verify the page header, `tablist`/`tab` semantics and selected state, document cards with PDF/Excel/generic icons, skeleton/empty/retry states, keyboard file selection, drag-enter visual state, PDF drop, Excel drop, unsupported-extension rejection before API calls, preview validation, raw-row confirmation, success, and same-file reset.
- [ ] **Step 2: Run `cd frontend; npm test -- src/data`.** Expect semantic/drop-zone failures.
- [ ] **Step 3: Refactor file selection through one path.**

```ts
const ACCEPTED_EXTENSIONS = [".pdf", ".xlsx", ".xls"] as const;
function selectFile(file: File | null): void;
function onDrop(event: React.DragEvent<HTMLDivElement>): void {
  event.preventDefault();
  setDragging(false);
  selectFile(event.dataTransfer.files[0] ?? null);
}
```

Render the drop zone as a focusable `<div role="button" tabIndex={0}>` that clicks the hidden input and responds to Enter/Space. Keep PDF direct upload and Excel `XLSX.read`/preview/confirm flows exactly as they are. Translate the visible `Confirmer` label to `Confirm import` to satisfy the approved English-only UI.

- [ ] **Step 4: Rerun `npm test -- src/data` and `npm run build`.** Expect all to pass.
- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/data
git commit -m "feat(data-ui): modernize document library and import"
```

### Task 11: Modernize Research through supported CopilotKit surfaces

**Files:**

- Modify: `frontend/src/desk/DeskView.tsx`
- Modify: `frontend/src/desk/DeskView.test.tsx`
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Extend regression tests.** Assert the compact `Research workspace` identity is present; `CopilotKitProvider` still receives the same agent map/message filter; `CopilotChat` still receives `agentId`, exact `threadId`, attachments, supported static `input` config, and a modern root class; `useConfigureSuggestions` receives all three existing suggestions plus `available: "always"`; history still seeds the same `HttpAgent`; and the Intelligence portal still contains `DeskActivityRail`.
- [ ] **Step 2: Run `cd frontend; npm test -- src/desk/DeskView.test.tsx src/desk/ApprovalPanel.test.tsx src/desk/displays/useToolDisplay.test.tsx`.** Expect only the new identity/config assertions to fail.
- [ ] **Step 3: Add a compact page header above `CopilotChat`, set `available: "always"`, and keep the documented v2 import/style path.** Use the existing supported `className` and `input` props for the chat/composer. Scope CopilotKit theme variables under `.finance-desk-chat` for card radius, visible borders, panel/background colors, and focus rings; do not target generated child class names or replace message renderers.
- [ ] **Step 4: Rerun the focused tests and `npm run build`.** Expect provider, history, attachment, approval, tool-display, and build checks to pass.
- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/desk/DeskView.tsx frontend/src/desk/DeskView.test.tsx frontend/src/index.css
git commit -m "feat(research): align market desk chat with product UI"
```

### Task 12: Adopt equivalent primitives in Briefing without changing its loading graph

**Files:**

- Modify: `frontend/src/briefing/BriefingPage.tsx`
- Modify: `frontend/src/briefing/BriefingPage.test.tsx`
- Modify: `frontend/src/briefing/ClientAlertsPanel.tsx`
- Create: `frontend/src/briefing/ClientAlertsPanel.test.tsx`
- Verify only: `frontend/src/briefing/briefingData.ts`
- Verify only: `frontend/src/briefing/MarketIndexGrid.tsx`
- Verify only: `frontend/src/briefing/MarketSummary.tsx`
- Verify only: `frontend/src/briefing/MarketNews.tsx`

- [ ] **Step 1: Add a regression assertion that all independent components mount on the initial render and that changing markets updates only market-dependent props.** Retain the six-tab assertion and add a `PageHeader` contract assertion. Add `ClientAlertsPanel` tests for skeleton, breach cards, all-clear, and unavailable states; assert it uses the shared section/card/badge presentation without `font-mono`.
- [ ] **Step 2: Run `cd frontend; npm test -- src/briefing`.** Record the baseline and ensure no existing Briefing test is lost.
- [ ] **Step 3: Replace only equivalent markup with shared primitives.** Use `PageHeader`/`SurfaceCard` at the page top and `SurfaceCard`/`SectionHeader`/`StatusBadge`/`Skeleton` in `ClientAlertsPanel`. Do not combine requests, move fetching into `BriefingPage`, remove `loadMarketIndices` prefetching, or add a page-wide loading state. Keep `MarketIndexGrid`, `MarketSummary`, `MarketNews`, `WatchlistGrid`, `SectorPanel`, `MarketMovers`, and `ClientAlertsPanel` mounted as siblings.
- [ ] **Step 4: Rerun `npm test -- src/briefing` and `npm run build`.** Expect all to pass with unchanged loading tests.
- [ ] **Step 5: Commit only the top-level Briefing primitive integration.**

```powershell
git diff -- frontend/src/briefing/BriefingPage.tsx frontend/src/briefing/BriefingPage.test.tsx frontend/src/briefing/ClientAlertsPanel.tsx frontend/src/briefing/ClientAlertsPanel.test.tsx
git add frontend/src/briefing/BriefingPage.tsx frontend/src/briefing/BriefingPage.test.tsx frontend/src/briefing/ClientAlertsPanel.tsx frontend/src/briefing/ClientAlertsPanel.test.tsx
git commit -m "feat(briefing): integrate modern dashboard components"
```

### Task 13: Cross-route regression, accessibility QA, and local handoff

**Files:**

- Modify: `frontend/src/App.test.tsx`
- Modify if a defect is found: the smallest owning component and its colocated test

- [ ] **Step 1: Add route-level regression tests.** Mount `/briefing`, `/clients`, `/research`, `/reports`, and `/data` through the real router with network/Copilot boundaries mocked. Assert the shared shell remains visible while each page renders, and `/classic` remains independently reachable but absent from navigation.
- [ ] **Step 2: Run complete automated verification.**

```powershell
uv run pytest tests/ -v
Set-Location frontend
npm test
npm run build
Set-Location ..
```

Expected: every pytest and Vitest test passes and Vite produces `frontend/dist` without TypeScript errors.

- [ ] **Step 3: Run manual responsive/theme QA at 1440 px, 1024 px, and 390 px.** Check all five routes in light and dark themes; verify no horizontal page overflow, visible focus, Escape/focus return for all drawers, paused ticker on hover, no ticker animation under reduced motion, readable Research center width, and no full-page blanking during local loads.
- [ ] **Step 4: Commit any route-level test or QA corrections.**

```powershell
git add frontend/src/App.test.tsx
git commit -m "test(ui): cover modernized product routes"
```

- [ ] **Step 5: Restart the project for user testing.** First resolve listeners on ports 8000 and 5173 and stop only those exact owning PIDs. Then launch hidden background processes from their correct working directories.

```powershell
$projectRoot = "F:\langchain-langgraph-mcp\market-agent\market-intelligence-agent"
$frontendRoot = Join-Path $projectRoot "frontend"
Start-Process -FilePath "uv" -ArgumentList "run","uvicorn","app.api.server:app","--host","0.0.0.0","--port","8000","--reload" -WorkingDirectory $projectRoot -WindowStyle Hidden
Start-Process -FilePath "npm.cmd" -ArgumentList "run","dev","--","--host","0.0.0.0","--port","5173" -WorkingDirectory $frontendRoot -WindowStyle Hidden
```

Verify `http://127.0.0.1:8000/health`, `http://127.0.0.1:8000/data/market-ticker`, and `http://127.0.0.1:5173/briefing` before handoff. Report the exact test counts, build result, running URLs, and any upstream market-feed limitation.
