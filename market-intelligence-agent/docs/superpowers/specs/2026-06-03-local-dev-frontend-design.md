# Local Dev Test Frontend — Design

**Date:** 2026-06-03
**Status:** Approved (design); pending implementation plan
**Owner:** Yaniv Bohbot

## Purpose

Provide a polished, modern web frontend for **local development testing** of the
Market Intelligence Agent. It replaces the day-to-day testing role of the existing
French-language Streamlit UI (`app/ui/app.py`) with a nicer, more capable dev tool.
This is a local-dev artifact only — it does **not** change anything about the
deployed AWS (AgentCore) stack.

### Goals
- Exercise the full agent loop from a browser: chat with token streaming, the
  human-in-the-loop (HITL) approve/reject flow, and voice.
- Give a debug view of which LangGraph node / tool is running ("Agent activity").
- Look genuinely good — a dark "fintech terminal" aesthetic, not generic AI-chat.

### Non-goals
- No changes to the production AWS deployment, IaC, or AgentCore Runtime.
- Not a replacement for the deployed product UI; it is a developer test harness.
- No auth — local dev only, runs against `localhost`.

## Architecture

A new **React + Vite + TypeScript + Tailwind** single-page app lives in
`market-intelligence-agent/frontend/`. It talks to the existing FastAPI backend
on `:8000`. The Vite dev server (`:5173`) proxies API paths to `:8000` so there
are no CORS issues during development.

```
[Vite dev :5173]  --proxy-->  [FastAPI :8000]  -->  LangGraph agent
   React SPA                    POST /stream  (SSE)
                                POST /approve
                                GET  /health
                                POST /livekit/token --> LiveKit Cloud (voice)
```

### Backend API contract (already exists)
- `POST /stream` — SSE. Request `{ query: str, thread_id: str }`. Events:
  - `token` → `{ token: str }` (incremental assistant text)
  - `interrupted` → `{ action: str, next_step: str }` (HITL gate hit)
  - `done` → `{}`
  - `error` → `{ error: str }`
- `POST /approve` — Request `{ thread_id: str, approved: bool }`. Response
  `{ response: str, status: "completed"|"interrupted", next_step: str|null }`.
  A single global verdict resumes the whole interrupted batch. On `interrupted`
  status, another action requires approval (chained interrupts).
- `GET /health` — `{ status: str, version: str }`.
- `POST /livekit/token` — Request `{ identity: str, room: str }`. Response
  `{ token: str, url: str, room: str }`. Only mounted when the `livekit` SDK is
  installed (it is, locally).

## Required backend change (additive)

The current `/stream` emits no signal of which graph node/tool is running, so the
"Agent activity" debug view is impossible without a small addition.

**Change `app/api/routers/stream.py`** to consume LangGraph's multi-mode stream
`stream_mode=["updates", "messages"]`. With multiple modes the async iterator
yields `(mode, chunk)` tuples:
- `mode == "messages"` → `chunk == (token, meta)` — existing token logic, unchanged.
- `mode == "updates"` → `chunk == { node_name: state_update }` — emit a new SSE
  event `node` → `{ node: str, tool_calls: [str]|null }` as each node fires.
  `tool_calls` is populated from the last `AIMessage.tool_calls` when the node is
  `generate` and it produced tool calls (so the activity rail can name the tools).

This is purely additive: the `token` / `interrupted` / `done` / `error` events keep
their exact shapes, and the existing Streamlit UI (which ignores unknown events)
continues to work. The `interrupted` / `done` snapshot logic at the end of the
handler is unchanged.

## Frontend components

All under `frontend/src/`.

| Unit | Responsibility | Depends on |
|---|---|---|
| `App.tsx` | Layout shell: two-column (chat main + collapsible "Agent activity" rail), header, voice toggle. | all below |
| `hooks/useChatStream.ts` | POST `/stream`, parse the SSE byte stream, accumulate tokens, surface `interrupted`, `node`, `done`, `error`. Exposes `{ messages, streaming, pendingAction, activity, send }`. | `lib/sse.ts` |
| `lib/sse.ts` | Pure function: parse an SSE chunk buffer into `{event, data}` records. Unit-tested. | — |
| `components/ChatPane.tsx` | Render message list, markdown, streaming caret, empty state. | — |
| `components/ApprovalCard.tsx` | On `interrupted`: show pending action, Approve/Reject buttons → POST `/approve`; handle chained interrupts and disable chat while pending. | `lib/api.ts` |
| `components/ActivityRail.tsx` | Live timeline of `node` events + named tool calls; color-coded; auto-scroll. | — |
| `components/Header.tsx` | Health dot (polls `/health` every ~10s), version, `thread_id` display, **New session** button, editable API-base field. | `lib/api.ts` |
| `components/VoicePanel.tsx` | Port the LiveKit flow with the `livekit-client` npm package: Connect/Disconnect, enable mic, attach + autoplay agent audio track, status + log. Unique room per connect (same rule as today). | `livekit-client`, `lib/api.ts` |
| `lib/api.ts` | Thin fetch wrappers + API base resolution (Vite proxy in dev). | — |

### State / data flow
- `thread_id` generated client-side as `web_session_<uuid8>`; **New session** mints
  a fresh one and clears messages. Voice uses its own room/thread (unchanged rule).
- Chat is disabled while `pendingAction` is set (mirrors Streamlit behavior).
- `useChatStream` keeps an `activity` array; `ActivityRail` renders it. Cleared per
  new user turn (with a thin separator so prior turns remain visible if desired).

### Error handling
- Connection error / non-2xx on `/stream` or `/approve` → inline error bubble +
  red health dot; chat re-enabled so the user can retry.
- SSE `error` event → render `error` text as an error bubble, end the turn.
- Voice errors → surfaced in the VoicePanel log, never crash the app.

## Design language
Dark "fintech terminal" theme via Tailwind. Restrained palette: slate/zinc base,
one signal-green accent (live/positive), amber (awaiting approval), red
(reject/errors). Monospace for tickers and tool names. Smooth streaming caret and
activity-rail enter animations. Avoid generic AI-chat aesthetics. The
frontend-specialist agent owns the visual execution.

## Running locally
- `frontend/README.md` + npm scripts (`dev`, `build`, `test`).
- Run order: `uv run uvicorn app.api.server:app --port 8000 --reload` →
  `npm run dev` (in `frontend/`) → open `http://localhost:5173`.
- Add this recipe to the project `CLAUDE.md` Commands section.
- Voice additionally requires the LiveKit worker:
  `uv run python -m app.voice.worker dev`.

## Testing
- **Vitest + React Testing Library** for the two pieces with real logic:
  - `lib/sse.ts` parser (multi-event buffers, split chunks, unknown events).
  - `ApprovalCard` state machine (approve → completed, reject, chained interrupt).
- Manual smoke against a live backend for streaming, activity rail, and voice.

## Implementation plan (phased)
1. Backend: additive `node` SSE event in `stream.py` (+ test).
2. React scaffold (Vite/TS/Tailwind) + chat token streaming (`useChatStream`, `sse.ts`, `ChatPane`).
3. HITL `ApprovalCard` (+ chained interrupts).
4. `ActivityRail` + `Header` (health/session controls).
5. `VoicePanel` (LiveKit).

After the plan is written, the **frontend-specialist agent** implements it.
