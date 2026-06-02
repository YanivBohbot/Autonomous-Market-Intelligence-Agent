# using-git-worktrees

**Type:** Process
**Plugin:** superpowers

## What it is
Creates an isolated workspace (native tool or git worktree fallback) for feature work, so
in-progress changes don't collide with the current workspace.

## How we used it on this project
Branch-per-feature isolation. The AgentCore Browser work came in over isolated branches,
each merged via its own PR:

- `feat/agentcore-browser` (PR #1)
- `fix/agentcore-browser-double-arn` (PR #2)
- `fix/browser-async-thread` (PR #3)
- `fix/browser-snapshot-and-probe` (PR #4)
