# writing-plans

**Type:** Process (after a spec, before code)
**Plugin:** superpowers

## What it is
Turns a spec/requirements into a multi-step, task-by-task implementation plan with explicit
TDD steps, full code (no placeholders), and checkbox tracking.

## How we used it on this project
Every spec got a matching plan in `docs/superpowers/plans/`. 13 plans total:

- `2026-05-04-enterprise-foundation.md`
- `2026-05-04-feature-enhancements.md`
- `2026-05-05-feature-enhancements-v2.md`
- `2026-05-07-langgraph-best-practices.md`
- `2026-05-07-yahoo-finance-mcp.md`
- `2026-05-10-filesystem-mcp.md`
- `2026-05-12-memory-store.md`
- `2026-05-12-playwright-mcp.md`
- `2026-05-15-livekit-voice-agent.md`
- `2026-05-25-durable-checkpointer.md`
- `2026-05-27-agentcore-browser.md`
- `2026-05-31-browser-long-lived-mcp.md`  ← written, not yet executed (Phase 8.1)

Each plan opens with "REQUIRED SUB-SKILL: use subagent-driven-development or executing-plans"
and uses `- [ ]` step tracking with Write-the-failing-test-first ordering.
