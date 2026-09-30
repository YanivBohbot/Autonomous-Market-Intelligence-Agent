# Portfolio Report: Excel Artifact & Atomic Save — Design

**Status:** Approved by user in conversation 2026-09-30. Ready for implementation planning.

## Motivation

The portfolio-report-artifact feature shipped earlier in this session (`docs/superpowers/specs/2026-09-29-portfolio-report-artifact-design.md`) generates a self-contained HTML file with an inline hand-computed SVG pie chart. `generate_portfolio_report_tool` returns `{client_name, suggested_path, html}`, and `portfolio_agent`'s system prompt instructs the LLM to pass `html`/`suggested_path` **unedited** into the generic `write_file` tool.

A final code review of that feature (this session, commit range `2d172e2..d416f9a`) flagged that this retyping step has no integrity check: the LLM copying a multi-KB HTML string token-for-token into a tool argument is exactly the class of "LLM asked to reproduce data exactly" risk the rest of this codebase's deterministic-tool pattern exists to eliminate (`client_portfolio`, `concentration_screen`, and `generate_portfolio_report`'s own chart math all avoid trusting the LLM with arithmetic or generation — the HTML retyping step re-introduced the same risk one layer up). The HITL approval card shows the raw HTML, which no advisor will realistically proofread before approving.

Separately, the user observed that a `.xlsx` deliverable — native chart, styled table, opens directly in Excel/Sheets — is a more idiomatic artifact for a wealth-management advisor than a browser-rendered HTML file, and asked to explore switching formats.

This design does both, together, because they share a root fix: **make the report-writing tool own the entire load → build → write path itself, with no content ever passing through the LLM.**

## Scope

**In scope:** replacing the HTML+SVG report with a generated `.xlsx` file (styled table + native pie chart), and collapsing the current two-step `generate_portfolio_report` → `write_file` flow into one atomic, self-writing tool.

**Out of scope (separate future design):** emailing the report as an attachment. `send_email` is currently text-only (SES `SendEmail`, no attachment support), and `portfolio_agent` has no email tool today — that capability, its recipient-safety guard, and its UI trigger need their own brainstorm. Not addressed here.

## Architecture

One new tool, `save_portfolio_report_tool(client_name: str)`, replaces both `generate_portfolio_report_tool` and the `write_file` call `portfolio_agent` currently makes for a report:

1. Resolves the client and loads holdings + live prices — reuses `load_client_portfolio` (`app/agent/tools/client_portfolio.py`), unchanged.
2. Builds the `.xlsx` file **in memory** via a new pure function `build_portfolio_report_xlsx(portfolio: dict) -> bytes` (`xlsxwriter`, in-memory buffer — `xlsxwriter.Workbook(BytesIO(), ...)`).
3. Writes those bytes directly to `WORKSPACE_ROOT/reports/<slug>-portfolio-brief-<date>.xlsx`, creating the `reports/` directory if needed (`Path.mkdir(parents=True, exist_ok=True)` immediately before the write — every call, not just at startup).
4. Returns `{"client_name": ..., "filename": ...}` (no bytes, no HTML, nothing for an LLM to reproduce) or `{"error": ...}` on a zero/multiple client match (same shape `load_client_portfolio` already produces).

The tool is still HITL-gated (`HumanInTheLoopMiddleware(interrupt_on={"save_portfolio_report": True})` on `portfolio_agent`), but since `HumanInTheLoopMiddleware` interrupts **before** the tool executes, the approval card can only ever show the tool call's *arguments* (`client_name`), never a result that doesn't exist yet. The user explicitly chose, after discussing the alternative (having the LLM call the existing read-only `client_portfolio` tool first so its table/chart card renders before the save prompt), to accept a plain action-confirmation card with no data summary: **"Save the portfolio report for Margaret Collins as an .xlsx file?"** — simpler, one tool call, one approval, no preceding display step required.

## Dependency

**`xlsxwriter`** (runtime dependency, added to `pyproject.toml` `dependencies` and `requirements.agentcore.txt`) — write-only, no read/edit support, but this codebase never needs to re-read a generated report (each one is rebuilt fresh from the database every time), and its chart/formatting API is more ergonomic than `openpyxl`'s for one-shot generation. `openpyxl` was considered and rejected as the primary dependency for this reason.

**`openpyxl`** (test-only, added to `pyproject.toml`'s `[dependency-groups] dev`) — used exclusively by `test_portfolio_report.py` to open and assert against the bytes `build_portfolio_report_xlsx` produces (cell values, chart presence), since `xlsxwriter` cannot read its own output. Never imported by production code, never in `requirements.agentcore.txt`.

## Data Flow

```
Human: "Generate a portfolio report for Margaret Collins and save it"
  -> portfolio_agent calls save_portfolio_report_tool(client_name="Margaret Collins")
  -> HITL pause: "Save the portfolio report for Margaret Collins as an .xlsx file?"
  -> approve
  -> load_client_portfolio (holdings + live prices, unchanged)
  -> build_portfolio_report_xlsx(portfolio) -> bytes (in a thread, see below)
  -> reports/margaret-collins-portfolio-brief-2026-09-30.xlsx written
  -> {"client_name": "Margaret Collins", "filename": "margaret-collins-portfolio-brief-2026-09-30.xlsx"}
  -> display normalizer -> report_file envelope -> ReportFileCard renders, Download works
```

A reject cancels the whole call — nothing is written, matching the existing `write_file` HITL contract.

The existing deterministic supervisor sticky-routing rule (added this session, `app/agent/multi_agent/supervisor.py`) is unaffected: it keys off `last_agent == "portfolio_agent"` plus report/save language in consecutive messages, not off which specific tool portfolio_agent calls.

## Error Handling

- Zero/multiple client match: `{"error": ...}` — identical shape to today, `load_client_portfolio`'s own error, unchanged.
- `reports/` missing: created on every call, immediately before the write (`mkdir(parents=True, exist_ok=True)`) — closes the ENOENT-class silent-failure bug found in this session's final review permanently, rather than relying on `registry.py`'s startup-time pre-creation (which only ever ran once and couldn't recover if the directory was later removed).
- Any write failure (disk full, permissions, etc.): a normal Python exception, caught by the existing `ToolErrorMiddleware` and converted to `ToolMessage(status="error")`. Because of this session's other final-review fix, `MarketDeskDisplayMiddleware._envelope` now skips normalization entirely for an error-status result — no fake success card is possible, by construction, not by convention.
- `xlsxwriter`'s `Workbook.close()` (the actual write) is a synchronous, blocking call inside an `async` tool function in a fully async graph — run it via `asyncio.to_thread` so it never blocks the event loop.
- Client names with filesystem-unsafe characters (e.g. `O'Brien`): reuses the existing, already-tested `_slugify`, unchanged.

## Components Touched

- **`app/agent/tools/portfolio_report.py`** — `build_pie_chart_svg`, `build_portfolio_report_html`, `generate_portfolio_report`, `generate_portfolio_report_tool`, `GeneratePortfolioReportInput` all removed. Replaced by `build_portfolio_report_xlsx(portfolio: dict) -> bytes`, an async core `save_portfolio_report(*, run_sql, get_price, client_name) -> dict` (same self-loading pattern as the function it replaces — mirrors `client_portfolio.py`/`concentration.py`), `SavePortfolioReportInput(BaseModel)`, and `save_portfolio_report_tool`.
- **`app/agent/multi_agent/portfolio_agent.py`** — `_TOOLS` drops `generate_portfolio_report_tool` and `fs_write_file_tool`, adds `save_portfolio_report_tool`. `HumanInTheLoopMiddleware(interrupt_on={"write_file": True})` becomes `interrupt_on={"save_portfolio_report": True}`.
- **`app/agent/prompts/specialist_agent_prompts.py`** — `PORTFOLIO_SYSTEM_PROMPT`'s tool-list entries for `generate_portfolio_report` (#9) and `write_file` (#10) collapse into one entry for `save_portfolio_report`; the "Report recipe" instruction bullet and its worked example are rewritten for the one-call flow (no more "call X then pass its output unedited to Y").
- **`app/agent/multi_agent/display.py`** — `normalize_report_file` (keyed on `write_file` + `args["path"].startswith("reports/")`) is replaced by a new normalizer keyed on `save_portfolio_report`, reading `filename` from the tool's **result** (there is no `path` argument anymore — the only argument is `client_name`). `DISPLAY_NORMALIZERS["write_file"]` entry is removed entirely: `write_file` reverts to no special-casing at all now that portfolio_agent never calls it, exactly as it was before the original report feature existed.
- **`frontend/src/desk/displays/useToolDisplay.tsx`** — `DISPLAYABLE_TOOLS` drops `"write_file"`, adds `"save_portfolio_report"`. `ReportFileCard`'s own contract (`{filename, url}`) and the `report_file` display-payload type are unchanged — no frontend component changes needed.
- **`app/api/routers/workspace.py`** (`GET /workspace/files/{filename}`) — unchanged; `FileResponse` content-type detection works for `.xlsx` the same as `.html`.
- **`pyproject.toml`** — `xlsxwriter` added to `dependencies`; `openpyxl` added to `[dependency-groups].dev`.
- **`requirements.agentcore.txt`** — `xlsxwriter` pinned to the `uv.lock` version (per `CLAUDE.md`'s dependency rule); `openpyxl` never added (test-only).
- **`docs/TOOLS.md`** — `generate_portfolio_report` row/section replaced with `save_portfolio_report` (per `CLAUDE.md`'s "keep TOOLS.md in sync" project rule).

## Testing

- `build_portfolio_report_xlsx`: pure-function tests reopen the returned bytes with `openpyxl` (test-only) and assert cell values, sheet structure, and that a chart object exists — same "pure function tested independently" discipline as the SVG builder it replaces, including the single-position and zero-position edge cases already covered.
- `save_portfolio_report` / `save_portfolio_report_tool`: zero/multiple client match returns the same error shape; apostrophe-in-name never reaches the filesystem path (reuses `_slugify`'s existing test); the file actually exists on disk after a successful call (new — the old tool never touched disk itself, this one does); `reports/` gets created when missing.
- `portfolio_agent.py`: `_TOOLS` and middleware tests updated for the new tool name and `interrupt_on` key.
- `display.py`: new normalizer tested the same way `normalize_report_file` was — success case produces a `report_file` display, an error-status result produces none (already covered generically by this session's `test_an_error_tool_message_is_never_enveloped`).
- `useToolDisplay.test.tsx`: tool-name list updated; existing `report_file` rendering test is unaffected (payload shape unchanged).
- Full backend (`uv run pytest tests/`) and frontend (`npx vitest run`) suites green before each commit, per this project's established TDD discipline.
