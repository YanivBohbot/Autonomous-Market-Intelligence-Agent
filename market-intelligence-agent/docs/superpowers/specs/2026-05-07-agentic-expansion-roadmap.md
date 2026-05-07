# Agentic Expansion Roadmap

**Date:** 2026-05-07
**Status:** Brainstorming — pending per-subsystem design
**Context:** After completing the LangGraph best-practices refactor (branch `refactor/langgraph-best-practices`), the next initiative is to expand the agent's capabilities by integrating six additional tools / MCP servers.

## Scope

Six independent subsystems were proposed by the user:

| # | Capability | Type | Estimated effort |
|---|---|---|---|
| 1 | Yahoo Finance MCP | New tool (data) | S |
| 2 | Playwright browser MCP | New tool (action) | M |
| 3 | Google Drive MCP | New tool (action + auth) | M-L (OAuth) |
| 4 | Filesystem MCP | New tool (action) | S |
| 5 | Memory store | Cross-cutting state layer | M |
| 6 | Scheduler / cron | Cross-cutting infrastructure | M-L (background process) |

Per the `superpowers:brainstorming` skill, six independent subsystems is too large for a single design / spec / plan cycle. Each must be decomposed into its own design → plan → implementation cycle.

## Proposed Build Order

Sequenced by leverage and dependency chain:

1. **Yahoo Finance MCP** — biggest "wow" payoff, smallest scope, no infra changes.
2. **Filesystem MCP** — quick win, lets the agent persist research artifacts.
3. **Playwright browser MCP** — paywalled scraping; complements Tavily.
4. **Memory store** — gets value once #1–3 produce content worth remembering.
5. **Google Drive MCP** — OAuth flow is real work; defer until memory-store decisions are made.
6. **Scheduler / cron** — last because what gets scheduled depends on capabilities #1–5.

## Per-Subsystem Workflow (each entry above)

For each capability, the workflow is:

1. Brainstorm (`superpowers:brainstorming`) — clarifying questions → 2–3 approaches → design.
2. Write design doc to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`.
3. User approves spec.
4. Plan (`superpowers:writing-plans`) → `docs/superpowers/plans/YYYY-MM-DD-<topic>.md`.
5. Implement (`superpowers:subagent-driven-development`).

## Open Questions

- **Sequencing:** Confirm proposed order, or pick a different first subsystem.
- **MCP vs. native:** Some of these (Filesystem, Memory) could be native LangChain tools rather than MCP servers — decide per subsystem during brainstorming.
- **HITL coverage:** Decide whether new write/action tools (Filesystem, Drive, Playwright actions) all gate through the existing `approval_node`.

## Existing Plan Inventory

Reference for context — plans already on disk:

- `docs/superpowers/plans/2026-05-04-enterprise-foundation.md`
- `docs/superpowers/plans/2026-05-04-feature-enhancements.md`
- `docs/superpowers/plans/2026-05-05-feature-enhancements-v2.md`
- `docs/superpowers/plans/2026-05-07-langgraph-best-practices.md` (executed on `refactor/langgraph-best-practices`)

## Next Action

Await user confirmation of the build order, then enter brainstorming for the first subsystem (default: Yahoo Finance MCP).
