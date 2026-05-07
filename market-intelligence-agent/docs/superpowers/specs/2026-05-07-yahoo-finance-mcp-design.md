# Yahoo Finance MCP Integration — Design Spec

**Date:** 2026-05-07
**Status:** Approved (pending user spec review)
**Initiative:** Subsystem #1 of the agentic-expansion roadmap (`2026-05-07-agentic-expansion-roadmap.md`).

## Goal

Add Yahoo Finance market data to the agent as a second MCP stdio tool server, exposing three read-only tools (`yf_quote`, `yf_history`, `yf_news`) that the LLM can call from the existing `generate → approval → tools → generate` loop. Introduce a read-only allowlist so quote/news lookups don't trigger the human-approval interrupt.

## Use Cases

The agent should handle all four flavors of market query:
- Quote lookup ("what's AAPL trading at?")
- Research reports ("summarize NVDA over the last quarter")
- Watchlist / portfolio analysis ("compare AAPL, MSFT, GOOG")
- Mixed CRM + market workflows ("email the top VIP a market summary for AAPL")

The LLM picks tools per query; no deterministic routing is added.

## Architecture

Yahoo Finance is integrated as a **second MCP stdio subprocess client**, parallel to the existing `crm_query` integration. No graph-topology changes; yfinance is just three new tools the LLM can call.

The one new graph behavior: `approval_node` checks tool names against a `READ_ONLY_TOOLS` allowlist and skips the `interrupt()` call for reads. Read-only flow:

```
generate → approval ─[read-only?]─→ tools → generate
                    └[side-effect]─→ interrupt() → tools | cancel
```

Mixed batches (read + write tool calls in one `AIMessage`) follow an **interrupt-if-any** rule: if any tool call in the batch is side-effect, the node interrupts and surfaces the side-effect call(s) to the human. On approve, all calls in the batch run; on reject, all get cancellation `ToolMessage`s. Splitting batch execution was rejected as graph complexity for marginal benefit.

## Components & Files

### New files

- **`app/agent/tools/mcp_clients/yfinance_client.py`** — stdio subprocess MCP client mirroring `mcp_client.py`. Launches `yfinance-mcp` as a subprocess, exposes a sync shim wrapping the async MCP `call_tool`. Bottom of file declares three module-level LangChain `@tool` wrappers: `yf_quote_tool`, `yf_history_tool`, `yf_news_tool`. Each tool has a Pydantic args schema and calls into the shim with the matching MCP tool name.

- **`app/agent/prompts/system.py`** — module-level `SYSTEM_PROMPT: str` constant. Holds the English-rewritten prompt with existing CRM/email instructions plus a new `📈 MARKET DATA` section listing the three yfinance tools and when to use each. Pulled out of `generate.py` because the prompt is about to grow.

### Modified files

- **`app/agent/tools/__init__.py`** — imports the three yfinance tools, appends them to `TOOLS`, exports `READ_ONLY_TOOLS: set[str] = {"crm_query", "yf_quote", "yf_history", "yf_news"}`.

- **`app/agent/graph.py`** — `approval_node` consults `READ_ONLY_TOOLS`. If every `tc["name"]` in `tool_calls` is read-only, return `{}` immediately without calling `interrupt()`. Otherwise, build the interrupt request from the side-effect tool calls only and proceed as today.

- **`app/agent/nodes/generate.py`** — replace inline French prompt with `from app.agent.prompts.system import SYSTEM_PROMPT`. The error-path system message is also moved into `prompts/system.py` (or kept inline in English, implementer's call).

- **`pyproject.toml`** — add the `yfinance-mcp` dependency (resolve exact PyPI/npm name during implementation; community Python packages exist).

- **`README.md`** — one-line note that yfinance is now a tool.

### Unchanged

- `.env.example` — yfinance is unauthenticated, no new keys.
- The `mcp_client.py` shim for `crm_query` — left as is. We do not refactor a shared MCP base class yet (YAGNI; revisit when adding the third MCP server).

## Data Flow — Representative Query

*"What's NVDA trading at, and any news today?"*

1. `POST /chat` seeds state with `question` and a `HumanMessage`.
2. `rag → grader` → likely no relevant Pinecone chunks → `web_search` (or directly `generate`).
3. `generate` — LLM emits an `AIMessage` with parallel `tool_calls`: `yf_quote(ticker="NVDA")`, `yf_news(ticker="NVDA", limit=5)`.
4. `route_after_generate` sees `tool_calls` → `approval`.
5. `approval_node` — both calls are read-only → returns `{}`, no `interrupt()`.
6. `route_after_approval` — last message is still the `AIMessage` with `tool_calls` → `tools`.
7. `tools` (ToolNode) executes both tools; each shim spawns a short-lived MCP subprocess, gets the response, returns text. Two `ToolMessage`s appended.
8. `generate` (loop) — LLM writes final answer, no tool_calls.
9. `route_after_generate` → `END`.

Mixed-batch query *("look up VIPs and email the top one a market summary for AAPL")*: `crm_query` + `yf_quote` + `send_email` emitted together. `approval_node` detects `send_email` is side-effect → interrupt-if-any rule fires → human sees the email request → on approve, all three execute; on reject, all three get cancellation `ToolMessage`s.

## Error Handling

| Mode | Handling |
|---|---|
| MCP subprocess fails to launch / crashes | Sync shim catches exception, returns `"Error: Yahoo Finance service unavailable: <reason>"`. Existing `generate.py` error path detects `"Error"` in `ToolMessage.content` and routes to graceful explanation. Same shape as `crm_query` failures. |
| Invalid ticker / empty result | yfinance returns empty data; MCP server wraps as `"No data found for ticker: XXX"`. Passed through verbatim — LLM rephrases into a user-facing answer. |
| Rate limiting / network timeout | 10-second timeout (configurable via `settings.YFINANCE_TIMEOUT_S`, default 10). Timeout → `"Error: Yahoo Finance request timed out"` → graceful path. **No retries** — YAGNI. |

## Configuration

Add to `app/core/config.py`:

```python
YFINANCE_TIMEOUT_S: int = 10
```

No secrets, no new `.env` keys.

## Testing & Verification

**Deferred.** No automated tests and no manual smoke step are part of this spec. Only gate: the existing test suite (`test_grader.py`, `test_state_reducer.py`, `test_hitl_interrupt.py`, `test_stream.py`) must continue to pass — no regressions. Verification of the new yfinance behavior is left to a follow-up spec.

## Out of Scope

- Caching layer (Redis or in-memory). Duplicate calls within a single conversation are rare; YAGNI for a portfolio project.
- Request-rate metering — trust Yahoo's limits and the LLM's natural reluctance to repeat tool calls.
- Structured-output schemas on yfinance responses — text returned by the MCP server is passed straight to the LLM.
- A shared MCP base class for `mcp_client.py` and `yfinance_client.py`. Revisit when adding the third MCP server (Filesystem MCP).
- Expanding to the "standard 6" tool set (`get_financials`, `get_recommendations`, `get_info`). Ship the minimal 3, add more once we see what the LLM reaches for.
- Tool-tagging via metadata (`read_only=True` on each tool). The simple name-based allowlist in `READ_ONLY_TOOLS` is enough until tool count grows.
- Test design and CI integration — covered by a follow-up spec.

## Open Decisions for the Implementation Plan

- Exact PyPI package name and CLI invocation for the `yfinance-mcp` server (community packages vary). Resolve during the first implementation task.
- Whether `prompts/system.py` also absorbs the error-path system message in `generate.py`, or just the main prompt. Implementer's call.

## Success Criteria

- Three new tools (`yf_quote`, `yf_history`, `yf_news`) are registered in `TOOLS` and bound to the LLM in `generate`.
- A query containing only read-only tool calls runs end-to-end without invoking `interrupt()`.
- A query containing a `send_email` call (alone or mixed with reads) still gates through the human approval interrupt.
- The English `SYSTEM_PROMPT` is loaded from `app/agent/prompts/system.py` and contains a `📈 MARKET DATA` section.
- No existing test fails.
