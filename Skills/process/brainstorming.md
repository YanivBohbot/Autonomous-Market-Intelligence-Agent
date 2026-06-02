# brainstorming

**Type:** Process (run first, before any creative work)
**Plugin:** superpowers

## What it is
Explores user intent, requirements, and design *before* implementation. Forces the "what
and why" conversation before touching code.

## How we used it on this project
The output of brainstorming for every feature is its `*-design.md` spec. Each subsystem
got a brainstorm-then-spec pass before any plan or code:

- `docs/superpowers/specs/2026-05-07-yahoo-finance-mcp-design.md`
- `docs/superpowers/specs/2026-05-10-filesystem-mcp-design.md`
- `docs/superpowers/specs/2026-05-12-memory-store-design.md`
- `docs/superpowers/specs/2026-05-12-playwright-mcp-design.md`
- `docs/superpowers/specs/2026-05-25-durable-checkpointer-design.md`
- `docs/superpowers/specs/2026-05-27-agentcore-browser-design.md`

Also used for the deployment design (Option A: AgentCore Runtime + Gateway + Memory),
captured in our memory as the locked design.
