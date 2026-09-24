# Multi-agent specialists on `create_agent` + middleware — design

**Date:** 2026-09-24
**Status:** implemented
**Scope:** `app/agent/multi_agent/` only

## Goal

Rebuild the 7 multi-agent specialists with LangChain v1's `create_agent` and
official middleware, so the multi-agent code follows the documented LangChain
method and future features (guardrails, memory, summarization, …) can be added
per specialist as middleware.

## Decisions (from brainstorming)

1. **Pattern stays Router.** The supervisor node (LLM routing + deterministic
   finish) is unchanged. Moving to the "Subagents" pattern (supervisor as a
   `create_agent` calling specialists as tools) is explicitly out of scope; the
   specialists built here are reusable as-is if that happens later.
2. **Only the multi-agent mode changes.** The single-agent graph
   (`app/agent/graph.py`) — which serves the API, Streamlit, React console,
   voice and AWS prod — is not touched. The multi-agent mode is not wired to
   any of those today (only tests and `scripts/qa_wealth_db.py` use it), so the
   blast radius is limited to those.
3. **HITL uses the official `HumanInTheLoopMiddleware`**, not the custom
   `approval_node`. Resume format becomes the official
   `Command(resume={"decisions": [...]})` with `approve` / `reject` / `edit`,
   decided **per tool call** (no atomic-batch rule in the multi-agent mode).
   When the multi-agent mode is later wired to `/approve`, the router adapts to
   this format at that point.
4. **One file per specialist is kept** (`rag_agent.py`, `finance_agent.py`,
   `portfolio_agent.py`, `browser_agent.py`, `email_agent.py`,
   `filesystem_agent.py`, `memory_agent.py`) for readability and so each agent
   can grow its own middleware independently. Shared pieces live in a new
   `common.py`.

## Architecture

```
START → record_question → supervisor ─┬─▶ rag_agent        ─┐
                                      ├─▶ finance_agent     │
                                      ├─▶ portfolio_agent   │  each = create_agent(...)
                                      ├─▶ browser_agent     ├─▶ supervisor → END
                                      ├─▶ email_agent       │  (added as a subgraph node,
                                      ├─▶ filesystem_agent  │   static edge back to supervisor)
                                      └─▶ memory_agent     ─┘
```

- Each `build_<name>_agent()` returns the compiled graph from `create_agent`,
  added with `workflow.add_node("<name>_agent", build_<name>_agent())` and a
  static `workflow.add_edge("<name>_agent", "supervisor")`.
- The specialist shares the `messages` key with `SupervisorState`
  (`add_messages` reducer on both sides), so it sees the full conversation and
  its messages are appended to the parent's. No `Command(graph=Command.PARENT)`.
- The supervisor's existing deterministic finish (last message is an
  `AIMessage` without `tool_calls` after a specialist ran) ends the turn.
- Specialists are compiled without their own checkpointer; they inherit the
  parent's, so HITL interrupts pause and resume the whole multi-agent graph.

### Files

| File | Change |
|---|---|
| `multi_agent/common.py` | **new** — `specialist_model()`, `today_prompt`, `tool_errors_to_messages`, `strip_tool_images`, `call_limit()` |
| `multi_agent/<7>_agent.py` | rewritten: `build_<name>_agent()` returning `create_agent(...)` |
| `multi_agent/graph.py` | add specialists as subgraph nodes + static edges back to `supervisor` |
| `multi_agent/supervisor.py` | unchanged (comment references to `Command.PARENT` updated only if present) |
| `multi_agent/state.py` | unchanged |
| `app/agent/graph.py`, `nodes/`, `api/`, `voice/`, `prod/` | unchanged |

### Specialists

| Specialist | Tools | HITL (`interrupt_on`) | Extra middleware |
|---|---|---|---|
| `rag_agent` | `search_knowledge_base`, `web_search` | — | — |
| `finance_agent` | `yfinance_get_ticker_info`, `yfinance_get_price_history`, `yfinance_get_ticker_news` | — | — |
| `portfolio_agent` | `read_query`, `list_tables`, `describe_table`, `yfinance_get_ticker_info`, `portfolio_metrics`, `pct_change`, `concentration_screen` | — | — |
| `browser_agent` | `browser_navigate`, `browser_snapshot`, `browser_take_screenshot` | — | `strip_tool_images` |
| `email_agent` | `send_email` | `send_email` | — |
| `filesystem_agent` | `read_text_file`, `list_directory`, `write_file` | `write_file` | — |
| `memory_agent` | `save_memory`, `recall_memory`, `list_memories` | `save_memory` | — |

Tool lists and system prompts are unchanged (prompts stay in
`app/agent/prompts/specialist_agent_prompts.py`). Every specialist gets
`name="<name>_agent"`.

### Shared middleware (`common.py`)

Order in every specialist: `today_prompt`, `call_limit()`,
`tool_errors_to_messages`, then agent-specific middleware (HITL /
`strip_tool_images`).

- **`specialist_model()`** — `ChatOpenAI(model=settings.OPENAI_MODEL,
  temperature=0, streaming=True)`, same settings as today.
- **`today_prompt`** — `@dynamic_prompt` that returns the agent's static
  `system_prompt` with `with_today(...)` applied, so all 7 specialists (including
  email, filesystem, memory, which lack it today) know the current date.
- **`call_limit()`** — official `ModelCallLimitMiddleware(run_limit=10,
  exit_behavior="end")`: a specialist makes at most 10 model calls per run (same for all 7 for now; per-agent tuning later — browser/RAG tasks can need 6+), so
  a looping agent can't run up OpenAI cost.
- **`tool_errors_to_messages`** — `@wrap_tool_call` (documented pattern; the
  built-in `ToolErrorMiddleware` is not in the installed langchain 1.2.17):
  any tool exception becomes a `ToolMessage(status="error")` the model can read,
  instead of aborting the run. Preserves the "thread poisoning" fix (today:
  `ToolNode(handle_tool_errors=True)`). Must work on the async path (MCP tools
  are async-only).
- **`strip_tool_images`** — `@wrap_tool_call` that removes image content parts
  from the tool result (reuses `nodes.tool_utils.strip_image_content`), since
  OpenAI rejects images in tool messages. Browser specialist only.

## HITL flow (multi-agent mode)

1. Specialist's model emits `send_email` / `write_file` / `save_memory`.
2. `HumanInTheLoopMiddleware` calls `interrupt(...)`; the multi-agent graph
   pauses and the checkpointer stores the state.
3. Caller resumes with `Command(resume={"decisions": [d1, d2, …]})`, one
   decision per pending side-effect call, each
   `{"type": "approve"}`, `{"type": "reject", "message": "..."}` or
   `{"type": "edit", "edited_action": {"name": ..., "args": {...}}}`.
4. Read-only calls in the same batch are not interrupted.

## Error handling

- Tool exceptions → error `ToolMessage` (see `tool_errors_to_messages`).
- Model-call cap reached → specialist ends its run (`exit_behavior="end"`);
  the supervisor then finishes or re-routes as today (bounded by
  `MAX_AGENT_HOPS = 4`).
- Unknown/malformed resume payloads: official middleware behavior (raises);
  acceptable because no external caller exists yet.

## Testing

Offline unit tests (no OpenAI calls; fake chat model):

- Per specialist: tool names match the table; HITL middleware present only on
  email/filesystem/memory with exactly the listed `interrupt_on` tools;
  `today_prompt`, `call_limit`, `tool_errors_to_messages` present; browser has
  `strip_tool_images`.
- `today_prompt` appends today's date to the static prompt.
- `tool_errors_to_messages` turns a raising tool into an error `ToolMessage`
  (async path).
- `strip_tool_images` drops image parts, keeps text.
- Graph structure: 7 specialist nodes + supervisor + record_question; each
  specialist has an edge back to `supervisor`.
- HITL end-to-end on the compiled multi-agent graph with a fake model and a
  fake `send_email`: interrupt fires; `approve` executes the tool; `reject`
  does not; `edit` executes with edited args.
- Existing supervisor routing tests keep passing unchanged.

One live pass at the end (per the proportionate-QA rule): the multi-agent case
in `scripts/qa_wealth_db.py` plus one email request that hits HITL and is
approved (email is simulated or goes to the user's own verified address).

## Out of scope

- Single-agent graph, API routers, voice, Streamlit/React, prod/CDK.
- Subagents pattern; guardrails, PII, summarization, long-term memory
  middleware (to be added later, per specialist).
- Wiring the multi-agent mode to `/stream` / `/approve`.
