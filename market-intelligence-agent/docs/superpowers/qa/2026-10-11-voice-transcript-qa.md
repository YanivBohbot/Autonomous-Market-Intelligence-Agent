# Live QA - Research voice chat transcript + legacy UI removal (2026-10-11)

Run against the branch backend (`:8001`, worktree venv) and Vite (`:5175`, proxying to `:8001`). No browser automation was available: text/API rows were driven with `POST /stream` + `POST /approve` using fresh `qa-*` thread ids and grounded against the LangGraph checkpoint (`data/checkpoints.db`, tool messages) and `customers.db`. Voice and purely visual checks are marked "A faire par l'utilisateur" and are covered step by step in `docs/QA-GUIDE.md`.

The mic badge was intentionally not built (plan YAGNI), so no row checks for it.

Specialist names come from the SSE `node` events (`<specialist>` node right before `supervisor > finalize_turn`); tool names from the `model` node's `tool_calls`.

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Voice transcript | A faire par l'utilisateur | Needs mic + WebRTC. Grounding half verified through typed twin (row 3): `concentration_screen` returns 24 breach entries / 18 distinct clients. See QA-GUIDE section 1. |
| 2 | Voice HITL | A faire par l'utilisateur | Needs mic. Typed twin of the flow proven in row 12 (interrupt + reject). See QA-GUIDE section 2. |
| 3 | Typed concentration | PASS | Nodes: `supervisor > model['concentration_screen'] > tools > model > portfolio_agent`. Answer lists 18 distinct clients (Robert Hayes GOOGL 68.19%, Thomas Reed NVDA 65.70%, James Whitaker NVDA 59.47%, ...) = exactly the 18 distinct `label`s in the checkpointed `concentration_screen` ToolMessage (`breach_count` 24, `screened_count` 25). All names exist in `customers.db`. |
| 4 | RAG | PASS | Nodes: `model['search_knowledge_base'] > tools > rag_agent`. Answer cites `[Source: Amazon-2024-Annual-Report.pdf, page 7]` (4 identical Source tags in the tool output). |
| 5 | Market data | PASS (note) | Nodes: `model['yfinance_get_ticker_info'] > tools > finance_agent`. Checkpointed tool output: `currentPrice 336.64` (previousClose 340.42); display envelope `ticker_info ... current_price 336.64`. `/data/briefing/watchlist` AAPL price = 336.6400146 (same). Note: the streamed text is only "Here's AAPL's current quote."; the number is shown in the ticker_info card (UI), so a text-only client does not display the price. Visual check of the card is for the user. The backend log only records HTTP lines, not tool output, so the checkpoint was used instead of the log. |
| 6 | Typed HITL approve | PASS | `write_file` -> SSE `interrupted` (`next_step: filesystem_agent`); `/approve approved:true` -> `completed`, "The file `qa-note.txt` has been successfully created". `data/workspace/qa-note.txt` existed (5 bytes) and contained `hello`; deleted afterwards. |
| 7 | Voice-to-text continuity | A faire par l'utilisateur | Needs a prior voice turn. Typed proxy (same thread as row 3, "summarize that in one sentence") answered with the concentration result (Robert Hayes, Thomas Reed, NVDA/GOOGL/GS); note it was routed to `rag_agent` (supervisor choice), but history carried through. See QA-GUIDE section 7. |
| 8 | Briefing | PASS (API) + user (visual) | All Briefing endpoints return 200 through :5175: `/data/market-ticker` (2.7s), `/data/briefing/indices`, `/sectors`, `/watchlist`, `/movers`, `/news` (2.6s), `/client-alerts` (24 breaches, same as row 3), `/narrative` (2.0s). Observation: the aggregate `/data/briefing` took 10.4s warm and the first call timed out at 60s (cold yfinance); the page uses the split endpoints. Console errors / layout: user. |
| 9 | Clients and Reports | PASS (API) + user (visual) | `/data/clients` 200 (25 clients with holdings), `/data/clients/1/summary` 200, `/data/clients/1/report` 200, `POST /data/clients/1/report/generate` 200 `{"filename":"yaniv-bohbot-portfolio-brief-2026-10-11.xlsx"}` (file removed afterwards). Clicking/opening a workspace: user. |
| 10 | Data | PASS (API) + user (visual) | `/data/clients` 200, `/data/documents` 200 (5 PDFs: 2026-Annual-Report-Web, Amazon-2024, Goldman-Sachs-GS-2025, NVIDIA-NVDA-2026, Tesla-TSLA-Q2-2026). No import performed. |
| 11 | Removed surfaces | PASS (+ user visual) | `/voice/x/transcript` -> 404 on :8001 and via :5175. `netstat` shows nothing listening on :8080. `/classic`: router has no such route (`frontend/src/App.tsx`), covered by `frontend/src/App.test.tsx` "no longer serves the classic chat at /classic" (no chat input, no voice toggle). Visual check of /classic: user. |
| 12 | Backend API | PASS | `GET /health` -> `{"status":"ok"}`. `POST /stream` "Send an email to Margaret Collins ..." (no address) -> email_agent asked for the address, no tool call (by design, recipient must be an explicit `clients.email`). With `margaret.collins@example.com`: `model['send_email','send_email'] > __interrupt__`, SSE `interrupted` (`next_step: email_agent`). `POST /approve approved:false` -> `status: completed`, "email sending request was rejected". Never approved: no SES send. Observation: the model emitted `send_email` twice in the same batch for one request (one reject cancels both; if approved it could send two emails). |
| 13 | Browser specialist | PASS | `model['browser_navigate'] > tools > browser_agent`; answer: The page title is "Example Domain." |
| 14 | Memory specialist | FAIL (recall wording) | Save leg PASS: `model['save_memory'] > __interrupt__` (memory_agent), approve -> "I've saved your preferred report format as Excel." Recall leg with the exact brief wording "What is my preferred report format?": new thread -> `memory_agent` but NO tool call, answer "I currently don't have any information saved..." (reproduced 2/2 on fresh threads); same thread -> routed to `rag_agent`, answered "Excel" from chat context with no tool. With "What do you remember about me? List my saved memories." -> `model['list_memories'] > memory_agent`, "your preferred report format is Excel" (store is cross-thread, value persisted). Root-cause hypothesis: `MEMORY_SYSTEM_PROMPT` says to call `list_memories` "at the start of complex tasks" but not to always check memory before answering that nothing is known; gpt-4o-mini answers from priors. Suggested fix (not applied): instruct the memory agent to call `list_memories`/`recall_memory` before answering any recall question; consider supervisor guidance so recall questions route to `memory_agent`. |
| 15 | Routing summary | PASS | portfolio_agent: row 3; rag_agent: row 4; finance_agent: row 5; filesystem_agent: row 6; browser_agent: row 13; memory_agent: row 14 (save + list recall); email_agent: row 12 (outside the 3-6/13/14 range, which contains no email request, but proven in the same QA pass). All 7 specialists routed. |

## Environment notes
- Thread ids used: `qa-r3-23490`, `qa-r4-23490`, `qa-r5-23490`, `qa-r13-23490`, `qa-r6-*`, `qa-r12-*`, `qa-r14*-*`, `qa-r14d-*` (never `clients_*`).
- The memory store is `InMemoryStore` (volatile): restarting the backend loses saved facts, so row 14 must save and recall within one server run.
- Backend log has only HTTP/pydantic warning lines (`PydanticSerializationUnexpectedValue ... RoutingDecision`, harmless serializer warnings from the supervisor structured output); no tracebacks seen.

## Fix commits
None (failures are recorded for the controller).

## Re-run after fix 9121e22 (row 14)

Root cause: `MEMORY_SYSTEM_PROMPT` never told the memory specialist to check saved facts before answering a question about the user's own preferences, and the supervisor's `memory_agent` description only matched "remember…" phrasing. Fix: prompt-only (commit 9121e22) + 2 prompt-contract regression tests (39 passed in the memory/supervisor/system-prompt test files).

Live re-check (backend restarted on :8001; note the store is in-memory, so the fact was re-saved after restart):
- "Remember that my preferred report format is Excel" → `save_memory` → `interrupted` → `/approve` approved:true → "I've saved your preferred report format as Excel."
- New thread, "What is my preferred report format?" → `memory_agent` + `list_memories` → "Your preferred report format is Excel." (2/2 runs)
- Routing control: "Which clients have more than 30 percent of their portfolio in one stock?" → still `concentration_screen` with real client names (Robert Hayes GOOGL 68.19%, Thomas Reed NVDA 65.70%, …).

**Row 14: PASS** (after fix).

Known limitation surfaced (pre-existing, out of scope): the long-term memory store is in-process (`InMemoryStore`) locally, so saved facts are lost on backend restart.
