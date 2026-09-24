# Multi-Agent API Cutover — Design

## Context

`app/agent/multi_agent/` (supervisor + 7 specialist subgraphs: rag, finance,
crm, memory, filesystem, browser, email) was built and live-QA'd standalone
over the course of 2026-09-15 — never wired into the FastAPI layer. It now has
full tool-domain parity with the old single-agent graph (`app/agent/graph.py`)
and has been exercised end-to-end (real LLM + real MCP calls) for every
specialist, including the HITL approve/reject cycle for side-effect tools.

This spec covers wiring it into the actual API (`/stream`, `/approve`) so real
traffic — the Streamlit UI and the React dev console — flows through it
instead of the single-agent graph.

## Decision: hard replace, no toggle

The single-agent graph is retired from the API entirely. `app/agent/graph.py`
stays in the repo (several of its functions — `approval_node`,
`record_question`, `route_after_approval` — are imported and reused verbatim
by every specialist), but `server.py`'s lifespan no longer builds or serves
it. No env-var switch between architectures.

## Investigation: how LangGraph streaming behaves with nested subgraphs

Spiked empirically against the real compiled multi-agent graph before
finalizing this design (not assumed):

- **Without `subgraphs=True`**, `astream(..., stream_mode=["updates","messages"])`
  only surfaces **top-level** node names (`record_question`, `supervisor`,
  `finance_agent`, …) — a whole specialist's internal run (its own
  agent/approval/tools loop) collapses into a single lump `updates` event, and
  **real per-token streaming from inside a specialist is not surfaced at all**
  (measured: 1 stray token vs. 51 real tokens with `subgraphs=True` on an
  identical live finance question). This would silently kill the live-typing
  UX the current single-agent graph provides.
- **With `subgraphs=True`**, the astream yields 3-tuples
  `(namespace, mode, chunk)` instead of 2-tuples. Inner node names surface
  correctly under a namespaced tuple like `('finance_agent:<uuid>',)` — e.g.
  `agent`, `approval`, `tools` — and real per-token streaming works, tagged
  with `meta["langgraph_node"] == "agent"` (or `"synthesize"` for `rag_agent`,
  whose final node has that name instead).
- `snapshot.next` on the **parent** graph, when an interrupt fires inside a
  specialist, reports the specialist's name as the paused node (e.g.
  `('finance_agent',)`), never `('approval',)` — confirmed via earlier live
  QA of `memory_agent`'s HITL flow. This means the old
  `"approval" in snapshot.next` check can never match in the new graph.
- `approve.py` was checked and requires **no changes** — it already only
  checks `snapshot.next` for truthiness generically, and resumes via
  `Command(resume=decision)` regardless of which node is paused.
- The React frontend's `ActivityRail.tsx` has a `NODE_CONFIG` map for
  known node names but falls back to a generic uppercase badge for unknown
  ones — new node names (`supervisor`, `agent`, `synthesize`) won't break
  rendering, just show a less polished label. Streamlit's `app/ui/app.py`
  doesn't consume the `node` SSE event at all, so it's entirely unaffected.

## Changes

### `app/api/server.py`
Replace the `build_agent_app` import and lifespan call with
`build_multi_agent_app` (same `(checkpointer, store)` signature). Delete the
now-unused `build_agent_app` import.

### `app/api/routers/stream.py`
1. Add `subgraphs=True` to the `agent_app.astream(...)` call.
2. Update the loop to unpack `namespace, mode, chunk` (3-tuple) instead of
   `mode, chunk` (2-tuple). `namespace` isn't otherwise used by the SSE
   contract — the emitted `node` event still carries just the bare node name
   (e.g. `"agent"`, `"approval"`, `"tools"`, `"supervisor"`), not the
   namespaced path, so the event payload shape is unchanged.
3. Replace the token-streaming condition
   `meta.get("langgraph_node") == "generate"` with membership in a module
   constant `_STREAMABLE_NODES = {"agent", "synthesize"}`.
4. Replace `if snapshot.next and "approval" in snapshot.next:` with
   `if snapshot.next:` — interrupt is the only pause mechanism left in the
   graph, so truthiness alone is correct and simpler.
5. `_tool_names_from_update` / `_screenshot_urls_from_update` /
   `_screenshot_filename`: no logic changes — they already operate on
   whatever `update["messages"]` dict they're handed, and inner-node updates
   carry the same message shapes as before.

### `app/api/routers/approve.py`
No changes.

### `tests/unit/test_stream.py`
`_FakeAgentApp.astream` currently hardcodes the 2-tuple, no-`subgraphs`
contract. Rewrite it to accept `subgraphs=True` and emit 3-tuples
`(namespace, mode, chunk)` (namespace can be a fixed dummy tuple like
`()` for top-level or `("finance_agent:x",)` for nested, matching what the
tests need to assert). Update all 6 existing tests' fixture data to use the
new node names (`"agent"` instead of `"generate"`, specialist names instead
of `"rag"`/`"grader"`) and the new interrupt semantics. The existing
`test_stream_does_not_emit_interrupted_for_non_approval_pause` test encodes a
distinction (pause at `"tools"` vs pause at `"approval"`) that no longer
exists in the new graph — repurpose it to assert the new invariant instead:
`snapshot.next` non-empty always means interrupted, whatever specialist name
it names.

### `frontend/src/components/ActivityRail.tsx` (optional, cosmetic)
Add a few `NODE_CONFIG` entries for the new common node names
(`supervisor`, `agent`, `synthesize`) so the activity rail shows a
recognizable label instead of the generic fallback. Not required for
correctness — purely a polish item, done only if time permits after the
functional cutover is verified.

## Error handling

No new error-handling paths are introduced. `ToolNode(handle_tool_errors=True)`
already prevents thread-poisoning inside every specialist (same pattern as
the old graph). The per-specialist error-recovery prompt gap (no
`ERROR_RECOVERY_PROMPT`-equivalent short-circuit per specialist) remains a
known, explicitly deferred gap — not addressed by this cutover.

## Testing / verification plan

1. Update `test_stream.py` per above; full `uv run pytest tests/` green.
2. Manual smoke test: start the real FastAPI server (`uv run uvicorn
   app.api.server:app --reload`) and the React dev console, and drive one
   real turn per specialist through the actual `/stream` + `/approve`
   endpoints (not direct `ainvoke` in a script) — at minimum: a finance
   question, a CRM question, a memory-save (approve), and one RAG question —
   confirming live token streaming, correct activity-rail entries, and a
   real approval pause/resume round-trip over HTTP.
3. Confirm the Streamlit UI (`uv run streamlit run app/ui/app.py`) still
   completes a basic turn without error (it doesn't render node events, so
   this is mainly a regression check on token/interrupted/done/error framing).

## Non-goals (unchanged from the earlier multi-agent design spec)

- Per-specialist error-recovery prompt.
- Multi-hop compound cross-domain questions in one turn.
- Voice mode (`app/voice/graph.py`) — untouched, still serves the old
  single-agent node functions directly (it already imports them, not
  `build_agent_app` itself, so it's unaffected by this cutover either way).
- `docs/TOOLS.md` — not triggered, no tool added/renamed/removed.
