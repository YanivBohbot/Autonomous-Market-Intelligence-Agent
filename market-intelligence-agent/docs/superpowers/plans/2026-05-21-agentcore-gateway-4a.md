# Plan — AgentCore Gateway Phase 4a

**Spec:** `docs/superpowers/specs/2026-05-21-agentcore-gateway-design.md`
**Branch:** `feat/agentcore-prod` (pushed)
**Last commit before plan:** `518c2c7 docs(prod): add deployment plan and update prod/agent README`

## Working directory

All paths below are relative to `market-intelligence-agent/`.

Run commands from `market-intelligence-agent/prod/agent/` unless noted.

## Execution order

### Step 1 — yfinance Lambda

1. Create `prod/agent/app/yfinance_tool/` (mkdir).
2. Write `handler.py` — an MCP server using `mcp.server.fastmcp.FastMCP` or `mcp.server.Server` (whichever pattern is current per `mcp` lib v1.22+; check via context7 if unsure). Exposes:
   - `yfinance_get_ticker_info(ticker: str)` — `yf.Ticker(ticker).info` → JSON
   - `yfinance_get_price_history(ticker: str, period: str = "1mo")` — `yf.Ticker(ticker).history(period=period)` → list of dicts
   - `yfinance_get_ticker_news(ticker: str, limit: int = 5)` — `yf.Ticker(ticker).news[:limit]` → list of dicts
   Wrap each in try/except; on yfinance failure return `{"error": "<message>"}` instead of raising. Apply a 10s socket timeout (`socket.setdefaulttimeout(10)`).
3. Write `requirements.txt`:
   ```
   mcp>=1.22.0
   yfinance>=0.2.40
   ```
4. Sanity-check the handler imports cleanly with `python -c "import handler"` (will fail because mcp / yfinance not installed locally — that's fine; the AgentCore CDK build installs deps).

### Step 2 — CRM Lambda

1. Create `prod/agent/app/crm_tool/`.
2. Copy `market-intelligence-agent/customers.db` → `prod/agent/app/crm_tool/customers.db`. If the file doesn't exist in dev, create it by running `uv run python create_db.py` from `market-intelligence-agent/` first.
3. Write `handler.py` exposing `read_query(query: str) -> str`:
   - Sanity-check `re.match(r"^\s*SELECT\b", query, re.I)`; reject otherwise with `{"error": "Only SELECT queries permitted"}`.
   - Open sqlite with `sqlite3.connect("file:customers.db?mode=ro&immutable=1", uri=True)`.
   - Return `json.dumps(rows)` where `rows` is `list[dict]` with column names from `cursor.description`.
4. Write `requirements.txt`:
   ```
   mcp>=1.22.0
   ```

### Step 3 — Edit `agentcore.json`

In `prod/agent/agentcore/agentcore.json`, replace the existing `agentCoreGateways[0].targets: []` with:

```jsonc
"targets": [
  {
    "name": "yfinance",
    "targetType": "lambda",
    "toolDefinitions": [
      {
        "name": "yfinance_get_ticker_info",
        "description": "Get current ticker info (price, volume, market cap, etc.) for a stock symbol.",
        "inputSchema": { "type": "object", "properties": { "ticker": { "type": "string" } }, "required": ["ticker"] }
      },
      {
        "name": "yfinance_get_price_history",
        "description": "Get historical OHLCV price data for a stock symbol over a period.",
        "inputSchema": { "type": "object", "properties": { "ticker": { "type": "string" }, "period": { "type": "string", "default": "1mo" } }, "required": ["ticker"] }
      },
      {
        "name": "yfinance_get_ticker_news",
        "description": "Get recent news articles for a stock symbol.",
        "inputSchema": { "type": "object", "properties": { "ticker": { "type": "string" }, "limit": { "type": "integer", "default": 5 } }, "required": ["ticker"] }
      }
    ],
    "compute": {
      "host": "Lambda",
      "implementation": { "language": "Python", "path": "app/yfinance_tool", "handler": "handler.app" }
    }
  },
  {
    "name": "crm",
    "targetType": "lambda",
    "toolDefinitions": [
      {
        "name": "read_query",
        "description": "Run a SELECT-only SQL query against the customers database. Returns JSON list of rows.",
        "inputSchema": { "type": "object", "properties": { "query": { "type": "string" } }, "required": ["query"] }
      }
    ],
    "compute": {
      "host": "Lambda",
      "implementation": { "language": "Python", "path": "app/crm_tool", "handler": "handler.app" }
    }
  }
]
```

Verify the schema requirements by re-reading `prod/agent/agentcore/cdk/node_modules/@aws/agentcore-cdk/dist/schema/schemas/mcp.d.ts` if any field is rejected during `agentcore validate`.

Run from `prod/agent/`:
```
agentcore validate
```
If it exits non-zero, fix the JSON until it passes.

### Step 4 — Rewire agent's MCP registry

Edit `prod/agent/app/agent/app/agent/tools/mcp_clients/registry.py`:

- Replace the existing stdio `MultiServerMCPClient` construction with a `streamable_http` config pointing at `os.environ["GATEWAY_URL"]`.
- If `GATEWAY_URL` is unset, return `[]` from `get_mcp_tools()` and log `[registry] GATEWAY_URL unset — Gateway tools skipped`.
- The async loop guard (`_run_async`) and `select_tool()` stay; both should gracefully handle empty tool lists by logging a warning and returning a no-op tool that raises a runtime error if ever called.

Refer to `langchain-mcp-adapters` docs for the `streamable_http` transport config shape if uncertain (use context7).

### Step 5 — Re-enable tool imports

Edit `prod/agent/app/agent/app/agent/tools/__init__.py`:

- Wrap the MCP-backed tool imports in a single try/except.
- On success: include yfinance + crm tools in `TOOLS`.
- On failure: log `[tools] MCP-backed tools unavailable, falling back to in-container set` and proceed with email + memory only.
- `READ_ONLY_TOOLS` keeps the full union — names are valid even if the tool object isn't loaded; the validation block at the bottom must be adjusted to allow names not in `TOOLS` (since gating happens by name).

### Step 6 — CDK stack — inject GATEWAY_URL

Edit `prod/agent/agentcore/cdk/lib/cdk-stack.ts`:

After the existing `if (mcpSpec?.agentCoreGateways && ...) { new AgentCoreMcp(...) }` block:

- Capture the resulting `AgentCoreMcp` instance.
- For each runtime in `this.application.environments`, call `env.runtime.addEnvironmentVariable("GATEWAY_URL", mcp.gatewayUrl)` (or whatever attribute the L3 construct exposes — check `dist/cdk/constructs/l3/AgentCoreMcp.d.ts`).
- If the L3 construct doesn't expose the URL directly, fall back to building it from `cdk.Fn.join` on the gateway logical ID and `bedrock-agentcore.us-east-1.amazonaws.com` per the schema.

Run from `prod/agent/agentcore/cdk/`:
```
npx tsc --noEmit
```
Must pass with no errors before proceeding.

### Step 7 — Lock file + local smoke test

1. From `prod/agent/app/agent/`: `uv lock` (in case anything in pyproject changed — should be a no-op).
2. From `prod/agent/`: `docker stop agentcore-dev-agent || true; docker rm agentcore-dev-agent || true`.
3. `agentcore dev -p 8090 --logs` (in background; wait for "Application startup complete").
4. Smoke test 1: `agentcore dev -p 8090 "What can you help me with?"` → expect `status: "completed"`.
5. Smoke test 2: `agentcore dev -p 8090 "Send an email to test@example.com saying hello"` → expect `status: "interrupted"` with `send_email` in `pending_tool_calls`.
6. Smoke test 3: `curl -X POST http://localhost:8090/invocations -H "Content-Type: application/json" -H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: local-dev-session" -d '{"resume":"reject"}'` → expect cancellation acknowledged.
7. Confirm log line `[registry] GATEWAY_URL unset — Gateway tools skipped` appeared at boot.
8. Stop the dev container.

### Step 8 — README + commit + push

1. Update `prod/agent/README.md` — add a "Gateway tools" subsection explaining local-dev (no Gateway) and that real Gateway tools come alive after Phase 6 deploy.
2. Stage all changes under `market-intelligence-agent/prod/agent/` and the new spec/plan files.
3. Commit with message:
   ```
   feat(prod/agent): Phase 4a — Gateway + yfinance + CRM Lambda targets

   - Two Lambda tool servers under prod/agent/app/{yfinance_tool,crm_tool}/
     publishing MCP via fastmcp; bundled customers.db for CRM read-only.
   - agentcore.json: market-gw Gateway with two `lambda`-type targets and
     inline toolDefinitions for discovery.
   - registry.py: streamable_http MCP client pointing at $GATEWAY_URL;
     empty no-op when unset (local-dev fallback).
   - tools/__init__.py: re-enable yfinance + read_query tool imports
     behind a try/except so local dev doesn't crash without Gateway.
   - cdk-stack.ts: inject GATEWAY_URL env var into every runtime.

   Verified locally: agentcore dev boots clean, MemorySaver fallback log,
   Phase 2 smoke tests still pass with email-HITL working.
   ```
4. `git push`.

### Step 9 — Update tracking docs

1. Append a "Phase 4a — done" entry to `docs/AGENTCORE_DEPLOYMENT.md` with the commit hash and the files touched.
2. Append (don't replace) the phase-status note to the memory file at `C:\Users\user\.claude\projects\F--Langchain-and-LangGraph-and-MCP-Autonomous-Market-Intelligence-Agent\memory\project_agentcore_prod_inflight.md` — mark Phase 4a done and note "Phase 4b (Browser) / 4c (Memory) still pending".
3. Final commit + push for the docs.

## What "done" looks like

- All 3 Phase 2 smoke tests still pass.
- `npx tsc --noEmit` clean.
- `agentcore validate` clean.
- New files: 2 handler.py + 2 requirements.txt + 1 customers.db + 1 spec + 1 plan.
- Modified files: 5 under `prod/agent/` + 2 docs.
- 2 commits pushed to `feat/agentcore-prod`.

## What to NOT do

- Do not run `agentcore deploy` — that's Phase 6.
- Do not delete the old stdio `_client.py` files (yfinance_client.py, filesystem_client.py, browser_client.py, mcp_client.py). They stay as reference for dev parity, just unused.
- Do not touch `app/agent/graph.py`, `nodes/*`, or `prompts/system.py` — graph + prompts unchanged.
- Do not modify the dev project at `market-intelligence-agent/app/` — prod copy only.
- Do not write tests (deferred per project convention).
