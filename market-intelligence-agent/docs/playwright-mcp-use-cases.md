# Playwright MCP — Use Cases

Pre-spec notes for subsystem #3. Captures the *why* before we formalize the design. When we brainstorm the spec, start from here.

## Why it earns a slot

Playwright MCP gives the agent a real browser it can drive — fetch, click, scroll, screenshot, extract. For a market-intelligence agent, that's the gap between "what the APIs hand me" and "what's actually on the page."

- **Tavily + yfinance cover the easy 60%.** Tavily returns search *snippets*, not full articles; yfinance gives structured price/news but no analyst commentary, earnings transcripts, or investor-relations pages. Playwright lets the agent open the actual source.
- **JavaScript-rendered pages.** Bloomberg, Seeking Alpha, investor portals render data via JS. Plain HTTP fetch returns an empty shell. Playwright executes the page.
- **Login-walled / paginated content.** Earnings call transcripts, SEC filings across pages, competitor dashboards behind free signups.
- **Screenshots for the human reviewer.** Attaching a screenshot of the source page to a HITL approval modal builds trust faster than a bare URL.
- **HITL fits cleanly.** `browser_navigate` / `browser_extract_text` are read-only (slot into `READ_ONLY_TOOLS`); `browser_click` / `browser_type` are side-effects, gated by `approval_node`.

**Tradeoff to flag in the spec:** Playwright is the heaviest MCP server so far — bundles Chromium (~300MB in Docker), per-call latency is seconds not milliseconds, and headless-browser sandboxing is its own attack surface.

---

## Example 1 — "Why did NVDA drop 8% today?"

**Current flow (without Playwright):**
1. `yfinance_get_ticker_info` → confirms the drop
2. `yfinance_get_ticker_news` → returns 5 headlines, but yfinance gives titles + URLs only, not body text
3. Tavily → snippets, often paywalled or truncated
4. Agent guesses at causation from headlines alone

**With Playwright:**
1. yfinance flags the drop + returns the top news URL (say, a Reuters article)
2. `browser_navigate(url)` → opens the article
3. `browser_extract_text()` → returns the full body
4. Agent now reads "Nvidia cut Q3 revenue guidance citing China export restrictions" — *actual* causation, not a guess
5. Agent writes a brief to `data/workspace/nvda_brief.md` (via `write_file`, HITL-gated)

The qualitative difference: headline-level vs. article-level reasoning.

---

## Example 2 — "Track our top 3 competitors' pricing changes"

This one is *impossible* without a browser. Competitor pricing pages are JS-rendered, sit behind login walls, or use anti-scraping on plain HTTP.

**Flow:**
1. User drops `competitors.csv` into `data/workspace/`
2. `read_text_file` → agent reads the list
3. For each competitor: `browser_navigate(pricing_url)` → `browser_extract_text()` → captures current tier prices
4. `read_query` against CRM → pulls last week's snapshot we stored
5. Agent diffs and writes `pricing_changes_2026-05-11.md` to the workspace
6. If anything changed: proposes `send_email` to the sales team → HITL approval → send

The kind of workflow analysts have hand-done for years. The agent automates the boring part; the human approves the email.

---

## Example 3 — Earnings call deep-dive

1. User: "Summarize Apple's Q2 earnings call"
2. `browser_navigate("https://investor.apple.com/...")` → opens the IR page
3. `browser_extract_text()` → pulls the transcript
4. Agent runs it through the LLM with a structured prompt ("extract guidance changes, capex commentary, AI mentions")
5. `write_file("aapl_q2_call.md", summary)` → HITL gate → persisted to workspace
6. Later sessions can `read_text_file` it without re-fetching

Transcripts are too long to live in message history alone — pairing Playwright (fetch) with filesystem MCP (persist) is the natural combo. Subsystem #2 enables subsystem #3.

---

## The pattern

Playwright = **input** side (read the live web). Filesystem = **storage** side (durable artifacts). HITL = **gate** (send_email, write_file, browser_click). Each subsystem we add unlocks workflows the previous ones couldn't reach.
