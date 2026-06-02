# executing-plans

**Type:** Process
**Plugin:** superpowers

## What it is
Executes a written implementation plan in a separate session, task-by-task, with review
checkpoints between tasks.

## How we used it on this project
The driving skill for working through the `docs/superpowers/plans/*.md` files. Each plan
names it explicitly as the required sub-skill. Evidence is the per-task commit cadence —
plan tasks map to commits like the durable-checkpointer series (`fee6554` deps →
`257b49f` backend → `586aa8f` infra switch → QA).

The next candidate for this skill is the unstarted `2026-05-31-browser-long-lived-mcp.md`
(Phase 8.1, 9 tasks).
