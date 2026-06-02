# requesting-code-review

**Type:** Process
**Plugin:** superpowers

## What it is
Request a code review on completing a task / major feature / before merge, to verify the
work meets requirements.

## How we used it on this project
The browser subsystem shipped through **4 GitHub PRs (#1–#4)**, each a review gate before
merge to master. The project rule in `CLAUDE.md` ("don't merge a tool addition without
updating `docs/TOOLS.md`") is enforced at this review step.
