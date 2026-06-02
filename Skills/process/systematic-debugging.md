# systematic-debugging

**Type:** Process (rigid)
**Plugin:** superpowers

## What it is
Root-cause a bug/test failure/unexpected behavior *before* proposing a fix — reproduce,
isolate, understand, then fix.

## How we used it on this project
Applied to the bug clusters that needed real root-causing rather than guesswork:

- **AgentCore Browser hotfixes (4 PRs, 2026-05-27):** double-ARN passed to `BrowserClient.start`,
  sync Playwright blocking the asyncio loop (fixed by running in a worker thread), and the
  removed `page.accessibility` API (switched to `body.inner_text`).
- **Phase 7 QA (2026-05-25):** 5 root-cause fixes — Gateway tool routing, persona drift,
  missing user-turn persistence, contract test gap, CI OIDC.

Standing candidate: the working-tree `checkpointer.py` change that hoisted lazy imports to
module top-level — a latent `ImportError` in the slim prod image that needs root-causing
before deploy.
