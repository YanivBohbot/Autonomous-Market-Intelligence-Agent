# Plan — AgentCore Memory Phase 4c

**Spec:** `docs/superpowers/specs/2026-05-21-agentcore-memory-design.md`
**Branch:** `feat/agentcore-prod`
**Last commit:** `6a8c499 docs(prod): mark Phase 4b done in deployment tracking doc`

## Steps

### 1 — agentcore.json memories block

Replace `"memories": []` with one entry (name `user_facts`, expiry 90 days, SEMANTIC strategy `facts` scoped to namespace `user_facts`). Run `agentcore validate` — must be Valid.

### 2 — main.py store factory

Add `_build_store()` parallel to `_build_checkpointer()`:
```python
def _build_store() -> BaseStore:
    memory_id = os.getenv("MEMORY_USER_FACTS_ID")
    if memory_id:
        from langgraph_checkpoint_aws import AgentCoreMemoryStore
        return AgentCoreMemoryStore(memory_id=memory_id, region_name=os.getenv("AWS_REGION", "us-east-1"))
    return InMemoryStore()
```

Then `_agent_app = build_agent_app(checkpointer=_checkpointer, store=_build_store())`.

Import the lazy AgentCoreMemoryStore *inside* the if branch — local dev never imports it, so a version mismatch doesn't crash boot.

### 3 — Validate

`npx tsc --noEmit` from `cdk/`. `agentcore validate` from `prod/agent/`. Both must be clean.

### 4 — README + tracking docs

- README "Memory store" subsection.
- Mark Phase 4c done in `docs/AGENTCORE_DEPLOYMENT.md`.
- Update memory file `project_agentcore_prod_inflight.md`.

### 5 — Commit + push

1. `feat(prod/agent): Phase 4c — AgentCore Memory store`
2. `docs(prod): mark Phase 4c done in deployment tracking doc`
3. `git push`.

## NOT in scope

- Smoke tests (deferred — real Memory only exists post-deploy).
- pre_model_hook for auto-extraction (Phase 4c.2 if asked).
- Replacing DynamoDBSaver.
