# Single-agent graph on `create_agent` + middleware — design

**Date:** 2026-10-02
**Status:** approved, not yet implemented
**Scope:** `app/agent/graph.py`, `app/agent/nodes/generate.py`, `app/voice/graph.py`, `app/voice/hitl.py`, `app/api/routers/approve.py`, `app/api/routers/stream.py`, plus new files

## Goal

The multi-agent specialists already moved to `create_agent` + official
middleware (`2026-09-24-multi-agent-create-agent-design.md`), explicitly
deferring the single-agent graph ("not touched... blast radius limited").
This spec closes that gap: rebuild the single-agent graph the same way, so it
shares `app/agent/middleware.py`'s `base_middleware()` (today: `today_prompt`,
`summarization()`, `mask_credit_cards()`, `SensitiveDataGuard`,
`ModelCallLimitMiddleware`, `model_fallback()`, `model_retry()`,
`tool_errors_to_messages`) instead of duplicating pieces of it by hand.

This is **not** fixing a non-conformance — a same-session architecture review
against current official LangGraph docs confirmed the existing raw
`StateGraph` + dynamic `interrupt()` pattern is fully conformant. The
motivation is architectural consistency and closing two gaps the review and a
follow-up memory/fallback review found specific to this graph:

1. No summarization/trimming of conversation history (unlike the multi-agent
   specialists), so a long-lived SQLite-backed thread's context grows
   unbounded.
2. Model-call retry/fallback exist today only as a hand-rolled
   `.with_retry()`/`.with_fallbacks()` in `generate.py` (added earlier this
   session) instead of the shared `model_retry()`/`model_fallback()`
   factories the specialists use.

## Decisions (from brainstorming)

1. **Error recovery prompt is preserved.** `generate.py`'s current behavior —
   routing to `ERROR_RECOVERY_PROMPT` instead of the normal system prompt when
   the last message is an error `ToolMessage` — is kept via a new custom
   `AgentMiddleware` (not dropped in favor of the specialists' simpler
   "`ToolErrorMiddleware` + normal prompt" handling).
2. **Atomic-batch reject is dropped.** The current `approval_node`'s rule
   ("any reject cancels every tool call in the batch, read-only included") is
   **not** replicated. The official `HumanInTheLoopMiddleware` does not
   support it — verified in
   `.venv/Lib/site-packages/langchain/agents/middleware/human_in_the_loop.py:513-515`:
   tool calls outside `interrupt_on` are marked "auto-approved" independently
   of the decision on any interrupted call in the same batch. The
   multi-agent specialists already have this weaker-but-standard semantics;
   single-agent adopts the same for consistency rather than adding a custom
   middleware to preserve the stronger rule.
3. **The external `/approve` HTTP contract does not change.**
   `ApproveRequest.approved: bool` stays as-is; `approve.py` translates
   internally to `Command(resume={"decisions": [{"type": "approve"|"reject"}]})`.
   Streamlit (`app/ui/app.py`) and the React dev console need no changes.
4. **Voice mode is migrated in the same pass**, not deferred — it directly
   calls `Command(resume=...)` and inspects `snapshot.next` itself (not
   through the HTTP router), so it cannot be insulated from the contract
   change the way Streamlit/React are. `app/voice/hitl.py` and
   `app/voice/graph.py` are both in scope.
5. **One shared agent factory**, not two parallel `create_agent` calls (text
   and voice). Voice's current graph already skips `record_question`
   specifically because voice turns don't need it — under this design voice
   has no need for a wrapping `StateGraph` at all; it compiles the shared
   factory directly.
6. **`app/api/routers/stream.py` is in scope too** (found while planning, not
   during brainstorming — same category of hidden coupling as voice, just a
   file not checked earlier). It hardcodes two node-name dependencies on the
   current graph: `meta.get("langgraph_node") == "generate"` gates which
   streamed tokens reach the client (event `token`), and
   `"approval" in snapshot.next` gates the `interrupted` SSE event. Both must
   be updated to whatever node names the compiled `single_agent` subgraph
   actually produces, verified empirically against the compiled graph during
   implementation — not assumed. Silent breakage risk if missed: the final
   answer would still arrive (via `done`), but word-by-word streaming and the
   "approval needed" signal to the frontend would both go dark with no error
   raised anywhere.

## Architecture

```
Text:  START → record_question → single_agent (create_agent subgraph node) → END
Voice: single_agent (create_agent, compiled directly — no wrapping StateGraph)
```

- New `app/agent/single_agent.py`: `build_single_agent()` → one
  `create_agent(model=, tools=TOOLS, system_prompt=SYSTEM_PROMPT,
  middleware=[...])`. Mirrors a multi-agent specialist file exactly, except
  there is only one.
- `app/agent/graph.py`: thin `StateGraph` with `record_question` (unchanged)
  feeding into `single_agent` as a subgraph node
  (`workflow.add_node("single_agent", build_single_agent())`), same pattern
  `multi_agent/graph.py` already uses for its 7 specialists. `generate.py`,
  `approval_node`, `route_after_generate`, `route_after_approval`, `run_tools`
  are all removed — their behavior moves into middleware or is handled by
  `create_agent` itself.
- `app/voice/graph.py`: `build_voice_agent_app(checkpointer, store)` becomes a
  thin wrapper that returns `build_single_agent()` compiled with the given
  checkpointer/store directly — no `StateGraph` of its own.
- `app/agent/guardrails/node.py` (`pii_guard_node`, `route_after_pii_guard`)
  is no longer used by either graph after this change — `SensitiveDataGuard`
  (middleware form, already used by all 7 multi-agent specialists) covers the
  same behavior inside `single_agent`'s middleware list. The module is not
  deleted in this change (out of scope — a later cleanup can remove it once
  confirmed nothing else references it).

### Middleware list for `single_agent`

Built from `base_middleware(check_email=False)` (same exemption reasoning as
`email_agent`/`portfolio_agent`/`memory_agent`/`filesystem_agent`: this one
graph bundles `send_email`, `save_memory`, `write_file`, and
`save_portfolio_report` together, so it needs real addresses) plus two
single-agent-specific additions:

| Middleware | Source | Purpose |
|---|---|---|
| `SensitiveDataGuard(check_email=False)` | `base_middleware()` | replaces `pii_guard` node |
| `today_prompt` | `base_middleware()` | unchanged |
| `summarization()` | `base_middleware()` | **new for this graph** — closes gap #1 |
| `mask_credit_cards()` | `base_middleware()` | unchanged |
| `ModelCallLimitMiddleware` (`call_limit()`) | `base_middleware()` | unchanged |
| `model_fallback()` | `base_middleware()` | opt-in, replaces today's hand-rolled `.with_fallbacks()` |
| `model_retry()` | `base_middleware()` | replaces today's hand-rolled `.with_retry()` |
| `ErrorRecoveryMiddleware` (**new**) | `app/agent/single_agent.py` | preserves `ERROR_RECOVERY_PROMPT` behavior — decision 1 |
| `HumanInTheLoopMiddleware(interrupt_on={...})` | official | replaces `approval_node` + `READ_ONLY_TOOLS` check |
| `strip_tool_images` | `app/agent/middleware.py` | replaces `run_tools`'s inline `_strip_image_content` loop — same singleton `browser_agent` already uses, applied here to all tools (harmless no-op on non-image content, confirmed via `app/agent/nodes/tool_utils.py`'s `strip_image_content`) |
| `tool_errors_to_messages` | `base_middleware()` | unchanged |

`interrupt_on` built from the side-effect subset of `TOOLS` (confirmed via
`app/agent/tools/__init__.py`, not assumed): `{"save_memory": True,
"save_portfolio_report": True, "send_email": True, "write_file": True}`. The
other 18 tools are read-only and need no entry (matches `READ_ONLY_TOOLS`
today).

`ErrorRecoveryMiddleware` design: a `wrap_model_call` middleware (not
`before_model` — the current behavior replaces the entire request, not just
the system prompt: `generate.py` today calls the plain non-tool-bound model
with only `[SystemMessage(ERROR_RECOVERY_PROMPT), HumanMessage(error text)]`,
dropping the rest of the conversation and the tool bindings for that one
call). It checks if the last message is a `ToolMessage` with
`status == "error"`; if so, it calls `handler` with a request rebuilt to
match that exact shape (system prompt swapped, messages replaced, tools
cleared) instead of forwarding the normal request unchanged.

### HITL contract changes

- `app/api/routers/approve.py`: `Command(resume=decision)` (string) becomes
  `Command(resume={"decisions": [{"type": decision}]})`. `ApproveRequest`
  schema, `ChatResponse` schema, and every HTTP caller are unchanged.
- `app/voice/hitl.py`:
  - `resume_with(agent_app, thread_id, verdict)`: same `Command` shape change.
  - `is_interrupted(agent_app, thread_id)`: `"approval" not in snapshot.next`
    becomes a check against `HumanInTheLoopMiddleware`'s actual node name
    (`"HumanInTheLoopMiddleware.after_model"`, confirmed via the existing
    multi-agent test `"HumanInTheLoopMiddleware.after_model" in nodes` in
    `tests/unit/test_multi_agent_email_agent.py`) — verify the exact string
    against the compiled single-agent graph during implementation rather than
    assuming it matches the multi-agent specialist's node name exactly, since
    node naming could differ when there's no specialist name prefix.

### What explicitly changes in behavior (call these out at implementation/QA time)

- Mixed-batch reject no longer cancels read-only calls in the same batch
  (decision 2) — read-only calls execute regardless.
- Single-agent now has `SummarizationMiddleware` (trigger 6000 tokens, keep
  50 messages) — long conversations get compacted; they didn't before.
- Model-call retry/fallback now flow through `base_middleware()`'s factories
  instead of the ad hoc `.with_retry()`/`.with_fallbacks()` added earlier
  this session to `generate.py` (removed by this change).

## Testing

- `tests/unit/test_graph_structure.py`: node set changes
  (`record_question`, `single_agent`) — rewrite.
- `tests/unit/test_generate_answer.py`: `generate.py` no longer exists —
  replace with tests against `build_single_agent()`'s middleware list and
  `ErrorRecoveryMiddleware` specifically (unit-test the middleware in
  isolation with `create_agent(model=FakeToolModel(...), middleware=[...])`,
  same pattern `test_middleware.py` already uses for `today_prompt` etc).
- `tests/unit/test_voice_graph_structure.py`: node set changes (no more
  `generate`/`approval`/`tools` — becomes whatever `create_agent` compiles
  internally); rewrite the specific assertions, keep the intent (voice graph
  compiles, has no `record_question`).
- New tests for `approve.py`'s updated `Command(resume=...)` shape (reject
  still works, approve still works) — no `/approve` router test file exists
  today (confirmed: `tests/unit/` has no `test_approve.py`), so this is a new
  file, not an update. `tests/unit/test_stream.py`'s `_FakeAgentApp` pattern
  (`app.state.agent_app = fake` + `TestClient(app)`) is the house style to
  follow.
- New tests for `app/voice/hitl.py`'s updated node-name check and resume
  shape.
- `tests/unit/test_stream.py`: existing tests hardcode
  `meta.get("langgraph_node") == "generate"` via their fake token metadata
  and `next_after=("approval",)` for the interrupted-event test — update
  both to the new node name(s) once confirmed against the compiled graph.
- `tests/unit/test_hitl_interrupt.py`: tests `approval_node` directly, which
  no longer exists — replace with tests against the new
  `HumanInTheLoopMiddleware` wiring (mirroring
  `tests/unit/test_multi_agent_hitl.py`'s approve/reject/edit pattern).
- `tests/unit/test_tool_output_image_stripping.py`: imports
  `_strip_image_content` from `app.agent.graph` (the re-export disappears
  with `run_tools`) — update the import to
  `app.agent.nodes.tool_utils.strip_image_content` directly.
  `tests/unit/test_tool_utils.py` already imports from the correct module
  and needs no change.
- Full regression: `uv run pytest tests/ -q` must stay green throughout.

## Out of scope

- Deleting `app/agent/guardrails/node.py` (`pii_guard_node`,
  `route_after_pii_guard`) — left in place, unused, for a later cleanup.
- Any change to the multi-agent graph, specialists, or supervisor.
- `EmailRecipientGuard`-equivalent restriction on single-agent's `send_email`
  (multi-agent's `email_agent` has one; single-agent never has, and adding
  one is not part of this migration's goal).
- AgentCore Memory Store / checkpointer changes (separate, already-identified
  gap from the memory review; not part of this spec).
