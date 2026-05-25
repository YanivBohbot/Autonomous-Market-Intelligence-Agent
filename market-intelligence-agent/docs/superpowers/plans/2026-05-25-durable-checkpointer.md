# Durable Checkpointer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-process `InMemorySaver` LangGraph checkpointer with `AgentCoreMemorySaver` (AWS-maintained `langgraph-checkpoint-aws` package), backed by the existing AgentCore Memory resource. After this lands, HITL `/approve` and cross-turn memory work from any client — including the AWS Console Runtime Playground, whose fresh-runtimeSessionId-per-click model breaks the in-memory backend today.

**Architecture:** A new `agentcore` branch in the existing `create_checkpointer` factory wraps `AgentCoreMemorySaver(memory_id, region_name)`. The factory contract is unchanged (it still yields a `BaseCheckpointSaver`), so graph compilation in `app/api/server.py` lifespan is unchanged. The `/invocations` router gains a single new key — `actor_id="mia-agent"` — in the LangGraph `configurable` dict, which the AWS saver requires. Runtime CDK stack adds three IAM actions on the memory ARN and flips two container env vars (`CHECKPOINTER_BACKEND=agentcore`, plus `MIA_MEMORY_ID` which is already exported).

**Tech Stack:** Python 3.12, `langgraph` (already installed), new dep `langgraph-checkpoint-aws` (AWS-maintained), `boto3` (already installed). AWS CDK Python (already wired). No new AWS services — all infrastructure already exists.

**Source spec:** `docs/superpowers/specs/2026-05-25-durable-checkpointer-design.md`

**User preferences carried in:**

- **Tests are deferred.** The codebase has a Windows long-path issue that prevents running `uv run pytest` locally; the CI pipeline runs pytest on push. The regression gate here is **CI green** + the live-runtime QA suites (`prod/ci/qa_full.py`, `prod/ci/qa_playground.py`) staying green or improving. No new pytest tests are added.
- **Reversible via env var.** The `memory` backend branch stays in `checkpointer.py`. Flipping `CHECKPOINTER_BACKEND=memory` in the runtime stack env vars rolls the system back without a code change.
- **Atomic-batch HITL semantics preserved.** No changes to `approval_node` or the `READ_ONLY_TOOLS` allowlist.
- **Frequent commits.** Each task ends with a commit; failure scenarios are recoverable from the previous commit.

**File structure (target):**

```
market-intelligence-agent/
├── requirements.agentcore.txt              # MODIFY — add langgraph-checkpoint-aws
├── app/
│   ├── core/config.py                       # MODIFY — extend CHECKPOINTER_BACKEND comment; reuse MIA_MEMORY_ID (already exported via env)
│   ├── agent/memory/checkpointer.py         # MODIFY — new `agentcore` branch
│   └── api/routers/agentcore.py             # MODIFY — pass actor_id in configurable dict
└── docs/superpowers/
    ├── specs/2026-05-25-durable-checkpointer-design.md   # (already created)
    └── plans/2026-05-25-durable-checkpointer.md          # (this file)

prod/
├── iac/stacks/runtime_stack.py              # MODIFY — IAM perms + 2 env vars
└── ci/qa_playground.py                      # MODIFY — flip the "expected FAIL" assertion polarity
```

---

### Task 1: Add the `langgraph-checkpoint-aws` dependency

**Files:**

- Modify: `market-intelligence-agent/requirements.agentcore.txt`

- [ ] **Step 1: Add the dependency line**

Edit `market-intelligence-agent/requirements.agentcore.txt`. After the `# LangGraph + LangChain stack` block (after line 18 `langchain-community>=0.4.1`), insert:

```
langgraph-checkpoint-aws>=0.1.0
```

The resulting block should read:

```
# LangGraph + LangChain stack
langgraph>=1.0.3
langchain>=1.0.8
langchain-core>=1.0.0
langchain-openai>=1.0.3
langchain-pinecone>=0.2.13
langchain-mcp-adapters>=0.1.0
langchain-community>=0.4.1
langgraph-checkpoint-aws>=0.1.0
```

- [ ] **Step 2: Verify the package exists on PyPI at the pinned floor**

Run from any directory:

```bash
pip index versions langgraph-checkpoint-aws 2>&1 | head -3
```

Expected: a line beginning with `Available versions:` listing one or more 0.x releases. If the package isn't found, do NOT proceed — confirm the package name with the AWS docs and update the floor.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/requirements.agentcore.txt
git commit -m "build(agentcore): add langgraph-checkpoint-aws dependency

Prep for switching the LangGraph checkpointer to AgentCoreMemorySaver
so HITL approve/reject works across container instances (the in-memory
backend keeps state in one container's RAM, which breaks the AWS Console
Runtime Playground's fresh-runtimeSessionId-per-click model).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Add the `agentcore` backend to `create_checkpointer`

**Files:**

- Modify: `market-intelligence-agent/app/agent/memory/checkpointer.py`

- [ ] **Step 1: Add the new branch**

In `market-intelligence-agent/app/agent/memory/checkpointer.py`, after the existing `memory` branch (after the line `yield InMemorySaver(); return`) and before the trailing `raise ValueError(...)`, insert:

```python
    if backend == "agentcore":
        # Durable, multi-container checkpointer backed by AgentCore Memory.
        # Required when running on AgentCore Runtime so that HITL resume and
        # cross-turn recall work regardless of which container handles which
        # turn. See docs/superpowers/specs/2026-05-25-durable-checkpointer-design.md.
        from langgraph_checkpoint_aws import AgentCoreMemorySaver

        memory_id = os.environ.get("MIA_MEMORY_ID")
        if not memory_id:
            raise RuntimeError(
                "CHECKPOINTER_BACKEND=agentcore requires MIA_MEMORY_ID env var "
                "(set automatically by the runtime CDK stack)."
            )
        region = os.environ.get("AWS_REGION", "us-east-1")
        logger.info(
            "checkpointer backend=agentcore memory_id=%s region=%s",
            memory_id, region,
        )
        yield AgentCoreMemorySaver(memory_id, region_name=region)
        return
```

- [ ] **Step 2: Update the module docstring**

Edit the docstring at the top of the same file (lines 1-15) to list the new backend:

```python
"""Checkpointer factory with a pluggable backend.

Backends, selected via `CHECKPOINTER_BACKEND` env:

- `sqlite` (default): `AsyncSqliteSaver` against a local SQLite file —
  right choice for local dev where state must survive process restarts.
- `memory`: LangGraph's in-process `InMemorySaver`. State is lost when
  the container stops AND when AgentCore routes a follow-up call to a
  different container. Use only for tests / very-short single-turn
  flows.
- `agentcore`: `AgentCoreMemorySaver` (from `langgraph-checkpoint-aws`),
  backed by an AgentCore Memory resource. Durable across containers —
  the right choice for any AgentCore Runtime deployment that does
  multi-turn or HITL. Requires `MIA_MEMORY_ID` and AWS creds with
  `bedrock-agentcore:CreateEvent`, `ListEvents`, `RetrieveMemories`
  on the memory ARN.
"""
```

- [ ] **Step 3: Sanity-check the import path**

Run:

```bash
python -c "from langgraph_checkpoint_aws import AgentCoreMemorySaver; print(AgentCoreMemorySaver.__module__)"
```

Expected output: a module path starting with `langgraph_checkpoint_aws`. If `ModuleNotFoundError`, run `pip install langgraph-checkpoint-aws` first.

If the symbol is at a different path (e.g. `langgraph_checkpoint_aws.agentcore.saver`), update the `import` line in Step 1 accordingly and note the discrepancy in the spec.

- [ ] **Step 4: Commit**

```bash
git add market-intelligence-agent/app/agent/memory/checkpointer.py
git commit -m "feat(checkpointer): add agentcore backend using AgentCoreMemorySaver

New branch in create_checkpointer() that yields AgentCoreMemorySaver
backed by the existing AgentCore Memory resource. Selected via
CHECKPOINTER_BACKEND=agentcore. Existing sqlite (local dev default)
and memory (legacy / test) branches unchanged — flipping the env var
back to 'memory' rolls this change back with no code change.

Spec: docs/superpowers/specs/2026-05-25-durable-checkpointer-design.md

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Pass `actor_id` into the LangGraph `configurable` dict

**Files:**

- Modify: `market-intelligence-agent/app/api/routers/agentcore.py`

- [ ] **Step 1: Replace the single-key configurable construction**

Locate the line in `market-intelligence-agent/app/api/routers/agentcore.py` that reads:

```python
    config = {"configurable": {"thread_id": session_id}}
```

Replace it with:

```python
    # AgentCoreMemorySaver requires both thread_id and actor_id. We use a
    # fixed actor_id for v1 — every session shares the same actor namespace.
    # A multi-tenant version would derive actor_id from the authenticated
    # user once Cognito sign-in is wired into the runtime contract.
    config = {
        "configurable": {
            "thread_id": session_id,
            "actor_id": "mia-agent",
        }
    }
```

- [ ] **Step 2: Verify nothing else builds a `configurable` dict that would bypass actor_id**

Run:

```bash
grep -rn '"thread_id"' market-intelligence-agent/app/ | grep -v __pycache__
```

Expected output: only the line you just edited in `app/api/routers/agentcore.py`. If anything else appears (e.g. another router or a background worker), apply the same `actor_id` addition there.

- [ ] **Step 3: Commit**

```bash
git add market-intelligence-agent/app/api/routers/agentcore.py
git commit -m "feat(api): pass actor_id alongside thread_id for AgentCoreMemorySaver

AgentCoreMemorySaver requires both keys in the LangGraph RunnableConfig
'configurable' dict. v1 uses a fixed actor_id 'mia-agent' for every
session — every checkpoint belongs to the same actor namespace, which
is fine for a single-tenant demo. A future multi-tenant change would
derive actor_id from the authenticated user.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Update `RuntimeStack` — IAM + env vars

**Files:**

- Modify: `prod/iac/stacks/runtime_stack.py`

- [ ] **Step 1: Broaden the memory IAM grant**

Locate the existing two-line memory grant (around line 93-94 of `prod/iac/stacks/runtime_stack.py`):

```python
        # Memory r/w
        self.memory.grant_read(role)
        self.memory.grant(role, "bedrock-agentcore:CreateEvent")
```

Replace with:

```python
        # Memory r/w — `AgentCoreMemorySaver` needs CreateEvent (write a
        # checkpoint), ListEvents (load checkpoint history), and
        # RetrieveMemories (long-term retrieval, also used by store).
        # Scoped to the specific memory ARN by the construct.
        self.memory.grant_read(role)
        self.memory.grant(
            role,
            "bedrock-agentcore:CreateEvent",
            "bedrock-agentcore:ListEvents",
            "bedrock-agentcore:RetrieveMemories",
        )
```

- [ ] **Step 2: Flip the checkpointer backend env var**

Locate the environment-variable block (around line 117-148). Change the line:

```python
                "CHECKPOINTER_BACKEND": "memory",
```

to:

```python
                # Durable checkpoint store via AgentCoreMemorySaver — required
                # for HITL approve/reject to work across container instances
                # (the AgentCore Runtime Playground generates a new
                # runtimeSessionId per click; in-memory state cannot survive).
                # Flip back to "memory" for a quick rollback without code changes.
                "CHECKPOINTER_BACKEND": "agentcore",
```

`MIA_MEMORY_ID` is already in the env block — no additional change there.

- [ ] **Step 3: Verify the construct still synthesizes**

From `prod/iac/`:

```bash
.venv/Scripts/activate
cdk synth mia-runtime-demo > /dev/null && echo "synth ok"
```

Expected: prints `synth ok`. If synth fails with an IAM grant error (e.g. the construct rejects multiple actions in one call), restructure as three separate `grant` calls.

- [ ] **Step 4: Commit**

```bash
git add prod/iac/stacks/runtime_stack.py
git commit -m "feat(infra): switch runtime to agentcore checkpointer backend

- Grants the runtime role the three IAM actions AgentCoreMemorySaver
  needs (CreateEvent + ListEvents + RetrieveMemories) on the memory
  ARN — no wildcards.
- Flips CHECKPOINTER_BACKEND from 'memory' to 'agentcore'. MIA_MEMORY_ID
  was already in the env block; no other change needed.
- Rollback: flip the env var back to 'memory' and redeploy. No code
  rollback required.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Update the playground QA reproducer to reflect the fix

**Files:**

- Modify: `prod/ci/qa_playground.py`

- [ ] **Step 1: Update the failing-case assertion**

In `prod/ci/qa_playground.py`, locate the block beginning with the comment `# Different runtimeSessionId — the playground bug`. The block currently asserts that the fresh-session resume PRODUCES the 500 error:

```python
    # Different runtimeSessionId — the playground bug
    pg_b = _new_runtime_session()
    r = invoke(pg_b, {"resume": "approve"})
    # We EXPECT this to fail — confirming the user's earlier 500
    ok = "_error" in r and "500" in r["_error"]
    case("playground:write_file → approve on FRESH session (expected FAIL)",
         ok, r)
```

Replace with:

```python
    # Different runtimeSessionId — used to be the playground bug
    # (in-memory backend lost state when a different container handled
    # the resume). With the durable AgentCore Memory backend, the resume
    # now works regardless of which container handles it.
    pg_b = _new_runtime_session()
    r = invoke(pg_b, {"resume": "approve"})
    ok = r.get("status") == "completed"
    case("playground:write_file → approve on FRESH session (durable saver)",
         ok, r)
```

- [ ] **Step 2: Don't run it yet**

The deploy needs to land first (next task). Running the QA script now against the un-deployed change would show the test still failing, which is expected — that's the proof state.

- [ ] **Step 3: Commit**

```bash
git add prod/ci/qa_playground.py
git commit -m "test(qa): flip playground reproducer to assert the fix

prod/ci/qa_playground.py previously asserted that a fresh-runtime-session
/approve would return 500 — that captured the bug. After the durable
checkpointer lands, the assertion polarity flips: status=completed is the
expected outcome.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Push, let CI deploy, observe smoke

**Files:** (none — push only)

- [ ] **Step 1: Push master**

```bash
git push origin master
```

The GH Actions OIDC pipeline (commit `e1f31bd` set this up) runs `test → deploy → smoke` automatically. Wall-clock: ~4 minutes.

- [ ] **Step 2: Watch the run**

```bash
gh run watch
```

Expected: `test ✅ deploy ✅ smoke ✅`. If `deploy` fails on a CDK / IAM error, read the failure and update the previous task — don't try to patch in a follow-up commit until the root cause is clear.

- [ ] **Step 3: If CI is green, confirm container picked up the new env var**

```bash
aws bedrock-agentcore get-agent-runtime \
  --agent-runtime-arn "arn:aws:bedrock-agentcore:us-east-1:584246028688:runtime/mia_runtime_demo-tio2ELGaQB" \
  --region us-east-1 \
  --query 'agentRuntimeArtifact.containerConfiguration.environmentVariables[?name==`CHECKPOINTER_BACKEND`]'
```

Expected: an entry whose `value` is `agentcore`.

If the field is empty or the API differs, fall back to inspecting the runtime stack outputs and the recent CloudFormation deployment via the AWS console.

- [ ] **Step 4: No commit needed; CI is the source of truth.**

---

### Task 7: Regression QA — sticky session

**Files:** (none — run-only)

- [ ] **Step 1: Run the full sticky-session QA suite**

```bash
python prod/ci/qa_full.py
```

Expected: `RESULT: 18 passed, 0 failed`. This includes the 13 tool tests plus HITL approve/reject and cross-turn recall.

- [ ] **Step 2: If any case fails, diagnose before proceeding**

Look at CloudWatch logs:

```bash
aws logs filter-log-events --region us-east-1 \
  --log-group-name "/aws/bedrock-agentcore/runtimes/mia_runtime_demo-tio2ELGaQB-DEFAULT" \
  --start-time $(($(date +%s)*1000 - 600000)) \
  --filter-pattern 'ERROR' \
  --query 'events[].message' --output text
```

Common new failure modes:

- `MIA_MEMORY_ID` missing → confirm it's in the runtime env block (it already is)
- `AccessDeniedException` on `bedrock-agentcore:ListEvents` → IAM grant didn't propagate; redeploy
- `langgraph_checkpoint_aws.AgentCoreMemorySaver()` argument mismatch → check the lib version, may need a different signature

- [ ] **Step 3: No commit; this is a verification gate.**

---

### Task 8: Reproducer QA — fresh session per call

**Files:** (none — run-only)

- [ ] **Step 1: Run the playground-mode reproducer**

```bash
python prod/ci/qa_playground.py
```

Expected: every case in Part 1 (playground mimic) AND Part 2 (sticky session) passes, including the previously-`expected FAIL` case that you flipped in Task 5. Total: `RESULT: 18 passed, 0 failed` or similar (count depends on the new case structure).

The two cases that were the proof of the bug should now pass:

- `playground:write_file → approve on FRESH session (durable saver)` — used to assert 500; now asserts `status=completed`.

- [ ] **Step 2: No commit; this is a verification gate.**

---

### Task 9: Manual verification in the AWS Console Runtime Playground

**Files:** (none — manual UI test)

- [ ] **Step 1: Open the playground**

Navigate to the Bedrock console → Agent Runtimes → `mia_runtime_demo` → Test → Runtime playground.

- [ ] **Step 2: Trigger a HITL interrupt**

In the playground input box, paste:

```json
{"prompt": "Please write a file named \"durable_test.txt\" in my workspace with content \"durable saver works\".", "session_id": "manual-durable-1"}
```

Click Run. Expected output: `status=interrupted`, `pending_tool_calls` includes a `filesystem___write_file` entry.

- [ ] **Step 3: Approve from the playground**

Paste:

```json
{"resume": "approve", "session_id": "manual-durable-1"}
```

Click Run. Expected output (the change that was previously 500): `status=completed`, response confirming the file write.

- [ ] **Step 4: Verify cross-turn recall from the playground**

Paste:

```json
{"prompt": "What was the very first thing I asked you in this session?", "session_id": "manual-durable-1"}
```

Click Run. Expected output: a response that references `durable_test.txt` with content `durable saver works` (or a paraphrase that clearly names the file). This is the round-trip proof.

- [ ] **Step 5: No commit; this is the human acceptance gate.**

---

### Task 10: Update memory + announce done

**Files:**

- Create: `C:/Users/user/.claude/projects/.../memory/project_durable_checkpointer_done.md`
- Modify: `C:/Users/user/.claude/projects/.../memory/MEMORY.md`

- [ ] **Step 1: Write the memory entry**

Create the file with the front-matter and a short summary referencing the spec and confirming the QA pass. Use the existing `project_*_done.md` files as the template.

- [ ] **Step 2: Add an index line to MEMORY.md**

Add one line under the existing Phase 7 entries:

```
- [Durable checkpointer DONE](project_durable_checkpointer_done.md) — agentcore backend live; HITL works in Console Playground; reproducer flipped to assert the fix
```

- [ ] **Step 3: Done — verbal confirmation to user**

Surface the result: 18/18 sticky QA pass + playground reproducer pass + manual UI step 4 returns the expected recall. Note the rollback procedure (env var flip + redeploy) as the recovery path if anything regresses.

- [ ] **Step 4: No code commit needed for memory updates; they live outside the repo.**

---

## Self-review

- **Spec coverage:** Each goal in the spec maps to a task — durable checkpointer (Tasks 1-2), `actor_id` plumbing (Task 3), IAM + env vars (Task 4), QA polarity flip (Task 5), deploy (Task 6), regression QA (Task 7), reproducer QA (Task 8), manual playground (Task 9), memory + done (Task 10). Acceptance criteria 1-5 in the spec map to Tasks 7, 8, 9, 6, and the env-var rollback note in Task 4.
- **Placeholder scan:** Every code change is fully written. The only deferred concrete value is the exact `langgraph-checkpoint-aws` floor version in Task 1 Step 1 — the verification in Step 2 catches that and tells the operator to adjust.
- **Type consistency:** `checkpointer.py` returns `BaseCheckpointSaver`; `AgentCoreMemorySaver` implements that contract per the AWS doc. `actor_id` is a string in the `configurable` dict — same convention as `thread_id`. CDK `grant(role, action_str, ...)` accepts a varargs list of actions, matching the existing call on line 94.

If Task 2 Step 3 reveals that `AgentCoreMemorySaver` lives at a different import path than `langgraph_checkpoint_aws`, update the import in Task 2 Step 1 inline and continue.
