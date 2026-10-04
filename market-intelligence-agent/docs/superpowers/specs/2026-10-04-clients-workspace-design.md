# Clients Workspace (chantier 2 of 4) — Design

**Status:** Approved by user, 2026-10-04. Ready for `writing-plans`.

**Roadmap context:** Chantier 1 (`2026-10-04-nav-shell-design.md`) shipped the 5-section `AppLayout` with Clients as a `ComingSoonPage` placeholder. This spec is chantier 2: the real Clients section. Per chantier 1's decision 3, this *replaces* today's read-only `/data` Clients tab rather than coexisting with it.

## Goal

Turn `/clients` into a client list + per-client workspace: a profile/P&L header, a chat scoped to that client (reusing the existing Market Desk multi-agent backend, context-aware of which client is active, no need for the user to name the client every turn), and the same Intelligence activity column Recherche already has.

## Why

Closes chantier 1's Clients placeholder with its intended content, absorbing `DataPage.tsx`'s Clients tab (per chantier 1 decision 3) instead of leaving two "Clients" surfaces in the app.

## Decisions (from brainstorming)

1. **Scope:** list + chat-contextualized workspace (the ASCII mockup's "Client / demande active" column), not a static detail page and not a bare list migration.
2. **`/data`'s Clients tab is removed**, absorbed into `/clients`. `DataPage.tsx` keeps Documents + Import only. `ClientsList.tsx` moves under the new `/clients` route.
3. **Workspace header shows profile + computed P&L** (total market value, unrealized P&L %), not just static profile fields — reuses the existing deterministic `compute_portfolio_metrics` (no LLM).
4. **Context injection mechanism: thread-id-derived, not a frontend context hook.** A backend graph node reads `client_id` straight out of the thread id (`clients_<id>`) via `config["configurable"]["thread_id"]` — standard LangGraph node/config plumbing — and loads that client's profile from `customers.db` fresh on every turn. No `useAgentContext`, no dependency on `ag_ui_langgraph`'s internal AG-UI-context-to-state merge (verified in `ag_ui_langgraph`'s installed source: it writes incoming AG-UI `context` into `state["ag-ui"]`, a key `SupervisorState` doesn't declare and which isn't a valid Python identifier in class-syntax `TypedDict` — avoidable entirely by deriving from thread id instead).
5. **Context reaches only the specialists that answer client questions:** `portfolio_agent`, `finance_agent`, `rag_agent`. `email_agent`/`browser_agent`/`memory_agent`/`filesystem_agent` are untouched.
6. **Thread persists per client:** `threadId = clients_${clientId}`, fixed — same pattern Recherche already uses (`desk_${threadId}`). Revisiting a client later resumes the same conversation via the checkpointer, across page reloads.
7. **Intelligence column reuses `DeskActivityRail` as-is** — it already watches whatever thread/agent `useAgent` is pointed at; no new component needed.
8. Verified against current LangChain and CopilotKit documentation (context7): `@dynamic_prompt` reading `request.state` and `create_agent(state_schema=...)` extended per specialist are the officially documented pattern (`docs.langchain.com/oss/python/langchain/context-engineering`, multi-agent handoffs doc); meaningful per-entity `threadId`s are the officially documented CopilotKit/AG-UI threading convention. Neither LangGraph's `Runtime`/`context_schema` mechanism nor a frontend AG-UI context hook is needed for this feature.

## Known limitation (discovered during live QA, 2026-10-05) — fixed same day

Decision 6's "resumes the same conversation via the checkpointer, across page reloads" was true at the **backend** level only at first: the LangGraph checkpoint and the model's context both correctly carried the full prior conversation forward, but `CopilotChat`/`useAgent` in `@copilotkit/react-core/v2` only set `threadId` as outgoing request metadata (confirmed by reading the installed package source — `agent.threadId = resolvedThreadId` is a bare property assignment, no fetch/connect call). There was no client-side mechanism that fetched and replayed a thread's prior messages on mount, so the chat panel started visually empty after a reload even though the backend remembered everything. Never noticed on Recherche since its `threadId` is a fresh random id every page load.

**Fixed** the same day: `GET /copilot/market-desk/history` (`app/api/routers/copilot.py`) reads the checkpointed user/assistant messages for a thread with no run/model call; `DeskView` fetches it on mount and calls the AG-UI agent's own `setMessages(...)` (an existing library method, discovered by reading `@ag-ui/client`'s source) before the user types anything. Recherche gets this too, for free, via the same shared `DeskView`.

## Architecture

### Frontend

- **`frontend/src/clients/ClientsPage.tsx`** (new, replaces the `ComingSoonPage` on `/clients`): fetches `GET /data/clients`, renders the existing `ClientsList.tsx` presentation (moved from `frontend/src/data/`), each row navigates to `/clients/:id` on click.
- **`frontend/src/clients/ClientWorkspace.tsx`** (new): on mount, fetches `GET /data/clients/:id/summary` for the header (name, segment, risk_profile, advisor, total market value, unrealized P&L %). Renders `CopilotChat` with `agentId={MARKET_DESK_AGENT_ID}`, `threadId={\`clients_${clientId}\`}`, same composer config `DeskView` already uses (`input={{positioning: "static", ...}}`, same classNames — visual parity with Recherche/Classic). Calls `useIntelligenceSlot(<DeskActivityRail/>)` exactly like `DeskBody` does today.
- **`frontend/src/App.tsx`**: `/clients` route → `ClientsPage`; new `/clients/:id` route → `ClientWorkspace`, both still nested under `AppLayout`.
- **`frontend/src/data/DataPage.tsx`**: drop the `"clients"` tab; `tabs` becomes `[documents, import]`; `ClientsList.tsx` is removed from `frontend/src/data/` (moved, not duplicated).
- **`frontend/src/lib/api.ts`**: new `getClientSummary(clientId)` returning the summary shape below.

### Backend

- **`app/api/routers/data.py`**: new `GET /data/clients/{client_id}/summary`. Deterministic, no agent involvement (same philosophy as the rest of `data.py`):
  1. Load the client row + holdings (reuse `list_clients_with_holdings`-style query, scoped to one client; 404 if the id doesn't exist).
  2. Fetch a live price per held ticker via `yf_quote_tool.ainvoke` (the same tool `concentration_screen` already calls directly, outside the agent graph) — `asyncio.gather`, tolerating individual failures (see Error handling).
  3. Run `compute_portfolio_metrics` (pure function, `app/agent/tools/finance_calc.py`) over the positions with a resolved price; positions with no resolved price are reported but excluded from the computed totals.
  4. Response: `{client_id, name, email, segment, risk_profile, advisor, city, totals: {market_value, cost_basis, unrealized_pnl, unrealized_pnl_pct} | None, positions: [...], unpriced_tickers: [...]}`.
- **`app/agent/multi_agent/state.py`**: `SupervisorState` gains `client_context: Optional[str]`.
- **`app/agent/multi_agent/graph.py`**: new node `load_client_context(state, config)`, wired `START -> load_client_context -> record_question -> supervisor` (or merged into `record_question` — an implementation-time call, not a design one). Reads `config["configurable"]["thread_id"]`; if it matches `^clients_(\d+)$`, queries `customers.db` directly (plain `sqlite3`, same convention as `app/data_import/db.py`) for that client's `name`/`segment`/`risk_profile`/`advisor`, formats one short sentence, writes it to `state["client_context"]`. No match, or client no longer exists → `None`. Runs every turn (cheap single-row read), so edits via `/data/import` mid-conversation are reflected immediately — matches the existing `fresh_documents_prompt` philosophy of never serving stale data from a long-running process.
- **`app/agent/middleware.py`**: new `client_context_prompt`, a `@dynamic_prompt` reading `request.state.get("client_context")` and appending it to the existing system prompt when present — same shape as `today_prompt` (line 47-51).
- **`app/agent/multi_agent/portfolio_agent.py`, `finance_agent.py`, `rag_agent.py`**: add `client_context_prompt` to the middleware list; extend each `create_agent(...)` call with a `state_schema` that includes `client_context: Optional[str]` so the field crosses the subgraph boundary (per the documented handoffs pattern — without this, `request.state` inside these three specialists never sees the parent graph's `client_context`).
- **`app/api/routers/copilot.py`**: no change. `thread_id` already flows through to the graph unmodified; no AG-UI-context handling needed.

## Data flow

1. User on `/clients` clicks a client (id 12) → navigates `/clients/12`.
2. `ClientWorkspace` fetches `GET /data/clients/12/summary` for the header; mounts `CopilotChat` with `threadId="clients_12"`.
3. User asks a question (no need to name the client) → request hits `/copilot/market-desk` with `thread_id="clients_12"`.
4. `load_client_context` extracts `12` from the thread id, loads the client row, sets `state.client_context`.
5. `supervisor` routes to the relevant specialist (e.g. `portfolio_agent` for a holdings question).
6. That specialist's `client_context_prompt` middleware appends the client blurb to its system prompt before the model call; the model answers already knowing which client is active.
7. Response streams back to `CopilotChat`; tool/specialist activity streams to `DeskActivityRail` in the Intelligence column — identical mechanics to Recherche today.
8. Reloading `/clients/12` later, or navigating away and back, resumes the same `clients_12` thread via the checkpointer.

## Error handling

- `GET /data/clients/{id}/summary`: unknown `client_id` → 404. A ticker whose live price fetch fails → that position is reported in `unpriced_tickers`, excluded from `totals`'s math; `totals` is only `None` when *every* held ticker is unpriced (degrade, don't fail the whole response — unlike `concentration_screen`, which is an agent tool needing full consistency, this is a view that should still render what it can).
- Client with zero holdings → `totals: None`, `positions: []`, `unpriced_tickers: []` — frontend shows "Aucune position" (same copy `ClientsList` already uses).
- `load_client_context`: thread id not matching `clients_\d+` (Recherche/Classic threads) → `client_context=None`, no behavior change from today. Thread id matching the pattern but the client was deleted since → also `None`; the specialist answers generically rather than crashing.
- Frontend `/clients/:id` with a 404 from the summary endpoint, or a non-numeric id → inline error banner (same pattern `ClientsList`'s existing `.catch()` uses) with a link back to `/clients`.

## Testing

**Backend (pytest):**
- `load_client_context`: `thread_id="clients_12"` + existing client → correct formatted string; nonexistent id → `None`; `thread_id="desk_xyz"` (no match) → `None`.
- `client_context_prompt`: state with `client_context` set → appended to the system prompt; unset → prompt unchanged (same style as the existing `today_prompt` test).
- `GET /data/clients/{id}/summary`: client with holdings and mocked live prices → correct `totals`; zero holdings → zero-ed response, no crash; unknown id → 404; one ticker's price fetch raising → that ticker in `unpriced_tickers`, `totals` still computed from the rest.
- Integration: `build_multi_agent_app` invoked with `thread_id="clients_12"`, asserting the routed specialist's model call received a system prompt containing the client's name (mock the model, inspect the captured prompt — same technique existing multi-agent tests already use).

**Frontend (Vitest):**
- `ClientsPage.test.tsx` (new, replaces the old `ClientsList`-under-`DataPage` coverage): list renders, row click navigates to `/clients/:id`.
- `ClientWorkspace.test.tsx` (new): renders header from the mocked summary fetch; `CopilotChat` receives `threadId="clients_<id>"`; `DeskActivityRail` portals through `useIntelligenceSlot` (mock `useAgent`, same technique as `DeskView.test.tsx`).
- `DataPage.test.tsx` (existing): update — only `documents`/`import` tabs remain.
- `App.test.tsx` (existing): add routing assertions for `/clients` (list) and `/clients/:id` (workspace).

**Live QA (one grounded pass):** click a client from the list, ask a portfolio question without naming the client, confirm the agent answers using the injected context; reload the page and confirm the conversation resumes; navigate back to the list and into a different client, confirm no context leakage between the two; confirm `/data` still works with just Documents + Import.

## Out of scope (explicitly, for this chantier)

- Editing a client's profile from this view (stays via `/data` Import).
- Multi-client comparison view.
- Surfacing `watchlists` or `transactions` history in the workspace (tables exist in `customers.db`, not exposed here — future increment if wanted).
- Rapports and Briefing sections (each its own future chantier/spec).
