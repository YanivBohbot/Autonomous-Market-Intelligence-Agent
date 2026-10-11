# Navigation Shell (chantier 1 of 4) — Design

**Status:** Approved by user, 2026-10-04. Ready for `writing-plans`.

**Roadmap context:** The user sketched a 5-section Market Desk navigation (Briefing · Clients · Recherche · Rapports · Données) with a persistent 3-column layout (Navigation | active content | Intelligence), replacing the current 3-flat-link `Header.tsx` (Market Desk / Classic / Clients). Three of those five sections need real new backend work (Clients' per-client workspace, Rapports' report history, Briefing's daily summary aggregation) and are each their own future chantier with their own spec. **This spec covers chantier 1 only: the navigation structure itself, plus the two sections that need zero new backend** — Recherche (the existing Market Desk chat, moved and renamed) and Données (the existing `/data` Documents+Import page, moved and renamed). Briefing, Clients and Rapports get a placeholder page in this chantier; their real content is out of scope here.

## Goal

Replace `Header.tsx`'s 3 flat nav links with a 5-section left-nav layout (`AppLayout`) that every section renders inside, matching the shape of a modern SaaS console: persistent navigation rail, central content area, and a right "Intelligence" column. Wire the two sections that already have real content (Recherche, Données) into it. The other three sections render a placeholder for now.

## Why

Closes the gap between the current flat 3-link header and the navigation shape the user actually wants for the product, without taking on the three content-heavy chantiers (Clients workspace, Rapports history, Briefing aggregation) in the same change. Each of those is its own spec, sequenced after this one.

## Decisions (from brainstorming)

1. **Five nav entries:** Briefing, Clients, Recherche, Rapports, Données — in that order, left-to-right in the mockup becomes top-to-bottom in a left nav rail.
2. **Briefing** = future daily auto-generated summary (concentration alerts, notable market moves on client tickers, agent-written synthesis) — placeholder this chantier.
3. **Clients** = future per-client workspace (résumé, chart, positions, client-scoped chat) that *replaces* today's read-only `/data` Clients tab — placeholder this chantier; today's Clients tab functionality moves to **Données** instead (see below).
4. **Recherche** = today's Market Desk chat (`DeskView.tsx`), moved into the new shell and relabeled. No functional change.
5. **Rapports** = future report generator + history (finishes the PDF/Word export sub-project, adds persistence for past reports, which doesn't exist yet) — placeholder this chantier.
6. **Données** = today's `/data` page (`DataPage.tsx`: Clients/Documents/Import tabs), moved into the new shell under this label, unchanged internally. It is a 5th nav entry, not folded into Rapports or Briefing. **Known interim duplication:** `DataPage.tsx`'s own internal tab is still labeled "Clients" (unchanged, per decision 6) while the nav *also* has a "Clients" entry (the chantier-4 placeholder, decision 3) — two different things sharing a label until the Clients chantier ships and actually replaces the read-only tab. Not a defect to fix here; the plan should not rename either.
7. **Classic** chat stays a working route (`/classic`) for debugging the original single-agent graph, but drops out of the main navigation — not one of the 5 entries, no link to it in `AppLayout`'s nav rail. It keeps its current standalone 2-column layout (not wrapped in `AppLayout`).
8. **Profil** (top-right in the mockup) is a stub this chantier: a static button/avatar that opens nothing functional yet.
9. **3-column layout applies to every section**, including the three placeholders — consistent shell even where the right column is empty.
10. **Naming:** the layout component is called `AppLayout`, not `AppShell` — reads as a product layout, not a dev-tool shell.
11. **Default route** (`/`) redirects to `/recherche` — there's no real Briefing yet to serve as a landing page.

## Architecture

### Routing (`frontend/src/App.tsx`)

`react-router-dom` (already a dependency) nests the 5 new routes under `AppLayout` via `<Outlet/>`:

```
<Route element={<AppLayout />}>
  <Route path="/" element={<Navigate to="/recherche" replace />} />
  <Route path="/briefing" element={<ComingSoonPage title="Briefing" description="..." />} />
  <Route path="/clients" element={<ComingSoonPage title="Clients" description="..." />} />
  <Route path="/recherche" element={<DeskView key={threadId} threadId={`desk_${threadId}`} />} />
  <Route path="/rapports" element={<ComingSoonPage title="Rapports" description="..." />} />
  <Route path="/data" element={<DataPage />} />
</Route>
<Route path="/classic" element={<ClassicChat key={threadId} threadId={threadId} />} />
```

`/data`'s path is unchanged (nothing links to it by a different URL today, no reason to break bookmarks); only its nav label changes to "Données".

### `AppLayout` (`frontend/src/shell/AppLayout.tsx`, new)

Three-column CSS grid: nav rail (fixed width, left) | `<Outlet/>` (flexible, center) | Intelligence column (fixed width, right). Carries everything `Header.tsx` has today — backend health dot, version badge, session id, "+ New session", theme toggle — reorganized into the nav rail (session/health/theme live in a compact top strip above or below the 5 nav links; exact arrangement is an implementation-time layout detail, not a design decision) plus the new Profil stub button. `Header.tsx` itself is retired; its logic (health polling, theme state) moves into `AppLayout`.

Nav links use `NavLink` (react-router) for active-state styling, same visual language already established (accent-colored active state, as `Header.tsx` does today).

### Intelligence column — content via a slot hook, not global wiring

`DeskActivityRail.tsx` calls `useAgent({agentId: MARKET_DESK_AGENT_ID})` — it only works inside the `CopilotKitProvider` that `DeskView` already sets up, so `AppLayout` cannot render it directly for every route. Instead, `AppLayout` exposes a slot via React context:

- `frontend/src/shell/IntelligenceSlot.tsx` (new): `IntelligenceSlotProvider` (wraps the app once, in `AppLayout`), `useIntelligenceSlot(node: ReactNode)` — a hook a page calls to push its content into the column; a `useEffect` cleanup clears it on unmount so switching sections doesn't leak the previous page's content.
- `AppLayout` renders whatever is currently in the slot, or a static empty state ("Aucune activité") when nothing has been pushed.
- `DeskView` (Recherche) calls `useIntelligenceSlot(<DeskActivityRail/>)` once mounted — same component, same behavior as today, just rendered through the slot instead of as a direct JSX child.
- `ComingSoonPage` and `DataPage` push nothing; the column shows the empty state for them.

### `ComingSoonPage` (`frontend/src/shell/ComingSoonPage.tsx`, new)

One reusable component — `{ title: string; description: string }` props — used for Briefing, Clients and Rapports. Not three near-duplicate files.

## Data flow

No new backend endpoints. This chantier is a frontend restructuring: moving two already-working pages (`DeskView`, `DataPage`) under a new layout, and adding static placeholders for the other three. `DeskActivityRail`'s data flow (AG-UI events via `useAgent`) is unchanged — only *where* it renders changes.

## Error handling

Nothing new: the moved pages (`DeskView`, `DataPage`) keep their existing error handling (fetch `.catch()` on `ClientsList`/`DocumentsList`, AG-UI's own error events for the chat) unchanged. `ComingSoonPage` has no failure modes — it's static.

## Testing

**Frontend (Vitest):**
- `AppLayout.test.tsx` (new) — renders the 5 nav links with correct hrefs and labels (Briefing/Clients/Recherche/Rapports/Données), confirms `/classic` has no nav link, confirms the active route gets the active-state class, confirms `/` redirects to `/recherche`.
- `IntelligenceSlot.test.tsx` (new) — a test component calling `useIntelligenceSlot` renders into the slot; unmounting it clears the slot back to the empty state; a second component's content doesn't leak after the first unmounts.
- `ComingSoonPage.test.tsx` (new) — renders the given title/description.
- `App.test.tsx` (existing) — update the routing assertions for the new paths (`/recherche` instead of `/`, nav link assertions move to `AppLayout.test.tsx` or get updated in place).
- `Header.test.tsx` (existing) — retired along with `Header.tsx`; its still-relevant assertions (health polling, theme toggle, session display) move into `AppLayout.test.tsx`.
- `DeskView.test.tsx` (existing) — update only if `useIntelligenceSlot` wiring changes its render tree in a way the existing assertions check against; its own content/behavior is unchanged.

**Live QA (one grounded pass):** click through all 5 nav entries + Profil stub, confirm Recherche's chat and activity rail work exactly as Market Desk does today, confirm Données' tabs work exactly as `/data` does today, confirm the 3 placeholders render without errors, confirm `/classic` still works and has no nav entry pointing to it, confirm light/dark toggle still works from the new layout.

## Out of scope (explicitly, for this chantier)

- Real content for Briefing, Clients, Rapports — each is its own future spec.
- Any new backend endpoint or agent logic.
- The Profil button opening anything functional.
- Removing or changing `/classic`'s own internal behavior.
