# AgentCore Memory — Design Spec (Phase 4c)

**Date:** 2026-05-21
**Status:** Approved (pending implementation)
**Branch:** `feat/agentcore-prod`
**Depends on:** Phase 4b complete (commit `038474d`).

## Goal

Replace the in-process LangGraph `InMemoryStore` (which loses all user facts on container restart) with **Amazon Bedrock AgentCore Memory** — a managed long-term memory service. The agent's three memory tools (`save_memory`, `recall_memory`, `list_memories`) continue to use the `InjectedStore()` LangChain pattern — no tool code changes required.

We deliberately **keep the Phase 3 DynamoDB checkpointer** for per-thread conversational state. Splitting the two concerns:
- **Checkpointer** (short-term, per-thread, full graph state) → DynamoDB. Cheap on-demand, we own the data, already done in Phase 3.
- **Store** (long-term, cross-thread user facts) → AgentCore Memory. Managed semantic indexing, future-ready for the SEMANTIC strategy's auto-extraction.

## Architecture

```
LangGraph agent (container)
    │
    ├── checkpointer ──► DynamoDB (Phase 3, durable per-thread state)
    │
    └── store ──────────► AgentCoreMemoryStore (this phase)
                              │
                              └── AgentCore Memory resource
                                  • name: user_facts
                                  • eventExpiryDuration: 90 days
                                  • SEMANTIC strategy → namespace `user_facts`
```

The CDK construct `AgentCoreApplication` reads the `memories` block in `agentcore.json`, provisions a `CfnMemory` resource, auto-grants the runtime IAM (`bedrock-agentcore:CreateEvent`, `ListEvents`, `RetrieveMemories`, etc.), and auto-injects `MEMORY_USER_FACTS_ID` as an env var on the runtime. **Zero CDK Python code added.**

## Modified files

- **`prod/agent/agentcore/agentcore.json`** — `memories` array adds one entry:
  ```json
  {
    "name": "user_facts",
    "eventExpiryDuration": 90,
    "strategies": [
      {
        "type": "SEMANTIC",
        "name": "facts",
        "description": "User facts and preferences extracted from conversations",
        "namespaceTemplates": ["user_facts"]
      }
    ]
  }
  ```

- **`prod/agent/app/agent/main.py`** — add `_build_store()` factory mirroring `_build_checkpointer()`:
  - `MEMORY_USER_FACTS_ID` set → `AgentCoreMemoryStore(memory_id, region_name=...)`
  - unset → `InMemoryStore()` (local dev)
  - Compile graph with `build_agent_app(checkpointer=..., store=...)` (the function already accepts a `store` kwarg).

## Files NOT modified

- **`tools/memory.py`** — unchanged. The 3 tools use `InjectedStore()` so they receive whatever store the graph was compiled with. AgentCore's `AgentCoreMemoryStore` is `BaseStore`-compatible.
- **`cdk-stack.ts`** — unchanged. The L3 application construct does all the work.
- **`pyproject.toml`** — unchanged. `langgraph-checkpoint-aws >= 1.0.7` (added in Phase 3) provides both `DynamoDBSaver` and `AgentCoreMemoryStore`.

## Decisions

| Question | Answer | Why |
|---|---|---|
| Replace checkpointer too? | No — keep DynamoDBSaver | Cheaper, we own the data, Phase 3 already built |
| Memory strategy | SEMANTIC on `user_facts` namespace | Enables semantic search in `list_memories`; also positions us for auto-extraction later |
| Event expiry | 90 days | Reasonable retention for a personal portfolio agent; can extend to 365 if needed |
| Namespace template | Literal `user_facts` (no `{actorId}`) | Single-user portfolio agent; multi-tenant scoping is a future-subsystem concern |
| Provisioning | Declarative in `agentcore.json` | Consistent with Phase 4a Gateway pattern; reproducible via `agentcore deploy` |

## Non-goals

- Long-term auto-extraction via `pre_model_hook` (would push HumanMessages into Memory for background fact extraction). Documented in the spec; defer to Phase 4c.2 if the user wants the agent to learn facts without explicit `save_memory` calls.
- Multi-actor namespacing (`{actorId}` template).
- Migration of any existing in-memory facts. There's no data to migrate — local dev starts fresh.

## Acceptance criteria

1. `npx tsc --noEmit` from `prod/agent/agentcore/cdk/` passes.
2. `agentcore validate` passes against the new schema.
3. Local dev still boots (`MEMORY_USER_FACTS_ID` unset → `InMemoryStore` log line).
4. Two commits land on `feat/agentcore-prod`. Pushed.
