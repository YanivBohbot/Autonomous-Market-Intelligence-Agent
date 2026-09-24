# CopilotKit foundation ("Market Desk"), design

**Date:** 2026-09-24
**Status:** approved in brainstorming, awaiting spec review
**Program:** sub-project 1 of 5 in the CopilotKit program:
1. foundation (this spec);
2. rich displays;
3. exports;
4. imports;
5. data view.

The program also covers extra ideas: watchlist alerts, what-if, morning brief, company comparison, conversation history, cost per question and feedback.

## Goal

The React console (`frontend/`) gets a CopilotKit-based **Market Desk** mode wired to the multi-agent graph. It gives the advisor three things:

- a streaming chat;
- a live activity rail showing which specialist and which tools are working;
- interactive approval cards (approve / edit / reject) for every side-effect tool.

The server side stays **100% Python**. There is no CopilotKit runtime, neither Node nor Python.

## Decisions (from brainstorming)

1. **Agent: the multi-agent graph** (`app.agent.multi_agent`).
   - It shows specialists.
   - It already uses the official `HumanInTheLoopMiddleware`.
   - It is not used by prod.
   - The single-agent graph (prod, Streamlit, voice, `/stream`, `/approve`) is untouched.
2. **UI: option C.**
   - CopilotKit's prebuilt `CopilotChat` in the center, plus our `ActivityRail`, adapted, on the right.
   - Rich renders (approval cards now; tables and charts in sub-project 2) go through CopilotKit's render hooks.
   - If this proves limiting, we fall back to a fully prebuilt layout.
3. **No runtime.**
   - The browser uses CopilotKit v2 with `@ag-ui/client` `HttpAgent` and talks AG-UI directly to our FastAPI.
   - The Python CopilotKit runtime (`packages/runtime-python`) was rejected: it is not on PyPI, it requires a CopilotKit Intelligence cloud API key, and it duplicates our checkpointer and store.
4. **Endpoint path: `POST /copilot/market-desk`**, with AG-UI agent id **`market_desk`**.
5. **Opt-in:** a new setting `COPILOT_ENABLED` (default `False`; `true` in local `.env`). Prod does not expose the endpoint until decided.
6. **Classic mode is kept.** A header toggle switches between Market Desk (default) and Classic (the current `/stream` UI, unchanged).

## Spike evidence (2026-09-24, throwaway)

- **Versions:** `ag-ui-langgraph` 0.0.45 and `copilotkit` 0.1.96 (PyPI), `@copilotkit/react-core` 1.73.3 (v2 entry), `@ag-ui/client` 1.0.0.
- **Server:** `add_langgraph_fastapi_endpoint(app, LangGraphAgent(name=..., graph=..., emit_subagent_events=True, emit_interrupt_outcome=True, enable_legacy_on_interrupt_event=False), path=...)`.
- **Streaming:**
  - text streams through `TEXT_MESSAGE_*`;
  - `STEP_STARTED` names graph nodes (`supervisor`, `finance_agent`, middleware nodes);
  - tools appear as `TOOL_CALL_START/ARGS/END/RESULT`;
  - `RUN_FINISHED.usage` carries token counts.
- **Interrupts:**
  - `RUN_FINISHED.outcome = {type: "interrupt", interrupts: [{id, reason: "langgraph:interrupt", metadata: {langgraph: {raw: {action_requests, review_configs}}}}]}`.
  - In React, `useInterrupt({agentId: "market_desk", render})` receives it; `resolve({decisions: [...]})` resumes the graph. Reject was verified end to end in a real browser.
- **Gotchas:**
  - Every CopilotKit hook and component needs `agentId="market_desk"`, otherwise it fails with "Agent 'default' not found".
  - The supervisor's structured-output JSON (`{"next": ...}`) is streamed as a text message and must be hidden.

## Server design (Python)

### `app/api/routers/copilot.py` (new)

- Exposes `POST /copilot/market-desk` as an AG-UI SSE endpoint for the multi-agent graph.
- The multi-agent graph needs the app's checkpointer, which is only created in `lifespan`, so the graph is built there. `add_langgraph_fastapi_endpoint` wants the graph at registration time, so the router does not call it directly. Instead, the handler:
  - reads a `LangGraphAgent` stored on `app.state.market_desk_agent`;
  - streams its events with the same encoder `add_langgraph_fastapi_endpoint` uses.
- The implementer reads `ag_ui_langgraph`'s endpoint helper and mirrors it: `RunAgentInput` body, `EventEncoder(accept=...)`, `StreamingResponse`.
- `LangGraphAgent(name="market_desk", graph=..., emit_subagent_events=True, emit_interrupt_outcome=True, enable_legacy_on_interrupt_event=False)`.
- A handler call before startup finished (no agent on `app.state`) returns 503.

### `app/api/server.py`

- In `lifespan`, when `settings.COPILOT_ENABLED` is true, build `build_multi_agent_app(checkpointer, store)` and store the `LangGraphAgent` on `app.state`.
- Include the router only when enabled. When disabled, the path returns 404.
- All other routers are unchanged.

### `app/core/config.py`

- `COPILOT_ENABLED: bool = False`.
- Document it in `CLAUDE.md`'s optional-keys list.

### Hide the supervisor's routing output

- `supervisor._router` is configured with the LangGraph `nostream` tag, so its structured-output tokens are never emitted as chat text.
- The routing decision remains visible through `state.next_agent` and `STEP_STARTED`.
- No behavior change.

### Dependencies

- Add `ag-ui-langgraph` to `pyproject.toml` / `uv.lock`, the local dev only.
- `requirements.agentcore.txt` is **not** changed: the endpoint is off in prod.

## UI design (React, `frontend/`)

### Dependencies

- Add `@copilotkit/react-core` (v2 entry) `1.73.3`, `@ag-ui/client` `1.0.0` and `zod` `^3.25`.
- React stays 18; the CopilotKit peer range is `^18 || ^19`.
- Import `@copilotkit/react-core/v2/styles.css`.

### Layout

- `App.tsx` gets a `mode` state (`"desk" | "classic"`, default `"desk"`, remembered in `localStorage`).
- The existing Classic tree stays as is.
- `Header` gets a Market Desk / Classic toggle.
- The Market Desk layout:
  - `<CopilotKit agents__unsafe_dev_only={{ market_desk: agent }} threadId={threadId}>`, where `agent` is an `HttpAgent` pointing at `/copilot/market-desk` through the Vite proxy (add the `/copilot` proxy entry next to the existing ones);
  - `CopilotChat agentId="market_desk"` in the center;
  - `DeskActivityRail` on the right.
- **New session** creates a new `threadId`, the same behavior as today.

### Live activity (`src/desk/activity.ts` + `DeskActivityRail.tsx`)

- **A pure mapper `toActivity(event)`:**
  - `STEP_STARTED` for a specialist node (the 7 names) becomes a specialist badge: RAG, FINANCE, PORTFOLIO, BROWSER, EMAIL, FILES, MEMORY;
  - `TOOL_CALL_START` / `TOOL_CALL_END` become a tool row with its duration;
  - `RUN_FINISHED` with an interrupt outcome becomes an "awaiting approval" row;
  - `RUN_FINISHED` becomes a "done" row with total tokens from `usage`;
  - middleware and internal node steps are ignored.
- **`DeskActivityRail`** subscribes to the `market_desk` agent (`useAgent({agentId}).agent.subscribe(...)`) and renders the list, reusing the existing badge and tag styling.

### Approval cards (`src/desk/ApprovalCards.tsx`)

- `useInterrupt({agentId: "market_desk", render})` renders one card per `action_request` in `interrupt.metadata.langgraph.raw.action_requests`.
- Presentation per tool:

  | Tool | Fields shown / editable |
  |---|---|
  | `send_email` | recipient, subject, body |
  | `write_file` | path, content |
  | `save_memory` | key, value |
  | any other | raw JSON args (read-only, approve / reject only) |

- **Buttons:**
  - **Approve** gives `{type: "approve"}`;
  - **Edit** makes the fields editable, then **Send edited** gives `{type: "edit", edited_action: {name, args}}`;
  - **Reject** takes an optional reason and gives `{type: "reject", message}`.
- With N action requests, the user decides each one; once all are decided, `resolve({decisions: [...]})` is called with the decisions in request order.
- The allowed buttons follow `review_configs[].allowed_decisions`.
- Labels are in English, like the rest of the console.

### Unchanged

- Classic mode, `VoicePanel` (single-agent), Streamlit, and the Tailwind setup.

## Testing

**Python (pytest, no OpenAI calls, fake models as in the existing multi-agent tests):**

- **Enable flag:**
  - with `COPILOT_ENABLED=false`, `POST /copilot/market-desk` returns 404;
  - when enabled with a built agent, it streams AG-UI events.
- **End-to-end SSE with a fake finance answer:** the events include `RUN_STARTED`, `TEXT_MESSAGE_CONTENT` and `RUN_FINISHED`.
- **Email request with a fake model and a fake `send_email`:**
  - the first run ends with an interrupt outcome whose `action_requests[0].name == "send_email"`;
  - resuming with `forwardedProps.command.resume = {decisions: [{type: "reject"}]}` does not call the tool.
- **Supervisor:** the router LLM carries the `nostream` tag.

**Frontend (Vitest + Testing Library):**

- `toActivity` mapping for each event type, including ignored middleware steps.
- **Approval cards:**
  - `send_email`, `write_file` and `save_memory` show the right fields;
  - Approve, Edit→Send edited and Reject produce the exact decision objects;
  - multiple requests produce one decision each, in order;
  - allowed decisions hide buttons.
- The mode toggle switches the layout and persists.

**Live, one pass at the end:** a Playwright-driven browser run.
- A portfolio question: the activity shows PORTFOLIO and its tools, and the answer streams.
- An email request: the card shows, **Reject** is clicked, and nothing is sent.

## Out of scope (later sub-projects)

- Portfolio tables, charts, screenshots in chat, RAG source cards (sub-project 2).
- Report and Excel exports (3), uploads (4), data view (5).
- The extra ideas, including conversation history and a cost display beyond the token count.
- Wiring the endpoint into prod / AgentCore, auth for the endpoint, `selfManagedAgents`.
