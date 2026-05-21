# AgentCore Gateway for MCP tools — Design Spec

**Date:** 2026-05-21
**Status:** Approved (pending implementation)
**Branch:** `feat/agentcore-prod`
**Initiative:** Phase 4a of the AgentCore production deployment (`docs/AGENTCORE_DEPLOYMENT.md`).

## Goal

Re-enable the `yfinance_*` and `read_query` (CRM sqlite) tools in the production agent by hosting them as **Lambda-backed AgentCore Gateway targets** instead of stdio MCP subprocesses. The slim Python container in AgentCore Runtime has no `uvx`/`npx`, so stdio MCP servers can't spawn there. Gateway moves them out of the container into HTTPS-callable, IAM-authenticated, MCP-compatible endpoints.

Out of scope (separate sub-phases): AgentCore Browser (`4b`), AgentCore Memory replacing local memory tools (`4c`), filesystem tools (dropped — revisit only on user need).

## Use cases that must keep working

- Quote lookup: "what is AAPL trading at?"
- Price history: "show me MSFT's last 6 months"
- News: "latest news on NVDA"
- CRM read: "what are this customer's recent purchases?" → `read_query` SQL on `customers.db`
- Mixed flows: agent calls yfinance + email in one turn → HITL only intercepts email

## Architecture

```
                ┌──────────────────────────────────┐
   AgentCore    │       AgentCore Gateway          │
   Runtime ◄──► │   (single MCP-over-HTTPS URL)    │
   (LangGraph)  │   inbound auth: AWS_IAM          │
                │                                  │
                │   ├─ Target: yfinance (Lambda)   │ ──► yfinance Python pkg
                │   └─ Target: crm      (Lambda)   │ ──► bundled customers.db
                └──────────────────────────────────┘
```

**One Gateway, multiple Lambda targets.** Single MCP endpoint, single inbound IAM principal, single Policy attachment point in later phases. Per AWS canonical pattern.

**Lambdas authored as MCP servers** (not bare handlers). Each Lambda runs `mcp` Python lib serving the tool calls, packaged via CodeZip. AgentCoreMcp L3 construct creates the Lambda + ECR + role from the inline `compute` block in `agentcore.json`. No hand-written CDK code for the Lambdas themselves — declarative in JSON.

## Components & Files

### New files

- **`prod/agent/app/yfinance_tool/handler.py`** — Lambda MCP server using `mcp.server` exposing three tools: `yfinance_get_ticker_info(ticker)`, `yfinance_get_price_history(ticker, period="1mo")`, `yfinance_get_ticker_news(ticker, limit=5)`. Each calls `yfinance` PyPI package directly. Match the **exact tool names** from the dev project so the system prompt and `READ_ONLY_TOOLS` allowlist work unchanged.

- **`prod/agent/app/yfinance_tool/requirements.txt`** — `mcp>=1.22.0`, `yfinance>=0.2.40`. No transitive deps from the agent container.

- **`prod/agent/app/crm_tool/handler.py`** — Lambda MCP server exposing one tool: `read_query(query: str) -> str`. Opens the bundled `customers.db` (read-only mode), runs the SELECT, returns JSON-serialized rows. Reject non-SELECT statements (defense in depth — Gateway Policy will also enforce in Phase 5).

- **`prod/agent/app/crm_tool/customers.db`** — copied from the dev project (`market-intelligence-agent/customers.db`) at implementation time.

- **`prod/agent/app/crm_tool/requirements.txt`** — `mcp>=1.22.0`. Sqlite is stdlib.

### Modified files

- **`prod/agent/agentcore/agentcore.json`** — under the existing `market-gw` gateway, append two `targets` entries with `targetType: "lambda"` and `compute: { host: "Lambda", implementation: { language: "Python", path: "app/yfinance_tool", ... } }`. Tool definitions inline so Gateway can advertise them via MCP discovery. (CLI doesn't expose this flow — hand-edit per schema in `node_modules/@aws/agentcore-cdk/dist/schema/schemas/mcp.d.ts`.)

- **`prod/agent/app/agent/app/agent/tools/mcp_clients/registry.py`** — replace `MultiServerMCPClient` stdio config with a **single `streamable_http` entry** pointing at `os.environ["GATEWAY_URL"]`. When `GATEWAY_URL` is unset (local dev), the registry returns an empty tool list. Log loudly which path was taken so debugging is obvious.

- **`prod/agent/app/agent/app/agent/tools/__init__.py`** — un-comment the yfinance + CRM imports gated behind a try/except. If the import raises (e.g., empty MCP client in local dev), log a warning and proceed with the in-container tools only. `READ_ONLY_TOOLS` keeps the same names whether or not the tools are registered — names are still valid allowlist entries.

- **`prod/agent/agentcore/cdk/lib/cdk-stack.ts`** — after the AgentCoreMcp construct is created, look up the Gateway URL via L3 construct outputs and inject it into every runtime as `GATEWAY_URL` env var. Use `addEnvironmentVariable` (existing pattern from Phase 3). No new IAM perms needed beyond what AgentCoreMcp auto-grants.

- **`prod/agent/docs/.../prod/agent/README.md`** — append a "Gateway tools" section explaining the local-dev no-Gateway fallback and how to point at a deployed Gateway via `GATEWAY_URL` env var.

### Files NOT modified (deliberately)

- **`app/agent/graph.py`, `nodes/*`, `prompts/system.py`** — graph topology and prompts are unchanged. Tool names match dev so the system prompt's tool-use guidance still applies verbatim.

- **`app/agent/tools/mcp_clients/{yfinance,filesystem,browser}_client.py`** — kept on disk for reference but unused; their `select_tool` calls happen behind the gated import in `tools/__init__.py`.

- **Dockerfile** — unchanged. The container no longer needs `yfmcp` or `mcp-server-sqlite` deps; they live in the Lambdas now. (Optional dep cleanup deferred to a follow-up commit to keep this PR focused.)

## Decisions

| Question | Answer | Why |
|---|---|---|
| One Gateway or many? | **One** | Single IAM principal, single Policy attach point, single MCP URL |
| Lambda code shape | **MCP server** (not raw handler) | Gateway expects MCP protocol; AgentCoreMcp construct handles the rest |
| Lambda packaging | **CodeZip per Lambda** | Each ~5-20 MB; no need for containerized Lambda |
| Gateway inbound auth | **AWS_IAM** | Container's runtime role authenticates; no JWT/Cognito complexity yet |
| Local-dev with no Gateway | **Empty tool list, log warning** | Don't fail boot. Container's native tools (email, memory) still work. |
| Phase 4a passes when | `agentcore dev` boots clean + the email-HITL smoke test from Phase 2 still passes | Validate the wiring, not the new tools (real Gateway only exists post-deploy) |

## Non-goals

- Wiring the agent's `MultiServerMCPClient` to actually fetch tools from a *running* Gateway during local dev. Local dev runs without Gateway tools. The first end-to-end Gateway test happens in Phase 6 after `agentcore deploy`.
- IAM least-privilege tightening on the Lambda execution roles — defaults are fine; Phase 5 hardens.
- Cedar policies on Gateway tool calls — Phase 5.
- Migrating sqlite to DynamoDB — out of scope; bundled file is acceptable for read-only customer data.

## Acceptance criteria

1. `npx tsc --noEmit` from `prod/agent/agentcore/cdk/` passes.
2. `agentcore dev -p 8090 --logs` boots clean. Log shows `[registry] GATEWAY_URL unset — Gateway tools skipped` (or similar).
3. The Phase 2 smoke tests still pass:
   - Simple prompt → completed response
   - Email prompt → `status: "interrupted"` with `pending_tool_calls`
   - `{"resume":"reject"}` → cancellation acknowledged
4. `agentcore.json` parses against the AgentCore schema (no validation errors on `agentcore validate`).
5. New commits land cleanly on `feat/agentcore-prod`. Push the branch.

## Open questions for the implementer

- The yfinance package occasionally hits Yahoo's anti-scraping. Add a 10s timeout (`YFINANCE_TIMEOUT_S` from dev `core/config.py`). Cache layer (Phase 5+) deferred.
- For `read_query`, sanitize via a strict `re.match(r"^\s*SELECT\b", query, re.I)` guard plus connection opened with `?mode=ro&immutable=1`. Don't trust the LLM to behave.
