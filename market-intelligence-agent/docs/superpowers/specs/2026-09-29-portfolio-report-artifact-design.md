# Portfolio report artifacts (downloadable HTML briefs with charts), design

**Date:** 2026-09-29
**Status:** approved in brainstorming, awaiting spec review
**Program:** sub-project 3 of 5 in the CopilotKit program (see `docs/superpowers/specs/2026-09-24-copilotkit-foundation-design.md`):
1. foundation (shipped, `feature/copilotkit-foundation`);
2. rich displays (shipped, `docs/superpowers/specs/2026-09-27-copilotkit-rich-displays-design.md`);
3. **exports (this spec)** — the roadmap's placeholder name for the general capability; this spec covers its first concrete artifact, a portfolio brief;
4. imports;
5. data view.

## Goal

Today `write_file` only saves whatever raw text the LLM hands it, and the chat gives no way to retrieve what was written — the advisor has to know it exists and go find it outside the app. This sub-project gives the advisor a real deliverable: ask for a client's portfolio brief, get a **self-contained, downloadable HTML report** (positions table + a pie chart of position weights) with a **download button right in the chat**, the same visual seam `rich displays` already uses for screenshots and portfolio tables.

Two other artifact kinds were raised during brainstorming (CSV/JSON data export, a free-text follow-up note) and found to need **no new work**: a follow-up note is already just `write_file` with prose the advisor dictates, and a CSV/JSON export is a straightforward follow-up once the report-building pattern below exists (deferred, see below) — this spec's scope is the one that actually needs new code: a report **with a chart**.

## Decisions (from brainstorming)

1. **Charts need real math (arc angles, coordinates) — that's code, not the LLM.** Same reasoning already proven for `concentration_screen` and `client_portfolio`: an LLM asked to hand-write SVG path data for a pie chart is the same failure class as an LLM asked to sum a portfolio's market value itself. So report generation is a **new deterministic, read-only tool**, not a prompt instruction telling the LLM to format its own chart.
2. **One self-contained HTML file, not Markdown + a sibling image.** A chart embedded as a separate PNG referenced from Markdown means two files to keep together, awkward for a single "download" affordance. A single HTML file with an **inline SVG chart** (hand-computed arc geometry, no external image, no `matplotlib`/`weasyprint` dependency) opens cleanly in any browser and is one file to write, serve, and download.
3. **The tool loads its own data, mirroring `concentration_screen`/`client_portfolio`.** `generate_portfolio_report(client_name)` reuses `client_portfolio.py`'s `load_client_portfolio()` to resolve the client and fetch holdings + live prices itself — nothing for the LLM to copy in, so a report's numbers can't drift from what `client_portfolio` would show for the same client. It is read-only (no side effects) and returns the built HTML string plus a suggested path; **it does not write anything** — `write_file` remains the single, already-HITL-gated write path in this app, and the LLM relays the HTML string to it unedited.
4. **Lives in `portfolio_agent`, which also gets `write_file`.** The supervisor ends a turn as soon as a specialist gives a plain answer, so "compute the report, then save it" needs one specialist that can do both steps in the same turn rather than a two-hop handoff to `filesystem_agent` that depends on the router prompt reliably recognizing the answer as incomplete. `portfolio_agent` gets its own `HumanInTheLoopMiddleware(interrupt_on={"write_file"})`, identical to `filesystem_agent`'s existing one.
5. **Reports live in their own `reports/` subfolder**, mirroring how screenshots already live in `WORKSPACE_ROOT/screenshots/`. `generate_portfolio_report`'s suggested path is always `reports/<slug>-portfolio-brief-<date>.html`; the prompt tells the LLM to use that path as-is.
6. **The chat card is a download button, nothing more** — explicitly **not** an inline preview of the chart or table in the chat itself (that was raised and declined during brainstorming: real scope-adder, a different rendering problem, no clear need yet). A compact card: filename + a styled download link, the same visual family as the existing `ScreenshotCard`/`TickerInfoCard`.
7. **Explicitly deferred:** CSV/JSON export (a real follow-up once this pattern exists, but a separate concrete artifact — new sub-task, not bundled here); report types beyond the portfolio brief (e.g. a concentration-risk-only report, a multi-client summary); an inline chart/table preview inside the chat card.

## Backend design (Python)

### `app/agent/tools/portfolio_report.py` (new)

Pure, independently testable pieces, same spirit as `finance_calc.py`:

```python
def build_pie_chart_svg(positions: list[dict], *, size: int = 220) -> str:
    """positions: [{"ticker": str, "weight_pct": float}, ...] (already computed
    by compute_portfolio_metrics — this function does no math beyond turning
    weights into arc angles). Returns a standalone <svg>...</svg> string: one
    <path> arc per position plus a small ticker/percentage legend. Categorical
    colors from the dataviz skill's palette reference, so the chart matches
    this project's other charts (PortfolioPieChart.tsx) in spirit without
    depending on React. A single 100%-weight position renders as a full
    circle (an SVG arc can't express 360° as one path) — handled as an
    explicit special case, not a math edge case to stumble into."""

def build_portfolio_report_html(portfolio: dict, *, threshold_pct: float = 30.0) -> str:
    """portfolio: the exact dict compute_portfolio_metrics returns, plus the
    client_name load_client_portfolio adds. Renders a self-contained HTML
    document: inline <style> (print-friendly light theme — this is a
    client-facing document, not the chat's dark terminal UI), a positions
    table, build_pie_chart_svg()'s output, and a concentration note for any
    position whose own weight_pct (already computed, no re-fetch) exceeds
    threshold_pct. No external assets, no network calls -- opens standalone."""


class GeneratePortfolioReportInput(BaseModel):
    client_name: str = Field(description="Full or partial client name.")


@tool("generate_portfolio_report", args_schema=GeneratePortfolioReportInput)
async def generate_portfolio_report_tool(client_name: str) -> dict:
    """Build a downloadable HTML portfolio brief (positions table + weight
    pie chart) for a named client. Resolves the client and fetches holdings
    and live prices itself -- do NOT call client_portfolio or fetch prices
    first, just pass client_name. Returns {"client_name", "suggested_path"
    (always under "reports/"), "html"}. Pass the html value UNEDITED as
    write_file's content and suggested_path as its path to save it -- do not
    summarize, truncate, or reformat the HTML yourself."""
    # Reuses client_portfolio.load_client_portfolio(run_sql=..., get_price=...)
    # for data loading -- same MCP wiring pattern as client_portfolio_tool
    # and concentration_screen_tool.
```

Read-only (no side effects) → added to `READ_ONLY_TOOLS`.

### `app/agent/multi_agent/portfolio_agent.py` (extended)

- `_TOOLS` gains `generate_portfolio_report_tool` and `fs_write_file_tool` (the same `write_file` instance `filesystem_agent` already uses).
- `middleware` gains `HumanInTheLoopMiddleware(interrupt_on={"write_file"})`, placed the same way `filesystem_agent.py` places its own — after `base_middleware()`, before `market_desk_display` (display middleware must see the tool's real post-approval result).

### `app/agent/prompts/specialist_agent_prompts.py` (extended)

`PORTFOLIO_SYSTEM_PROMPT` gains tool #9 (`generate_portfolio_report`) and an instruction: for any "save/export/generate a brief or report" request about a named client, call `generate_portfolio_report` (it loads its own data — no `client_portfolio` call needed first), then `write_file` with its `html` and `suggested_path` verbatim. `write_file` itself gets a note mirroring `filesystem_agent`'s existing one (call it directly; the platform's approval card handles consent, don't pre-confirm in prose — the same fix already shipped for `filesystem_agent`).

### `app/api/routers/workspace.py` (extended)

```python
@router.get("/files/{filename}")
async def get_report_file(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    candidate = Path(settings.WORKSPACE_ROOT) / "reports" / safe_name
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(candidate, filename=safe_name)  # filename= forces Content-Disposition: attachment
```

Single location check (unlike the screenshot route's two-candidate check) — there is exactly one writer of `reports/*`, no cross-backend path disagreement to defend against. Media type is inferred by `FileResponse` from the extension.

### `app/agent/multi_agent/display.py` (extended)

```python
def normalize_report_file(text: str, args: dict) -> list[dict]:
    path = args.get("path", "")
    if not path.startswith("reports/"):
        return []  # a plain filesystem_agent write (e.g. notes.txt) -- not a report, no card
    filename = Path(path).name
    return [{"type": "report_file", "filename": filename, "url": f"/workspace/files/{filename}"}]

DISPLAY_NORMALIZERS["write_file"] = normalize_report_file
```

`write_file` is shared by `filesystem_agent` and (after this change) `portfolio_agent`; the `reports/` prefix check is what scopes the card to actual reports regardless of which specialist wrote the file. `market_desk_display` is already in `portfolio_agent`'s middleware list (added in the rich-displays sub-project) — no change needed there.

## Frontend design (`frontend/src/desk/displays/`)

- **`types.ts`**: add `{ type: "report_file"; filename: string; url: string }` to `DisplayPayload`.
- **`parseDisplay.ts`**: add a validator (`filename` and `url` both strings).
- **`ReportFileCard.tsx`** (new): a compact card — document icon, filename, a styled `<a href={url} download>Download</a>` button. Visual polish via the `frontend-design` skill at implementation time, matching the existing card family's dark-terminal styling (`ScreenshotCard`, `TickerInfoCard`).
- **`useToolDisplay.tsx`**: add `"write_file"` to `DISPLAYABLE_TOOLS` and a `"report_file"` case in `Rendered`'s switch, rendering `ReportFileCard`.

## Testing plan

- `build_pie_chart_svg`: angle math for 1/2/several positions, the 100%-single-position special case, no negative/NaN angles.
- `build_portfolio_report_html`: contains client name, exact copied numbers (not recomputed), a `<svg>` tag, a concentration note only when a position exceeds the threshold.
- `generate_portfolio_report_tool`: same fake `run_sql`/`get_price` harness as `test_client_portfolio.py`; asserts `suggested_path` starts with `"reports/"` and `html` round-trips through `build_portfolio_report_html`.
- `normalize_report_file`: fires only when `args["path"]` starts with `"reports/"`; empty otherwise.
- `workspace.py`: `GET /workspace/files/{filename}` serves from `reports/`, 404 when absent, `Path(...).name` strips `../`.
- `portfolio_agent.py`: tool list includes the two new entries; `HumanInTheLoopMiddleware.interrupt_on == {"write_file"}`.
- Frontend: `ReportFileCard.test.tsx` (renders filename + correct `href`), `useToolDisplay.test.tsx` updated to 9 displayable tools, `parseDisplay.test.ts` extended.
- Full backend (`uv run pytest tests/`) and frontend (`npx vitest run`) suites green before each commit, live-verified in Chrome before considering the sub-project done — same discipline as every other change this session.
