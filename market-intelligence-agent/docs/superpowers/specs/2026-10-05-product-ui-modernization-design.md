# Multi-Agent Finance Desk UI Modernization — Design

**Status:** Design approved by the user on 2026-10-05. Awaiting written-spec review before implementation planning.

## Goal

Turn the existing React console into one coherent financial product named **Multi-Agent Finance Desk**. The current Briefing page is the visual reference: bright financial surfaces, restrained blue and green accents, generous spacing, rounded cards, clear hierarchy, progressive loading, and full light/dark support. Clients, Research, Reports, Data, the global navigation, the multi-agent activity trace, and the profile affordance will adopt this system without changing their established business behavior.

## Success Criteria

- No visible `MIA · Dev Console` or `v0.0.0` branding remains in the main product shell.
- Every main route looks like part of the same product as Briefing.
- The shell includes a non-blocking global market ticker and persistent navigation.
- Agent activity is understandable as a chronological run timeline, not a developer log.
- Existing Clients, Research, Reports, Data, approval, chat, and routing behavior remains intact.
- Loading, empty, error, focus, responsive, light, and dark states are designed rather than incidental.
- The profile control opens a polished preview of future settings, but does not persist preferences in this version.

## Approved Product Decisions

1. **Product name:** `Multi-Agent Finance Desk`.
2. **Language:** English throughout the application.
3. **Visual reference:** the existing Briefing page, extended into a shared design system.
4. **Implementation approach:** shared UI primitives first, followed by progressive page migration. No rewrite of the React application or agent integrations.
5. **Shell:** persistent left navigation, central content, and persistent contextual activity rail on the right. On smaller screens, both rails become drawers.
6. **Global market ticker:** a continuously moving world view containing S&P 500, Nasdaq, Dow Jones, DAX, Nikkei 225, Bitcoin, EUR/USD, gold, and crude oil.
7. **Activity presentation:** a timeline grouped by run, showing supervisor/specialist steps, tool calls, durations, approval waits, completion, and errors.
8. **Profile:** a visual-only settings preview with `Coming soon` states.
9. **Themes:** retain both light and dark themes. Sans-serif is the default; monospace is reserved for symbols, timestamps, IDs, and raw technical values.
10. **Behavior preservation:** UI modernization must not restructure the LangGraph/AG-UI flows or replace CopilotKit.

## Visual System

The implementation will consolidate repeated styles into focused components under `frontend/src/ui/`:

- `PageHeader`: eyebrow, title, description, actions, and optional gradient treatment.
- `SurfaceCard`: consistent border, radius, background, shadow, and padding variants.
- `SectionHeader`: section title, supporting text, and optional action.
- `MetricCard`: label, value, delta, and state color.
- `StatusBadge`: neutral, info, success, warning, and danger variants.
- `Skeleton`: reusable text, card, and row placeholders.
- `EmptyState` and `ErrorState`: explanatory copy with an optional action.
- `Icon`: a small internal SVG set for navigation and status cues; no new icon dependency is required.

Existing CSS variables remain the theme source of truth so the migration does not require rewriting every Tailwind class. New semantic tokens may be added for brand blue, elevated surfaces, and soft gradients. The old CRT `scan-lines` treatment and routine use of `font-mono` are removed from the product shell.

## Global Product Shell

`frontend/src/layout/AppLayout.tsx` remains the routing layout but is visually rebuilt:

- **Header:** `MF` brand mark, full product name, compact backend health state, theme control, and profile control. The backend version is no longer shown to end users.
- **Ticker row:** `GlobalMarketTicker` sits immediately below the header. It scrolls two copies of the same instruments for a seamless loop, pauses on hover, and respects `prefers-reduced-motion`.
- **Left navigation:** the existing five routes remain in their current order. Each link gains an icon, improved active state, and accessible focus state. A non-route Settings/Profile affordance sits at the bottom.
- **Center:** routes render into a consistent page-width and spacing system while retaining layouts that genuinely need full height, such as Research.
- **Right activity rail:** always reserves the chosen contextual rail on desktop. Routes without an active agent show a polished `System ready` state rather than a blank `No activity` panel.
- **Responsive behavior:** below the desktop breakpoint, navigation and activity become overlay drawers with explicit open/close controls. The ticker and central content remain visible.

The standalone `/classic` developer route remains available and out of the primary navigation. Its behavior is out of scope, though shared tokens may improve it automatically.

## Global Market Ticker Data

Add `GET /data/market-ticker` to the existing data router. It uses the dashboard's direct batched yfinance path for these symbols:

- `^GSPC`, `^IXIC`, `^DJI`, `^GDAXI`, `^N225`
- `BTC-USD`, `EURUSD=X`, `GC=F`, `CL=F`

The endpoint returns `symbol`, `name`, `price`, and `change_pct`. It uses a 60-second cache and single-flight protection so multiple mounted consumers never duplicate a refresh. Market data loads independently from the shell; a compact ticker skeleton is shown while waiting, and a failure collapses to a quiet `Market feed unavailable` state without blocking navigation. The frontend polls every 60 seconds while visible and displays the last successful update time. The UI describes the feed as live but does not claim exchange-grade real-time data because Yahoo quotes may be delayed.

## Page Designs

### Clients

`ClientsPage` receives a Briefing-style header and summary metrics derived from the already-loaded client list: client count, total positions, represented segments, and risk-profile distribution. `ClientsList` adds client-side search plus segment and risk filters. Each client is rendered as a structured card with identity, profile metadata, holding count, and a restrained holdings preview. No extra price fetches are introduced on the list page.

`ClientWorkspace` receives a modern client hero containing identity, advisor, risk profile, market value, performance, and price-availability state. Its existing scoped `DeskView` remains the functional workspace below it.

### Research

Research keeps `CopilotKitProvider`, `HttpAgent`, interrupts, tool displays, attachments, history restoration, and the existing agent/thread boundaries. It gains a compact page identity area, improved suggested-prompt cards, Briefing-style message surfaces, and a consistent composer. The redesign must use supported CopilotKit class/configuration hooks rather than brittle selectors where possible.

### Reports

`ReportsPage` uses the shared page header, summary metrics, and structured client selection cards. `ReportWorkspace` presents the fast client summary as a hero/KPI area, then keeps the existing explicit `View full report` gate. Loaded content is grouped into clear cards for analysis, allocation, sector exposure, price trends, concentration risk, positions, and generated files. Report generation behavior and progressive loading remain unchanged.

### Data

`DataPage` gains the shared page header and modern pill tabs. `DocumentsList` becomes a document library with file-type icon, filename, and a useful empty state. `ImportPanel` becomes a large accessible drop zone supporting click-to-select and drag-and-drop for the already-supported PDF/Excel formats. Preview, validation errors, confirmation, and success states use shared cards and badges; import API behavior is unchanged.

### Briefing

Briefing content remains the visual source of truth. It is integrated into the new shell and adjusted only where shared primitives replace equivalent local markup. Its independent data-loading architecture must not regress.

### Profile Preview

Clicking Profile opens an accessible side panel or popover with user identity and visible future settings: theme, language, default market, refresh interval, and notifications. All unavailable controls are disabled and labeled `Coming soon`. Theme may continue to use the existing global theme control, but the profile preview itself stores no preferences and calls no backend endpoint.

## Multi-Agent Activity Timeline

`DeskActivityRail` keeps subscribing to the same AG-UI agent instance and continues to use the pure `reduceActivity` transformation. The rendering changes from compact monospace log rows to a run timeline:

- Supervisor and specialist steps use distinct but restrained colored nodes.
- Tool calls show a human-readable tool name, running/completed state, and duration.
- Approval waits use a warning treatment.
- Run completion shows total token usage when available.
- Errors show concise copy with expandable technical detail only if already present in the event.
- New runs are visually separated; the current run remains prominent.

No new agent events or backend graph changes are required. Empty state is `System ready`, with a short explanation that activity will appear when Research or a client workspace starts a run.

## Data and State Boundaries

- Shared UI components are presentation-only and do not fetch data.
- Each page retains ownership of its existing page data and errors.
- The ticker owns only market-ticker polling and cache state.
- `AppLayout` owns shell state: responsive drawers, theme control, profile preview, and backend health.
- `DeskActivityRail` owns only AG-UI activity presentation.
- Profile-preview controls are static and cannot imply successful persistence.

This separation prevents the visual refactor from coupling unrelated page requests or recreating the all-page loading problem already corrected in Briefing.

## Loading, Empty, and Error Behavior

- Never replace an entire page with a spinner when a local section can show a skeleton.
- Preserve already-rendered data during background refreshes.
- Use actionable retry buttons for recoverable page requests.
- Missing optional content produces a local empty state, not a page error.
- Ticker, backend health, and agent activity failures never prevent route navigation.
- Disabled profile controls use both visual and semantic disabled states.

## Accessibility and Responsive Requirements

- All controls have visible focus styles and useful accessible names.
- Color is never the only indicator of positive/negative or success/error state.
- Drawers trap focus while open and close with Escape.
- Ticker motion stops under `prefers-reduced-motion`.
- Cards and data grids reflow without horizontal page overflow.
- Desktop Research preserves enough center width for chat; the activity rail may collapse before the main content becomes unusable.

## Testing

Frontend Vitest/Testing Library coverage will include:

- Shared primitives and their variants.
- App shell branding, absence of the dev-console/version labels, navigation, profile preview, responsive controls, and theme behavior.
- Global ticker loading, success, failure, refresh, and reduced-motion markup.
- Clients search/filtering and cards.
- Research provider/thread/approval behavior regression tests.
- Reports progressive-load and generation behavior after restyling.
- Data tabs, drag-and-drop, validation, confirmation, and empty states.
- Activity timeline rendering for specialists, tools, approvals, completion, and errors.

Backend pytest coverage will include the market-ticker happy path, cache reuse, partial-symbol failure, total provider failure, and invalid payload resilience. Handoff requires the complete backend and frontend suites, a production frontend build, and a locally running backend/frontend for user testing.

## Delivery Sequence

1. Shared visual primitives and theme tokens.
2. Product shell, brand, global ticker, responsive rails, and profile preview.
3. Activity timeline.
4. Clients and client workspace.
5. Reports list and report workspace.
6. Research and Data.
7. Briefing primitive adoption, cross-route responsive QA, complete verification, and local restart.

## Out of Scope

- Authentication or user-account management.
- Persisted profile preferences or notification delivery.
- Customizable ticker instruments.
- Exchange-grade streaming quotes or WebSocket market feeds.
- Changes to LangGraph routing, specialist responsibilities, MCP tools, or approval semantics.
- Removal or functional redesign of `/classic`.
