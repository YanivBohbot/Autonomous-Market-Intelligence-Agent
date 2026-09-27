# CopilotKit rich displays ("Market Desk" enrichment), design

**Date:** 2026-09-27
**Status:** approved in brainstorming, awaiting spec review
**Program:** sub-project 2 of 5 in the CopilotKit program (see `docs/superpowers/specs/2026-09-24-copilotkit-foundation-design.md`):
1. foundation (shipped, `feature/copilotkit-foundation`);
2. rich displays (this spec);
3. exports;
4. imports;
5. data view.

## Goal

Today, Market Desk's chat shows every tool call as CopilotKit's generic text card: the LLM's summary, nothing else. This sub-project adds structured, visual renders — tables, charts, screenshots, source cards — for the tools whose output is naturally visual, **in the same place in the chat** where the generic card shows today. No new screen, no new panel: this is a richer render of an existing seam (`useRenderTool`), for a wider set of tools than sub-project 1 touched.

It also adds two small CopilotKit-native conveniences to the same chat: starter suggestions and file attachments (landing on disk for the agent to read with existing tools — not the RAG/Excel import pipeline, which is sub-project 4's job).

## Decisions (from brainstorming)

1. **Displays covered (7 tools, 8 display types):**
   - `portfolio_metrics` → `portfolio_table` + `portfolio_chart` (two displays from one call)
   - `yfinance_get_price_history` → `price_chart`
   - `yfinance_get_ticker_info` → `ticker_info`
   - `yfinance_get_ticker_news` → `ticker_news`
   - `concentration_screen` → `concentration_alert`
   - `search_knowledge_base` → `rag_sources`
   - `browser_take_screenshot` → `screenshot`
2. **Where the data is shaped: a single backend middleware, not per-tool changes.**
   - `search_knowledge_base_tool` and `browser_screenshot_tool` are the *same instances* used by the single-agent graph (`/stream`, Streamlit, voice) — confirmed by reading `app/agent/tools/__init__.py` and the multi-agent specialist files, which import these exact tool objects. Reshaping a tool's own return value would change what Streamlit and voice see too.
   - A middleware scoped to the multi-agent graph only (not present in the single-agent graph at all) is the correct seam: it reshapes the `ToolMessage` *after* the shared tool runs, only inside Market Desk's own agents.
   - One middleware, one explicit registry (`dict[str, Normalizer]`), not a per-tool `if/elif`. Every displayable tool goes through the same contract, including the 3 tools whose raw output already happens to be structured JSON (`portfolio_metrics`, `concentration_screen`) — so the wire contract with the frontend never depends on a tool's internal JSON shape, which could change for reasons unrelated to display (e.g. a field renamed for the LLM's benefit).
3. **The wire contract: one envelope, always a list.**
   ```json
   {"summary": "<text the LLM already wrote>", "displays": [ {"type": "...", ...}, ... ]}
   ```
   `summary` is what the LLM reads to write its answer (so the model's reasoning is unaffected). `displays` is what the frontend renders. Always a list — even a single display is `displays: [...]` — so the frontend has exactly one parsing shape regardless of tool.
4. **Placement: inside the chat, not a side panel.** Same mechanism as sub-project 1's approval cards (`useInterrupt`) and the same architectural seam CopilotKit already exposes for tool calls (`useRenderTool`), one registration per tool name.
5. **Two small additions to the same chat, same scope boundary respected:**
   - **Starter suggestions** (`useConfigureSuggestions`): a short static list of example questions, frontend-only, no backend change.
   - **File attachments** (`CopilotChat`'s `attachments` prop): the user can attach a file from the chat input. It lands on disk under `data/workspace/uploads/` via a new endpoint, and the agent is told its path in plain text so it can read it with the **already-existing** `read_text_file`/`list_directory` tools. **Explicitly not** RAG ingestion into Pinecone, not Excel-to-DB with a validated preview — that is sub-project 4's job, with its own approval flow.
6. **Explicitly deferred to their own sub-projects:** exports, imports (beyond the plain landing-on-disk above), the data view page, and the 7 extra roadmap ideas (watchlist alerts, what-if, morning brief, company comparison, conversation history, cost per question, feedback).

## Backend design (Python)

### `app/agent/multi_agent/display.py` (new)

```python
DisplayList = list[dict]          # each dict: {"type": str, ...}
Normalizer = Callable[[str], tuple[str, DisplayList]]   # (raw ToolMessage.content) -> (summary, displays)

DISPLAY_NORMALIZERS: dict[str, Normalizer] = {
    "portfolio_metrics": normalize_portfolio,
    "yfinance_get_price_history": normalize_price_history,
    "yfinance_get_ticker_info": normalize_ticker_info,
    "yfinance_get_ticker_news": normalize_ticker_news,
    "concentration_screen": normalize_concentration,
    "search_knowledge_base": normalize_rag_sources,
    "browser_take_screenshot": normalize_screenshot,
}
```

- **`MarketDeskDisplayMiddleware(AgentMiddleware)`**: `wrap_tool_call`/`awrap_tool_call` look up `request.tool_call["name"]` in `DISPLAY_NORMALIZERS`; if present and the handler's result is a `ToolMessage`, call the normalizer on `result.content`, and replace `result.content` with `json.dumps({"summary": summary, "displays": displays})`. Unregistered tools pass through untouched — their `ToolMessage.content` is exactly what it is today.
- A normalizer that raises or returns something that doesn't validate **fails open**: the middleware catches the exception, logs it, and leaves `result.content` unchanged (the LLM still gets its text; the frontend falls back to CopilotKit's default card). A display bug never breaks the answer.
- Applied in `common.py`'s middleware lists for exactly the 4 specialists that own a displayable tool: `portfolio_agent`, `finance_agent`, `rag_agent`, `browser_agent`. `email_agent`, `memory_agent`, `filesystem_agent` are untouched.
- **Verified inputs** (existing code, no guessing):
  - `portfolio_metrics` → `compute_portfolio_metrics()`'s dict: positions with `ticker, shares, avg_cost, price, market_value, cost_basis, unrealized_pnl, unrealized_pnl_pct, weight_pct, sector`, plus portfolio totals.
  - `concentration_screen` → `screen_clients()`'s dict: `breaches: [{label, ticker, weight_pct, market_value, portfolio_market_value}], screened_labels, prices`.
  - `browser_take_screenshot` → confirmed filename served at `GET /workspace/screenshots/{filename}` (existing `workspace.py`).
  - `search_knowledge_base` → text chunks prefixed `[Source: filename, page N]` (existing convention, `knowledge_base.py`).
- **Not yet verified — implementation-plan spike required:** `yfinance_get_ticker_info` and `yfinance_get_ticker_news` come from the third-party `yfmcp` MCP server; this codebase has no fixture of their exact JSON keys. The plan's first task for these two normalizers captures one real response (via a live tool call, same pattern as sub-project 1's pre-plan spike) before the parser is written, and pins the shape with a fixture-based test — never guessed field names in this spec.

### `app/api/routers/copilot.py` (extended)

- **`POST /copilot/uploads`** (new, gated by `COPILOT_ENABLED` like the rest of this router): accepts a multipart file, sanitizes the filename the same way `workspace.py`'s screenshot route already does (`Path(filename).name`, stripping any `..`/directory components), prefixes it with a short random id to avoid collisions (`f"{uuid4().hex[:8]}_{safe_name}"`), writes it to `WORKSPACE_ROOT/uploads/`, and returns `{"path": "uploads/<name>"}`. Re-checks size server-side (defense in depth — the frontend's `maxSize` is client-side only).
- No GET route is added for uploads: the agent reads the file back through the **existing** `read_text_file`/`list_directory` tools, which already resolve paths under `WORKSPACE_ROOT`. Only screenshots need a GET route, because the *browser* renders those, not the agent.

## Frontend design (`frontend/src/`)

### Integration point — unchanged from sub-project 1

```tsx
function DeskBody({ threadId }: { threadId: string }) {
  useDeskInterrupt();     // sub-project 1: approval cards
  useToolDisplay();       // new: tables, charts, screenshots, sources
  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <CopilotChat agentId={MARKET_DESK_AGENT_ID} threadId={threadId} attachments={UPLOAD_CONFIG} className="h-full" />
      </main>
      <DeskActivityRail />
    </div>
  );
}
```

No change to `App.tsx`, `Header.tsx`, `DeskActivityRail.tsx`, `ApprovalPanel.tsx`, or Classic mode.

### `frontend/src/desk/displays/` (new folder)

| File | Role |
|---|---|
| `types.ts` | `DisplayPayload` — a discriminated union on `type`, one variant per display type above. `DisplayEnvelope = {summary: string; displays: DisplayPayload[]}`. |
| `parseDisplay.ts` | Pure: `unknown -> DisplayEnvelope \| null`. Validates `displays` is an array; each entry with a *known* `type` and valid fields is kept, an entry with an unknown `type` or missing fields is dropped (never throws). If the whole envelope doesn't parse (not JSON, no `displays` array), returns `null` — the component then falls back to CopilotKit's default tool-call card. |
| `useToolDisplay.tsx` | One hook, called once in `DeskBody`. Registers one `useRenderTool({name, render})` per entry in a frontend mirror of the backend registry (7 tool names). Each render calls `parseDisplay(result)` and maps `displays` to components; `null` renders CopilotKit's default. |
| `PortfolioTable.tsx`, `PortfolioPieChart.tsx`, `PriceChart.tsx`, `TickerInfoCard.tsx`, `TickerNewsList.tsx`, `ConcentrationAlert.tsx`, `ScreenshotCard.tsx`, `RagSourceCards.tsx` | One component per display type. Reuse the existing terminal palette (`terminal-accent`, `terminal-warn`, `terminal-danger`, `terminal-muted`) — no new colors. |

- **Charts:** new dependency `recharts` (React 18-compatible) for `PortfolioPieChart` and `PriceChart`.
- **`ScreenshotCard`**: an `<img>` pointing at the existing `GET /workspace/screenshots/{filename}`.
- **`RagSourceCards`**: one card per source (`filename`, `page`, `excerpt`), collapsed by default, click to expand.

### Suggestions

```tsx
useConfigureSuggestions({
  suggestions: [
    { title: "Portfolio value", message: "What is the total value of <client>'s portfolio?" },
    { title: "Stock price", message: "What is AAPL trading at?" },
    { title: "Concentration risk", message: "Are any clients over-concentrated in one stock?" },
  ],
}, []);
```
Called once in `DeskBody`, agent-scoped implicitly by the chat's own `agentId`. Frontend-only, no backend change.

### File attachments

```tsx
const UPLOAD_CONFIG: AttachmentsConfig = {
  enabled: true,
  maxSize: 20 * 1024 * 1024,
  onUpload: async (file) => {
    const { path } = await uploadToWorkspace(file);   // POST /copilot/uploads, multipart
    return { type: "url", value: path, metadata: { filename: file.name } };
  },
};
```
- `uploadToWorkspace` is a small new function in `src/desk/` (or `src/lib/api.ts`) doing a plain `fetch(..., {method: "POST", body: formData})`.
- **How the agent learns the file exists:** CopilotKit turns the attachment into a binary/document content part on the outgoing message, whose handling by `ag-ui-langgraph`'s inbound conversion isn't something this codebase controls or has verified. To make this deterministic regardless of that, the frontend **also appends a plain-text line to the outgoing message** when an attachment is present: `\n\n(Uploaded file: uploads/<name> — read it with read_text_file if relevant.)`. The specialist then sees an ordinary text instruction it can act on with existing tools, with no dependency on how the binary part is handled upstream.

## Testing

**Python (pytest):**
- `display.py`'s 7 normalizers, each tested on the real, verified shapes above (or the captured `yfmcp` fixture for the 2 pending ones) — pure function tests, no LLM, no tool execution.
- `MarketDeskDisplayMiddleware`: a registered tool's `ToolMessage.content` becomes the envelope; an unregistered tool's content is untouched; a normalizer that raises leaves the original content untouched (fail-open) and logs.
- `test_copilot_endpoint.py`: an end-to-end run with a fake `portfolio_metrics` result asserts the `TOOL_CALL_RESULT` event's content is the envelope JSON.
- `POST /copilot/uploads`: saves a file under `uploads/`, filename traversal (`../../etc/passwd`) is stripped to a safe name, oversized upload is rejected, disabled when `COPILOT_ENABLED=false` (404, consistent with the rest of the router).

**Frontend (Vitest):**
- `parseDisplay.test.ts`: all 8 display types parse correctly; unknown `type` in the list is dropped, not thrown; a non-object payload returns `null`.
- One test file per display component, with representative fixture data per type.
- `useToolDisplay` wiring: a smoke test that a mocked tool-call render for each of the 7 names invokes the matching component (mirrors sub-project 1's `DeskActivityRail.test.tsx` pattern of mocking `useAgent`/`useRenderTool`).
- Attachment flow: attaching a file appends the plain-text upload note to the outgoing message (unit test on the composed message, not a live upload).

**Live pass (Playwright, one at the end):** a portfolio question (table + pie chart render), a price-history question (line chart), a RAG question (source cards), a screenshot request (image renders), a suggestion click, and one file attachment round-trip (message includes the upload note).

## Out of scope

- RAG ingestion of an uploaded PDF into Pinecone, Excel-to-DB import with a validated preview (sub-project 4).
- Report/Excel export (sub-project 3).
- The clients/portfolios/documents data view page (sub-project 5).
- The 7 extra roadmap ideas.
- Rendering the uploaded file itself back in the chat (only text/document tools read it; no inline preview).
