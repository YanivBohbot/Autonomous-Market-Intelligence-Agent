# Playwright MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Microsoft's `@playwright/mcp` as a third Node-based MCP server in the existing `MultiServerMCPClient` registry, exposing 3 read-only browser tools (`browser_navigate`, `browser_snapshot`, `browser_take_screenshot`) with screenshots persisted into `data/workspace/screenshots/`.

**Architecture:** One new entry in `_server_config()` in `registry.py`, one new selector module (`browser_client.py`) that mirrors the shape of `filesystem_client.py`, and `READ_ONLY_TOOLS` extended to bypass the HITL gate for all 3 browser tools. The graph topology is unchanged. Chromium is baked into the Docker image at build time.

**Tech Stack:** Python 3.12, `langchain-mcp-adapters` (already installed), `langgraph`, `mcp`, Node 20 (already installed), `@playwright/mcp` (new, fetched via `npx`), Chromium (installed at Docker build time).

**Source spec:** `docs/superpowers/specs/2026-05-12-playwright-mcp-design.md`

**User preferences carried in:**
- Tests are deferred. Each task ends with the **regression gate** (`uv run pytest tests/ -v`) which must keep the current count of **18 passed, 1 failed** (`test_health_returns_ok` is the pre-existing fail and is unrelated). No new tests are added.
- Prompts and user-facing strings in English.
- Atomic-batch HITL semantics preserved (no changes to `approval_node`).
- Every tool added to `TOOLS` gets an entry in `docs/TOOLS.md` (project rule in `CLAUDE.md`).

**File structure (target):**

```
market-intelligence-agent/
├── app/
│   └── agent/
│       ├── prompts/system.py             # MODIFY — add browser tools to roster + 🌐 BROWSER GUIDELINES section
│       └── tools/
│           ├── __init__.py               # MODIFY — wire 3 new tools, refresh READ_ONLY_TOOLS
│           └── mcp_clients/
│               ├── registry.py           # MODIFY — add "browser" server to _server_config()
│               └── browser_client.py     # CREATE — selects 3 browser tools from registry
├── data/workspace/screenshots/.gitkeep   # CREATE
├── docs/TOOLS.md                         # MODIFY — append 3 entries
├── CLAUDE.md                             # MODIFY — refresh tools table
├── README.md                             # MODIFY — mention browser capability
├── Dockerfile                            # MODIFY — install Chromium via `npx playwright install`
└── .gitignore                            # MODIFY — keep workspace/screenshots/.gitkeep, ignore the rest
```

`docker-compose.yml` already mounts `./data:/app/data`, so `data/workspace/screenshots/` is automatically persisted in containers without any compose changes.

**Tool-name decisions:** the registry uses **no controller-side prefix** (consistent with subsystems #1 and #2 after their cleanup). Microsoft's `@playwright/mcp` self-namespaces every tool with `browser_*`, so collisions are impossible. Final tool names exposed to the LLM:

| Name | Read-only? | Backend |
|---|---|---|
| `browser_navigate` | yes | `@playwright/mcp` (Node, stdio) |
| `browser_snapshot` | yes | same |
| `browser_take_screenshot` | yes | same |

Final tool count: **11** (was 8). `READ_ONLY_TOOLS` size: **9** (was 6). Gated/side-effect: **2** unchanged (`send_email`, `write_file`).

---

## Task 1: Create the screenshots directory and update `.gitignore`

**Files:**
- Create: `market-intelligence-agent/data/workspace/screenshots/.gitkeep`
- Modify: `market-intelligence-agent/.gitignore`

- [ ] **Step 1: Create the screenshots directory and its `.gitkeep`**

From the project root:

```bash
mkdir -p "market-intelligence-agent/data/workspace/screenshots"
touch "market-intelligence-agent/data/workspace/screenshots/.gitkeep"
```

The `.gitkeep` file is empty — it just keeps the directory in git.

- [ ] **Step 2: Update `.gitignore` to keep `.gitkeep` but ignore everything else under `screenshots/`**

Open `market-intelligence-agent/.gitignore`. Locate the existing block:

```
# Agent workspace — keep the folder, ignore its contents
data/workspace/*
!data/workspace/.gitkeep
```

Replace it with the version below (adds the screenshots subfolder rules — the `data/workspace/*` glob doesn't recurse, so the screenshots subfolder needs its own pair):

```
# Agent workspace — keep the folder, ignore its contents
data/workspace/*
!data/workspace/.gitkeep
!data/workspace/screenshots/
data/workspace/screenshots/*
!data/workspace/screenshots/.gitkeep
```

- [ ] **Step 3: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. `.gitkeep`/`.gitignore` changes don't affect pytest.

- [ ] **Step 4: Commit**

```bash
git add market-intelligence-agent/data/workspace/screenshots/.gitkeep \
        market-intelligence-agent/.gitignore
git commit -m "feat(playwright-mcp): add data/workspace/screenshots/ directory"
```

---

## Task 2: Bake Chromium into the Docker image

**Files:**
- Modify: `market-intelligence-agent/Dockerfile`

- [ ] **Step 1: Add the Chromium install step after the existing filesystem-MCP pre-pull**

Open `market-intelligence-agent/Dockerfile`. Locate this line (added by subsystem #2):

```dockerfile
RUN npx -y @modelcontextprotocol/server-filesystem --help >/dev/null 2>&1 || true
```

Right after that line, add the Chromium install step:

```dockerfile

# Install Chromium for @playwright/mcp. `--with-deps` brings in the shared libraries
# (libnss, libatk, fonts, etc.) that headless Chrome needs on Debian-slim.
RUN npx -y playwright@latest install --with-deps chromium

# Pre-pull the Playwright MCP server so the first request doesn't pay an npm install.
RUN npx -y @playwright/mcp@latest --help >/dev/null 2>&1 || true
```

The final file should look like:

```dockerfile
FROM python:3.12-slim

# Install Node.js + npm (provides npx) for MCP servers that ship as Node packages
# (@modelcontextprotocol/server-filesystem, @playwright/mcp).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /usr/local/bin/uv

WORKDIR /app

COPY . .

RUN uv sync --frozen --no-dev

# Pre-pull the filesystem MCP server so the first request doesn't pay an npm install.
RUN npx -y @modelcontextprotocol/server-filesystem --help >/dev/null 2>&1 || true

# Install Chromium for @playwright/mcp. `--with-deps` brings in the shared libraries
# (libnss, libatk, fonts, etc.) that headless Chrome needs on Debian-slim.
RUN npx -y playwright@latest install --with-deps chromium

# Pre-pull the Playwright MCP server so the first request doesn't pay an npm install.
RUN npx -y @playwright/mcp@latest --help >/dev/null 2>&1 || true

EXPOSE 8000 8080

CMD ["uv", "run", "uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Run the regression gate (no Docker rebuild required — code-only)**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. Dockerfile changes don't affect pytest.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/Dockerfile
git commit -m "feat(playwright-mcp): install Chromium + pre-pull @playwright/mcp in Docker image"
```

---

## Task 3: Register the browser server in `registry.py`

**Files:**
- Modify: `market-intelligence-agent/app/agent/tools/mcp_clients/registry.py`

- [ ] **Step 1: Extend `_server_config()` with the `"browser"` entry**

Open `market-intelligence-agent/app/agent/tools/mcp_clients/registry.py`. Locate the existing `_server_config()` function (around line 30). After the `workspace_root.mkdir(...)` line, add a new line to ensure the `screenshots/` subdirectory exists:

```python
    (workspace_root / "screenshots").mkdir(parents=True, exist_ok=True)
```

Then, inside the returned dict, append the `"browser"` entry after the existing `"filesystem"` entry. The full replacement for `_server_config()`:

```python
def _server_config() -> dict:
    """Build the MultiServerMCPClient server config. Centralised so adding a server
    means changing one dict, not three import sites."""
    workspace_root = settings.WORKSPACE_ROOT.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "screenshots").mkdir(parents=True, exist_ok=True)
    return {
        "crm": {
            "command": "uv",
            "args": ["run", "mcp-server-sqlite", "--db-path", "customers.db"],
            "transport": "stdio",
            "env": dict(os.environ),
        },
        "yfinance": {
            "command": "uv",
            "args": ["run", "yfmcp"],
            "transport": "stdio",
            "env": dict(os.environ),
        },
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", str(workspace_root)],
            "transport": "stdio",
            "env": dict(os.environ),
            # Run the filesystem server with cwd = workspace_root so the LLM can use
            # plain relative paths like "brief.md" (the system prompt promises this).
            # Without it, relative paths resolve to the calling process's cwd (project
            # root), which is outside the allowed directory and the server rejects them.
            "cwd": str(workspace_root),
        },
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
            # cwd = workspace_root so any relative path the LLM passes to
            # browser_take_screenshot lands inside the workspace, not the project root.
            "cwd": str(workspace_root),
        },
    }
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. Nothing imports the browser tools yet, but the registry now configures the browser server. If `npx` isn't available locally, this still doesn't run — `get_mcp_tools()` is `lru_cache`-d and only fires on first call.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/mcp_clients/registry.py
git commit -m "feat(playwright-mcp): register @playwright/mcp server in MCP registry"
```

---

## Task 4: Create `browser_client.py`

**Files:**
- Create: `market-intelligence-agent/app/agent/tools/mcp_clients/browser_client.py`

- [ ] **Step 1: Create `browser_client.py`**

Create `market-intelligence-agent/app/agent/tools/mcp_clients/browser_client.py` with:

```python
"""Playwright Browser MCP client — selects browser-server tools out of the shared registry.

Public symbols: `browser_navigate_tool`, `browser_snapshot_tool`,
`browser_screenshot_tool`. All three are read-only from the agent's perspective and
slot into READ_ONLY_TOOLS — they perform network reads and (for screenshots) write
into the dedicated `data/workspace/screenshots/` subfolder, away from user-facing
briefs in the workspace root.

Sandboxing is enforced by the @playwright/mcp server itself (headless Chromium,
no host filesystem access outside --output-dir).
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.agent.tools.mcp_clients.registry import select_tool

logger = logging.getLogger(__name__)

NAVIGATE_TOOL_NAME = "browser_navigate"
SNAPSHOT_TOOL_NAME = "browser_snapshot"
SCREENSHOT_TOOL_NAME = "browser_take_screenshot"

browser_navigate_tool: BaseTool = select_tool(NAVIGATE_TOOL_NAME, "Playwright Browser")
browser_snapshot_tool: BaseTool = select_tool(SNAPSHOT_TOOL_NAME, "Playwright Browser")
browser_screenshot_tool: BaseTool = select_tool(SCREENSHOT_TOOL_NAME, "Playwright Browser")
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. The browser client isn't imported anywhere yet, so pytest is unaffected even though `select_tool` would spawn the browser server if called.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/mcp_clients/browser_client.py
git commit -m "feat(playwright-mcp): add browser_client selecting 3 tools from registry"
```

---

## Task 5: Wire browser tools into `TOOLS` and extend `READ_ONLY_TOOLS`

**Files:**
- Modify: `market-intelligence-agent/app/agent/tools/__init__.py`

- [ ] **Step 1: Replace `__init__.py`**

Replace the entire contents of `market-intelligence-agent/app/agent/tools/__init__.py` with:

```python
from app.agent.tools.emails import send_email_tool
from app.agent.tools.mcp_clients.mcp_client import crm_tool
from app.agent.tools.mcp_clients.yfinance_client import (
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
)
from app.agent.tools.mcp_clients.filesystem_client import (
    fs_read_file_tool,
    fs_list_dir_tool,
    fs_write_file_tool,
)
from app.agent.tools.mcp_clients.browser_client import (
    browser_navigate_tool,
    browser_snapshot_tool,
    browser_screenshot_tool,
)

TOOLS = [
    send_email_tool,
    crm_tool,
    yf_quote_tool,
    yf_history_tool,
    yf_news_tool,
    fs_read_file_tool,
    fs_list_dir_tool,
    fs_write_file_tool,
    browser_navigate_tool,
    browser_snapshot_tool,
    browser_screenshot_tool,
]

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

__all__ = [
    "TOOLS",
    "READ_ONLY_TOOLS",
    "send_email_tool",
    "crm_tool",
    "yf_quote_tool",
    "yf_history_tool",
    "yf_news_tool",
    "fs_read_file_tool",
    "fs_list_dir_tool",
    "fs_write_file_tool",
    "browser_navigate_tool",
    "browser_snapshot_tool",
    "browser_screenshot_tool",
]
```

- [ ] **Step 2: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**. This is the first task that actually spawns the browser MCP server at import time (because the test suite imports `app.agent.tools`, which triggers `get_mcp_tools()`). If `npx` or Chromium isn't available locally, you'll see a clear `RuntimeError` from `select_tool` saying the browser tool wasn't found. Install Node 20+ and run `npx -y playwright install chromium` once, or run inside Docker.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/agent/tools/__init__.py
git commit -m "feat(playwright-mcp): expose 3 browser tools, extend READ_ONLY_TOOLS"
```

---

## Task 6: Update the system prompt for browser awareness

**Files:**
- Modify: `market-intelligence-agent/app/agent/prompts/system.py`

- [ ] **Step 1: Update the tool roster in `SYSTEM_PROMPT`**

Open `market-intelligence-agent/app/agent/prompts/system.py`. Locate the section that lists tools (the "🛠️ YOUR TOOLS" block). After the "Filesystem workspace" subsection (which ends with the `write_file` entry) and *before* the "Side effects (require human approval)" subsection, insert this new subsection:

```
Browser (read-only, headless Chromium via @playwright/mcp):
8. `browser_navigate` — load a URL in the headless browser (args: `url: str`). Always call this before snapshot/screenshot.
9. `browser_snapshot` — return the current page as an accessibility tree (structured text + element refs). Use this to read article bodies, pricing tables, transcripts — anything you would have asked a human to "look at on the page."
10. `browser_take_screenshot` — capture a PNG of the current page (args: optional `filename: str`, optional `fullPage: bool`). Files land in the `screenshots/` subfolder of the workspace; pass a filename like `"nvda-evidence.png"` to make it easy to reference.
```

Then renumber the existing "Side effects" entry that came after — if it was numbered `8` for `send_email`, change it to `11`.

- [ ] **Step 2: Add the 🌐 BROWSER GUIDELINES section**

In the same file, after the "📈 MARKET DATA GUIDELINES" section, append:

```
🌐 BROWSER GUIDELINES
- Use the browser when API data isn't enough — full article bodies, JS-rendered competitor pricing pages, investor-relations transcripts. Don't use it when `yfinance_get_ticker_news` or a Tavily snippet already answers the question.
- Always `browser_navigate` first; `browser_snapshot` and `browser_take_screenshot` operate on the page you most recently navigated to.
- The browser session persists across tool calls within the same conversation, so consecutive navigations reuse a warm Chromium subprocess. You don't need to "close" the browser.
- Screenshots are evidence captures, not the agent's main output. Save them with descriptive filenames (`acme-pricing-2026-05-12.png`) so a human reviewing the brief can find the matching image in `screenshots/`.
- If a navigation times out or returns an error, fall back to Tavily search or explain to the user that the source was unreachable — don't loop on the same URL.
```

- [ ] **Step 3: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**.

- [ ] **Step 4: Commit**

```bash
git add market-intelligence-agent/app/agent/prompts/system.py
git commit -m "feat(playwright-mcp): system prompt — browser tools + 🌐 BROWSER GUIDELINES"
```

---

## Task 7: Update `docs/TOOLS.md`, `CLAUDE.md`, and `README.md`

**Files:**
- Modify: `market-intelligence-agent/docs/TOOLS.md`
- Modify: `market-intelligence-agent/CLAUDE.md`
- Modify: `market-intelligence-agent/README.md`

- [ ] **Step 1: Append 3 rows to the summary table in `docs/TOOLS.md`**

Open `market-intelligence-agent/docs/TOOLS.md`. Locate the summary table — it currently ends with row 8 (`write_file`). After that row, append:

```markdown
| 9 | `browser_navigate` | read-only | MCP stdio → `@playwright/mcp` | url | Loads a URL in the headless Chromium controlled by the Playwright MCP server. Sets the active page for subsequent snapshot/screenshot calls. | Tavily snippets and yfinance metadata don't return article bodies — the browser lets the agent reach the actual page (paywalled-but-readable, JS-rendered, login-walled). |
| 10 | `browser_snapshot` | read-only | same | (none) | Returns the current page as an accessibility tree — structured text plus element refs like `button [ref=e2]`. | The "extract" capability for the browser. Returns LLM-friendly structured text instead of raw HTML, so the agent can read full article bodies, pricing tables, and earnings transcripts without burning tokens on markup. |
| 11 | `browser_take_screenshot` | read-only | same | filename (optional), fullPage (optional) | Captures a PNG of the current page, written to `data/workspace/screenshots/`. | Visual evidence of what the agent saw. Lets a human reviewer cross-check a brief or email proposal against the actual source before approving it. |
```

Then update the `READ_ONLY_TOOLS` line directly below the table — locate:

```
`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory"}` — the allowlist consulted by `approval_node` to skip the HITL interrupt for safe reads.
```

Replace it with:

```
`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot"}` — the allowlist consulted by `approval_node` to skip the HITL interrupt for safe reads.
```

- [ ] **Step 2: Append 3 per-tool detail sub-sections to `docs/TOOLS.md`**

In the same file, locate the "## Per-tool details" section. After the existing `### 8. write_file` sub-section, append:

```markdown
### 9. `browser_navigate`
- **File:** `app/agent/tools/mcp_clients/browser_client.py` (selects from registry)
- **What:** Spawns `@playwright/mcp` as a stdio subprocess (with headless Chromium), navigates the active browser tab to the given URL, returns page metadata.
- **Why:** The agent's reach was bounded by what Tavily snippets and yfinance metadata could surface. With `browser_navigate` it can open the actual Reuters article, the actual investor-relations page, the actual competitor pricing tier — and feed that into the synthesis step instead of guessing from headlines.

### 10. `browser_snapshot`
- **File:** same as `browser_navigate`
- **What:** Returns the current page as an accessibility tree — structured text plus element refs (`button [ref=e2]`, `link [ref=e3]`, etc.). No raw HTML.
- **Why:** This is the "extract text" capability. Accessibility-tree output is LLM-friendly: cheap on tokens, semantically labelled, ignores the markup soup. Pair with `browser_navigate` to do the equivalent of "open page X and read it to me."

### 11. `browser_take_screenshot`
- **File:** same as `browser_navigate`
- **What:** Captures a PNG of the current page. Saves into `data/workspace/screenshots/<filename>` via the server's `--output-dir` flag. Optional `fullPage` argument captures beyond the viewport.
- **Why:** Visual evidence for HITL review. When the agent proposes a `write_file` or `send_email`, attaching a screenshot reference (`see screenshots/acme-2026-05-12.png`) lets the human reviewer cross-check the claim against the source page in one click. Screenshots are bypassed by `READ_ONLY_TOOLS` — they go into a dedicated subfolder so the workspace root stays clean for user-facing briefs.
```

- [ ] **Step 3: Update `CLAUDE.md`**

Open `market-intelligence-agent/CLAUDE.md`. Locate the tools table — it currently ends with row `write_file`. After that row, append:

```markdown
| `browser_navigate` | `app/agent/tools/mcp_clients/browser_client.py` | read-only | MCP stdio client → `@playwright/mcp` → `browser_navigate(url)` (headless Chromium). |
| `browser_snapshot` | same | read-only | Returns the current page as an accessibility tree (LLM-friendly structured text). |
| `browser_take_screenshot` | same | read-only | Saves a PNG into `data/workspace/screenshots/`. |
```

Then update the `READ_ONLY_TOOLS` paragraph directly below the table. Locate:

```
`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory"}` is the allowlist consulted by `approval_node` to skip the interrupt for safe reads.
```

Replace it with:

```
`READ_ONLY_TOOLS = {"read_query", "yfinance_get_ticker_info", "yfinance_get_price_history", "yfinance_get_ticker_news", "read_text_file", "list_directory", "browser_navigate", "browser_snapshot", "browser_take_screenshot"}` is the allowlist consulted by `approval_node` to skip the interrupt for safe reads.
```

- [ ] **Step 4: Update the "Required `.env` keys" optional list in `CLAUDE.md`**

No new required keys are introduced — `@playwright/mcp` runs entirely from npx with no auth. No edit needed for this step beyond verifying that the existing optional-keys list (around line 43) still reads correctly with `WORKSPACE_ROOT (data/workspace)`. Skip if no change needed.

- [ ] **Step 5: Update `README.md`**

Open `market-intelligence-agent/README.md`. Locate the workspace section added by subsystem #2. After the existing paragraph that describes `data/workspace/`, append:

```markdown
The agent also has a headless browser via `@playwright/mcp` (`browser_navigate`, `browser_snapshot`, `browser_take_screenshot`). Use it to reach pages Tavily snippets can't — full article bodies, JS-rendered competitor pricing, investor-relations transcripts. Screenshots land in `data/workspace/screenshots/`.
```

- [ ] **Step 6: Run the regression gate**

Run: `cd market-intelligence-agent && uv run pytest tests/ -v`
Expected: **18 passed, 1 failed**.

- [ ] **Step 7: Commit**

```bash
git add market-intelligence-agent/docs/TOOLS.md \
        market-intelligence-agent/CLAUDE.md \
        market-intelligence-agent/README.md
git commit -m "docs(playwright-mcp): tools registry, CLAUDE.md table, README browser section"
```

---

## Self-review notes

**Spec coverage check:**
- Decision 1 (3 tools: navigate, snapshot, take_screenshot) → Tasks 4, 5. ✓
- Decision 2 (`@playwright/mcp` upstream) → Tasks 2, 3. ✓
- Decision 3 (persistent browser session, upstream default) → Task 3 (no explicit config — accepting the default is the implementation). ✓
- Decision 4 (Chromium baked into Docker at build time) → Task 2. ✓
- Decision 5 (screenshots at `data/workspace/screenshots/` via `--output-dir`) → Task 1 (dir + gitignore), Task 3 (`--output-dir` flag + mkdir). ✓
- Decision 6 (all 3 tools in `READ_ONLY_TOOLS`) → Task 5. ✓
- Architecture (one new registry entry + one new selector module mirroring filesystem_client.py) → Tasks 3, 4. ✓
- Documentation deliverables (TOOLS.md rows + per-tool details, CLAUDE.md table, README mention) → Task 7. ✓
- Error handling (timeouts/crashes surface as ToolMessage, no new prompts needed) → no task — the existing `ERROR_RECOVERY_PROMPT` already covers this, called out in the spec.

**Type / name consistency:**
- Upstream tool names `browser_navigate`, `browser_snapshot`, `browser_take_screenshot` — used identically in `browser_client.py`, `__init__.py`'s `READ_ONLY_TOOLS`, the system prompt, `docs/TOOLS.md`, and `CLAUDE.md`. ✓
- Public symbols `browser_navigate_tool`, `browser_snapshot_tool`, `browser_screenshot_tool` — used identically in `browser_client.py` and `__init__.py`'s `TOOLS` list + `__all__`. ✓
- `select_tool` from `registry` — already exists from subsystem #2 cleanup; used in Task 4. ✓

**Placeholder scan:** none. Every step has either complete code or an exact command.
