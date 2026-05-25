# Durable Checkpointer Design

**Author:** Yaniv Bohbot (with Claude pair-programming)
**Date:** 2026-05-25
**Status:** Approved — ready for implementation
**Companion plan:** `docs/superpowers/plans/2026-05-25-durable-checkpointer.md`

## Problem

The deployed agent uses `InMemorySaver` (LangGraph's in-process checkpointer, configured via `CHECKPOINTER_BACKEND=memory` in `app/agent/memory/checkpointer.py`). Checkpoints live in the RAM of whichever AgentCore Runtime container handled the turn. The AgentCore Runtime Playground in the AWS Console generates a **fresh `runtimeSessionId` per "Run" click**, which lets AgentCore route follow-up calls to a different container than the one holding the checkpoint. Consequences:

1. `/approve` after a HITL `interrupt` returns **500 Internal Server Error** in the Console Playground (`KeyError: 'question'` in `rag` node when the resume path enters a container that never saw the original prompt).
2. Cross-turn memory recall is unreliable from the playground (each click looks like a brand-new session).
3. The `send_email` tool cannot be exercised end-to-end from the playground because it requires `interrupt → /approve` to actually send.

Confirmed reproducer: `prod/ci/qa_playground.py` Part 1 deterministically reproduces the 500; Part 2 with a sticky session passes everything.

## Goals

1. Make HITL approve/reject work from any client — Console Playground, CLI, future UI — regardless of which container handles which turn.
2. Make cross-turn memory recall ("what did I ask you earlier?") reliable across the full container fleet.
3. Zero new AWS infrastructure (we already have AgentCore Memory `mia_memory_demo-UOKiBF3nx2` provisioned).
4. Reversible: must be possible to flip back to the `memory` backend via an env var with no code rollback.

## Non-goals

- Long-term cross-session episodic memory (`AgentCoreMemoryStore`). The Memory service supports it, but our existing `app/agent/memory/store.py` (`InMemoryStore`) covers the v1 "user facts" feature already. Episodic upgrade is a future change, out of scope here.
- Multi-tenant authentication mapping (every session uses a fixed `actor_id`).
- DynamoDB-backed checkpointer (`langgraph-checkpoint-dynamodb`). Evaluated and rejected — see "Options considered" below.

## Solution

Replace `InMemorySaver` with **`AgentCoreMemorySaver`** from the AWS-maintained `langgraph-checkpoint-aws` package. It implements LangGraph's `BaseCheckpointSaver` contract and persists checkpoints as AgentCore Memory short-term events. Containers become stateless w.r.t. session state; any container in the fleet can read any session's checkpoint.

### Reference

- AWS doc: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-integrate-lang.html>
- PyPI: <https://pypi.org/project/langgraph-checkpoint-aws/>
- Source: <https://github.com/langchain-ai/langchain-aws/tree/main/libs/langgraph-checkpoint-aws>

### API used

```python
from langgraph_checkpoint_aws import AgentCoreMemorySaver

checkpointer = AgentCoreMemorySaver(MEMORY_ID, region_name=REGION)

# Invocation now requires actor_id in addition to thread_id:
config = {
    "configurable": {
        "thread_id": session_id,    # already wired
        "actor_id": "mia-agent",    # new — same value for every session in v1
    }
}
```

### Required IAM (per AWS doc)

- `bedrock-agentcore:CreateEvent`
- `bedrock-agentcore:ListEvents`
- `bedrock-agentcore:RetrieveMemories`

Scoped to the specific memory ARN, not `*`.

## Options considered

| Option | Backing store | Net new infra | Net new perms | Maintenance | Verdict |
|---|---|---|---|---|---|
| **A. `AgentCoreMemorySaver`** | Existing AgentCore Memory | None | 3 IAM actions | None — service-managed | ✅ Chosen |
| B. `langgraph-checkpoint-dynamodb` (community) | New DynamoDB table + TTL | 1 table, 1 IAM grant, TTL config | 5 IAM actions | TTL retention, RCU/WCU monitoring | Rejected |
| C. Status quo (`InMemorySaver`) | Container RAM | None | None | None | Rejected — broken in Playground |

Option B would have won if we didn't already have AgentCore Memory in the stack. We do, so leaning into the vendor we've committed to is the lower-friction choice.

## Architecture flow

```
User (Console Playground / chat.py / API)
     │ invoke-agent-runtime  (runtimeSessionId X)
     ▼
AgentCore Runtime ─── routes to ANY warm container
     │
     ▼ ainvoke(...) / ainvoke(Command(resume=...))
LangGraph agent_app
     │
     ▼ checkpointer.aget / aput
AgentCoreMemorySaver
     │ CreateEvent / ListEvents
     ▼
AgentCore Memory (mia_memory_demo-UOKiBF3nx2)
   namespace = (actor_id="mia-agent", thread_id=<session>)
```

Key property: containers no longer need session affinity. The runtime's microVM-per-`runtimeSessionId` model still applies, but state durability no longer depends on it.

## Required code changes (summary)

| File | Change |
|---|---|
| `requirements.agentcore.txt` | Add `langgraph-checkpoint-aws` |
| `app/agent/memory/checkpointer.py` | New `agentcore` backend branch — `AgentCoreMemorySaver(MIA_MEMORY_ID, region_name=AWS_REGION)` |
| `app/core/config.py` | Default `CHECKPOINTER_BACKEND` stays `sqlite` for local dev. Existing `MIA_MEMORY_ID` env var is reused. Existing `AWS_REGION` settings reused. |
| `app/api/routers/agentcore.py` | Add `"actor_id": "mia-agent"` to the `configurable` dict |
| `prod/iac/stacks/runtime_stack.py` | Add IAM `CreateEvent`, `ListEvents`, `RetrieveMemories` on the memory ARN. Set container env `CHECKPOINTER_BACKEND=agentcore` and `MIA_MEMORY_ID=<from memory stack>` |

## Required QA (summary)

| Probe | Tool | Pre-fix expectation | Post-fix expectation |
|---|---|---|---|
| Sticky-session 18-case regression | `prod/ci/qa_full.py` | 18/18 pass | 18/18 pass (no regression) |
| Playground reproducer | `prod/ci/qa_playground.py` | 1 case marked `expected FAIL` passes (i.e., the bug exists); the `approve` on fresh session returns 500 | The `approve` on fresh session now returns `status=completed`. Adjust the assertion polarity. |
| Console Playground manual | AWS Console UI | `/approve` → 500 | `/approve` → completed; cross-turn recall works |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `langgraph-checkpoint-aws` is young; could have a contract bug | Medium | Keep `memory` backend wired; flip env var to roll back |
| `AgentCoreMemorySaver` serialization differs from `InMemorySaver` enough to break existing in-flight sessions | Low | We are between sessions; redeploy nukes in-memory state anyway. No regression. |
| Per-event AgentCore Memory cost spikes if traffic spikes | Low | $0.25 / 1K events. Even 10K sessions/day ≈ $75/month. Add a billing alarm at $50 over baseline. |
| Memory short-term retention too short → checkpoints garbage-collected mid-conversation | Medium | Verify the retention setting on the existing memory resource. Default is 30 days for short-term events; fine. |
| Pinecone/Tavily/OpenAI not affected | n/a | Unrelated subsystems |

## Acceptance criteria

1. `prod/ci/qa_full.py`: 18/18 pass on the deployed runtime.
2. `prod/ci/qa_playground.py`: every fresh-session probe passes; the previously-`expected FAIL` case for `write_file` approve now returns `status=completed` and the test polarity is updated to reflect the fix.
3. Manual: in the AWS Console Runtime Playground, the full HITL write_file approve flow completes without 500, and a follow-up "what was my first question" returns the correct prior turn.
4. CI green: push to master triggers test → deploy → smoke; smoke does not regress.
5. Env-var rollback works: flipping `CHECKPOINTER_BACKEND=memory` in the runtime stack and redeploying brings the system back to the previous behavior with no code change.

## Out-of-scope follow-ups

- `AgentCoreMemoryStore` for cross-session episodic memory (replaces our `InMemoryStore` "user facts" backend; needs a separate plan).
- `actor_id` derived from the authenticated user once Cognito user-pool sign-in lands.
- Tighten the IAM `Resource` on `InvokeAgentRuntime` (currently `runtime/*`) — recorded in `project_phase7_done.md` tech-debt list.
