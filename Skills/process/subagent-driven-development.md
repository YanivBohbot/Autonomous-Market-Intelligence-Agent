# subagent-driven-development

**Type:** Process
**Plugin:** superpowers

## What it is
Executes an implementation plan's independent tasks in the current session by dispatching
subagents, rather than doing every task inline.

## How we used it on this project
Named alongside `executing-plans` as the accepted sub-skill at the top of every plan
("REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
superpowers:executing-plans"). Used to parallelize independent plan tasks — e.g. the
AgentCore Browser plan had independent unit-test tasks (BrowserSessionManager, registry
switch, FastMCP server) that could be built without shared state.
