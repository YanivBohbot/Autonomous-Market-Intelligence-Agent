# finishing-a-development-branch

**Type:** Process
**Plugin:** superpowers

## What it is
Once implementation is complete and tests pass, decide how to integrate — presents
structured options for merge, PR, or cleanup.

## How we used it on this project
The merge-PR-then-followup cadence on master. Each feature branch ended with a PR merge
(e.g. `2279120 Merge pull request #4 …`, `01d26cf Merge pull request #1 …`) rather than
a direct push, keeping master integration deliberate.
