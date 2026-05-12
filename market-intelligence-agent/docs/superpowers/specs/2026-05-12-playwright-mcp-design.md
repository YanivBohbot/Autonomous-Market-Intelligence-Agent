# Playwright MCP — Design Spec

**Subsystem #3 of the agentic-expansion roadmap.** Use cases captured separately in `docs/playwright-mcp-use-cases.md` (NVDIA news deep-dive, competitor pricing watch, earnings call transcripts). This spec defines *how* we integrate Microsoft's `@playwright/mcp` into the existing `MultiServerMCPClient` registry.

## Decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Tool scope | 3 tools: `browser_navigate`, `browser_snapshot`, `browser_take_screenshot` |
| 2 | Upstream package | `@playwright/mcp` (Microsoft official) |
| 3 | Browser session | Persistent per MCP server process (upstream default) |
| 4 | Chromium install | Baked into Dockerfile at build time via `npx playwright install --with-deps chromium` |
| 5 | Screenshot storage | `data/workspace/screenshots/`, set on the server via the `--output-dir` flag |
| 6 | HITL gate | All 3 tools → `READ_ONLY_TOOLS` (bypass interrupt). Screenshots are evidence captures, not user-facing artifacts, and live in a dedicated `screenshots/` subfolder away from briefs the user cares about. |

## Architecture

Single new entry in the existing `MultiServerMCPClient` config, plus a thin selector module that mirrors the shape of `filesystem_client.py`. No new transport, no new infrastructure, no special-case code paths.

The integration follows the pattern already proven by subsystems #1 (yfinance) and #2 (filesystem): the upstream MCP server's tool names are surfaced to the LLM as-is, with no controller-side prefix. Microsoft's `@playwright/mcp` already self-namespaces every tool with `browser_*`, so collisions with our other servers' tool names are impossible.

## Components

| File | Change |
|---|---|
| `app/agent/tools/mcp_clients/registry.py` | Add `"browser"` entry to `_server_config()` (one new dict block). |
| `app/agent/tools/mcp_clients/browser_client.py` | **NEW.** Selector module — imports `select_tool` from `registry`, re-exports `browser_navigate_tool`, `browser_snapshot_tool`, `browser_screenshot_tool` by the upstream tool names. |
| `app/agent/tools/__init__.py` | Import the 3 new tool symbols and append them to `TOOLS`. Add `browser_navigate`, `browser_snapshot`, `browser_take_screenshot` to `READ_ONLY_TOOLS`. |
| `app/agent/prompts/system.py` | Add "🌐 BROWSER GUIDELINES" section: when to use snapshot vs screenshot, navigate-before-snapshot rule, that screenshot filenames are workspace-relative under `screenshots/`. |
| `Dockerfile` | After the existing Node 20 install, add `RUN npx -y playwright install --with-deps chromium` to bake Chromium into the image. |
| `.gitignore` | Add `data/workspace/screenshots/*` and `!data/workspace/screenshots/.gitkeep`. |
| `data/workspace/screenshots/.gitkeep` | **NEW.** Empty placeholder to keep the directory in git. |
| `docs/TOOLS.md` | Append 3 entries to the summary table and per-tool details section (per the project rule). |
| `CLAUDE.md` | Refresh the tools table with the 3 new rows. |
| `README.md` | Add browser tools to the tool list. |

### Registry entry

```python
"browser": {
    "command": "npx",
    "args": [
        "-y", "@playwright/mcp@latest",
        "--browser", "chromium",
        "--headless",
        "--output-dir", str(workspace_root / "screenshots"),
    ],
    "transport": "stdio",
    "env": dict(os.environ),
    "cwd": str(workspace_root),
},
```

- `--browser chromium` pins the engine (we install only Chromium, not Firefox/Webkit).
- `--headless` runs without a UI.
- `--output-dir` is what makes `browser_take_screenshot` write into `data/workspace/screenshots/` instead of the MCP's default temp folder. The directory is created at registry startup time (the registry already does this for `workspace_root` — extend it to ensure the `screenshots/` subdir exists too).
- `cwd` matches the pattern from the filesystem server.

### Selector module shape

```python
# app/agent/tools/mcp_clients/browser_client.py
from app.agent.tools.mcp_clients.registry import select_tool

NAVIGATE_TOOL_NAME = "browser_navigate"
SNAPSHOT_TOOL_NAME = "browser_snapshot"
SCREENSHOT_TOOL_NAME = "browser_take_screenshot"

browser_navigate_tool = select_tool(NAVIGATE_TOOL_NAME, "Playwright Browser")
browser_snapshot_tool = select_tool(SNAPSHOT_TOOL_NAME, "Playwright Browser")
browser_screenshot_tool = select_tool(SCREENSHOT_TOOL_NAME, "Playwright Browser")
```

### Updated `READ_ONLY_TOOLS`

```python
READ_ONLY_TOOLS: set[str] = {
    "read_query",
    "yfinance_get_ticker_info",
    "yfinance_get_price_history",
    "yfinance_get_ticker_news",
    "read_text_file",
    "list_directory",
    "browser_navigate",
    "browser_snapshot",
    "browser_take_screenshot",
}
```

Final tool count: **11** (was 8). Read-only count: **9** (was 6). Side-effect / gated count: **2** unchanged (`send_email`, `write_file`).

## Data flow — NVDIA news deep-dive

```
User: "Why did NVDIA drop 8% today?"
  → rag → grader → generate
  → yfinance_get_ticker_info("NVDIA")      [RO]
  → yfinance_get_ticker_news("NVDIA")      [RO]
  → browser_navigate(top_news_url)        [RO]  (spawns Chromium, persistent)
  → browser_snapshot()                    [RO]  (returns accessibility tree)
  → browser_take_screenshot("nvda-evidence.png")   [RO]  (writes to screenshots/)
  → write_file("nvda_brief.md", brief)    [GATED — user approves]
  → final answer with file path + screenshot reference
```

Five new tool calls, zero new interrupts. The single HITL gate is at the moment the agent persists the brief to disk.

## Data flow — Competitor pricing watch

```
User: "Has anything changed on our competitors' pricing pages?"
(user has dropped competitors.csv into data/workspace/)

  → list_directory(".")                                           [RO]
  → read_text_file("competitors.csv")                             [RO]
  → read_query("SELECT * FROM pricing_snapshots WHERE date=...")  [RO]
  → for each competitor:
      browser_navigate(pricing_url)                               [RO]
      browser_snapshot()                                          [RO]
      browser_take_screenshot("acme-2026-05-12.png")              [RO]
  → write_file("pricing_changes_2026-05-12.md", brief)            [GATED]
  → send_email(to=sales, subject, body)                           [GATED]
  → final answer
```

Hits 7 of the 8 prior tools plus the 3 new ones in a single task. Two HITL gates — both at moments where a side-effect is about to leave the workspace (file persisted, email sent).

## Error handling

- **Navigation timeout** (Playwright default 30s): the MCP returns an error string; `ToolNode` surfaces it as a `ToolMessage` with `is_error=True`; the LLM either retries with a different URL, falls back to Tavily, or tells the user it couldn't reach the source.
- **Chromium crash** (rare): the MCP subprocess dies. The next tool call re-spawns a fresh subprocess via `langchain-mcp-adapters`'s per-call subprocess model — the LLM sees a one-off failure, retries cleanly.
- **Invalid URL** (404, DNS failure): same path as timeout — error string back through `ToolMessage`.
- **Disk write failure on screenshot** (workspace not writable): MCP returns an error; agent treats it the same as a tool failure and reports up.

No new error-recovery prompts needed — the existing `ERROR_RECOVERY_PROMPT` in `app/agent/prompts/system.py` already covers "tool returned an error, decide what to do."

## Documentation deliverables

Per the project rule in `CLAUDE.md`, every tool addition must update `docs/TOOLS.md` with a *what* and *why* entry. The three new rows:

| Tool | Why we have it |
|---|---|
| `browser_navigate` | The agent needs to reach pages Tavily snippets and yfinance metadata can't — full article bodies, investor-relations pages, JS-rendered content. |
| `browser_snapshot` | Returns the page as an accessibility tree, not raw HTML — structured text + element refs that the LLM can read cleanly without token-wasting markup. |
| `browser_take_screenshot` | Captures visual evidence of what the agent saw, persisted into the workspace alongside briefs. Builds trust when a human reviews a write_file or send_email proposal. |

Plus tools-table refresh in `CLAUDE.md` and `README.md`.
