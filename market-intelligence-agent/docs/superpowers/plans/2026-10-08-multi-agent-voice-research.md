# Multi-Agent Voice for Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add continuous GPT-Live voice to `/research`, route spoken turns through the shared multi-agent graph, keep text and voice mutually exclusive, show English voice/activity/HITL UI, and retain voice context without rendering transcripts.

**Architecture:** Complete `docs/superpowers/plans/2026-10-08-multi-agent-cutover-reconciliation.md` first. Research voice then becomes a transport around the shared graph: a per-thread lease prevents concurrent text and voice runs; a bounded activity store feeds the Intelligence rail; a Research voice runtime streams nested graph events and coordinates idempotent HITL decisions; the browser owns WebRTC and microphone cleanup. Classic voice keeps its current transcript endpoint and single-agent path.

**Tech Stack:** React 19, TypeScript, Vite, CopilotKit v2, Vitest, Testing Library, FastAPI, LangGraph, OpenAI GPT-Live WebRTC and sideband delegation, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-multi-agent-voice-research-design.md`

## Dependency

- Execute and validate `docs/superpowers/plans/2026-10-08-multi-agent-cutover-reconciliation.md` before Task 1.
- The shared graph invariant must already hold: `app.state.market_desk_agent.graph is app.state.agent_app`.

## Global Constraints

- Voice is enabled only on `/research`; client workspaces remain text-only.
- Voice is continuous, not push-to-talk or dictation.
- All new UI text is English.
- Voice and text use the same Research `thread_id` and checkpoint.
- Voice transcript messages stay in graph context but never appear in Research chat history.
- Spoken decisions support approve/reject; visual decisions retain approve/edit/reject and the generated-report selector.
- The first valid decision for an interrupt wins; a duplicate may return the stored outcome but never resume twice.
- Raw audio, complete transcript text, credentials, and binary tool output never enter the activity endpoint.
- Preserve `/classic`, `GET /voice/{thread_id}/transcript`, and Streamlit behavior.
- Desktop is the acceptance target; tablet/mobile redesign is excluded.
- Do not merge branches, push, or open a pull request.

## Review Focus

- Multi-tab races are prevented on the server, not only by disabled buttons.
- Every WebRTC exit path stops tracks, closes channels/connections, removes audio elements, and releases the lease.
- An unresolved approval survives voice disconnect and remains actionable visually.
- Voice activity joins the existing Intelligence timeline; it does not create a second activity panel.
- The composer is structurally replaced through CopilotKit's input slot, with no DOM query or mutation.

---

### Task 1: Tag voice turns and filter only their visual history

**Files:**
- Create: `tests/unit/test_multi_agent_voice_history.py`
- Modify: `tests/unit/test_copilot_endpoint.py`
- Modify: `app/agent/multi_agent/state.py`
- Modify: `app/agent/multi_agent/graph.py`
- Modify: `app/agent/multi_agent/supervisor.py`
- Modify: `app/api/routers/copilot.py`

**Interfaces:**
- Adds `SupervisorState.turn_source: Literal["text", "voice"]`.
- Adds `record_multi_agent_question(state, config)` and `finalize_turn(state)`.
- Uses message `additional_kwargs["source"] == "voice"` as the presentation filter.

- [ ] **Step 1: Write failing source-tag tests**

Assert that `record_multi_agent_question` defaults to `text`, writes `voice` when `config.metadata.input_source` is set, and that `finalize_turn` replaces every AI message after the current voice HumanMessage with the same id plus `source=voice`. Assert the graph contains `finalize_turn` and every supervisor finish path targets it.

Add a history endpoint test with interleaved text and voice turns:

```python
assert [item["content"] for item in response.json()] == [
    "typed question",
    "typed answer",
    "typed follow-up",
    "typed follow-up answer",
]
```

The checkpoint must still contain the hidden voice HumanMessage and AIMessage.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `uv run pytest tests/unit/test_multi_agent_voice_history.py tests/unit/test_copilot_endpoint.py -v`

Expected: source fields, finalizer node, and history filtering are absent.

- [ ] **Step 3: Add the multi-agent-only record/finalize nodes**

Do not change the shared single-agent `record_question`. In `multi_agent/graph.py` add:

```python
def record_multi_agent_question(state: SupervisorState, config: RunnableConfig) -> dict:
    question = state.get("question")
    if not question:
        return {}
    source = (config.get("metadata") or {}).get("input_source", "text")
    return {
        "messages": [HumanMessage(content=question, additional_kwargs={"source": source})],
        "turn_source": source,
    }
```

`finalize_turn` must find the latest HumanMessage, and for a voice turn return copies of later AI messages with the same ids and merged `additional_kwargs={"source": "voice"}`. The `add_messages` reducer will replace by id. Text finalization returns `{}`.

Change `_finish()` to `Command(goto="finalize_turn", update={"next_agent": None})`, add the node to `_build_workflow`, and connect it to `END`.

- [ ] **Step 4: Filter voice messages in both AG-UI snapshots and history**

Add `_is_voice(message)` next to `_is_summary`. `MarketDeskAgent._filter_orphan_tool_messages` and `market_desk_history` must remove voice-tagged Human/AI messages for presentation while leaving graph state untouched.

- [ ] **Step 5: Run focused tests and commit**

Run: `uv run pytest tests/unit/test_multi_agent_voice_history.py tests/unit/test_copilot_endpoint.py tests/unit/test_multi_agent_graph_structure.py tests/unit/test_multi_agent_supervisor_routing.py -v`

Expected: all tests pass.

```bash
git add app/agent/multi_agent/state.py app/agent/multi_agent/graph.py app/agent/multi_agent/supervisor.py app/api/routers/copilot.py tests/unit/test_multi_agent_voice_history.py tests/unit/test_copilot_endpoint.py
git commit -m "feat(research): retain voice context outside visual history"
```

---

### Task 2: Enforce one active transport per thread

**Files:**
- Create: `app/agent/turn_coordinator.py`
- Create: `tests/unit/test_turn_coordinator.py`
- Modify: `tests/unit/test_copilot_endpoint.py`
- Modify: `tests/unit/test_stream.py`
- Modify: `tests/unit/test_agentcore_contract.py`
- Modify: `app/api/routers/copilot.py`
- Modify: `app/api/routers/stream.py`
- Modify: `app/api/routers/agentcore.py`
- Modify: `app/api/server.py`

**Interfaces:**
- Produces immutable `TurnLease(thread_id, owner, token)`.
- Produces async `try_acquire(thread_id, owner)`, `release(lease)`, and `owner(thread_id)`.
- Returns HTTP 409 from Copilot/AgentCore typed runs when voice owns the thread; legacy SSE returns an `error` event without invoking the graph.

- [ ] **Step 1: Write failing lease tests**

Cover first acquisition, rejection of a second owner, release with the correct token, ignored stale release, and independent threads. In the Copilot and AgentCore endpoint tests, pre-acquire the Research thread as `voice:test` and assert POST returns 409 without running the graph. In `/stream`, assert the same conflict emits one `error` SSE frame and does not call `astream`. Add failure cases asserting every typed lease is released in `finally`.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `uv run pytest tests/unit/test_turn_coordinator.py tests/unit/test_copilot_endpoint.py -v`

Expected: imports fail because the coordinator does not exist.

- [ ] **Step 3: Implement the coordinator**

Use one `asyncio.Lock`, a dictionary keyed by thread id, and a UUID token. `release` removes ownership only when all three lease fields match.

```python
lease = await coordinator.try_acquire(input_data.thread_id, f"text:{input_data.run_id}")
if lease is None:
    raise HTTPException(status_code=409, detail="Voice mode is active for this thread.")
```

Acquire before constructing Copilot's `StreamingResponse`; release inside the events generator's `finally`. AgentCore holds a lease only around one prompt invocation. Legacy `/stream` acquires at the start of its event generator, emits an `error` frame when unavailable, and releases in `finally`. Approval resume endpoints do not acquire a new turn because they complete an already-paused turn. Instantiate `app.state.turn_coordinator = ThreadTurnCoordinator()` during lifespan.

- [ ] **Step 4: Run focused tests and commit**

Run: `uv run pytest tests/unit/test_turn_coordinator.py tests/unit/test_copilot_endpoint.py tests/unit/test_stream.py tests/unit/test_agentcore_contract.py tests/unit/test_server_wiring.py -v`

Expected: all tests pass.

```bash
git add app/agent/turn_coordinator.py app/api/routers/copilot.py app/api/routers/stream.py app/api/routers/agentcore.py app/api/server.py tests/unit/test_turn_coordinator.py tests/unit/test_copilot_endpoint.py tests/unit/test_stream.py tests/unit/test_agentcore_contract.py
git commit -m "feat(research): serialize text and voice turns"
```

---

### Task 3: Add bounded Research voice state and activity contracts

**Files:**
- Create: `app/voice/activity_store.py`
- Create: `tests/unit/test_voice_activity_store.py`
- Modify: `app/api/models/models.py`
- Modify: `app/api/server.py`

**Interfaces:**
- `VoicePhase = connecting | listening | analyzing | speaking | approval_required | disconnected | error`.
- `VoiceActivityEvent` fields: `sequence`, `run_id`, `kind`, `name`, `tool_call_id`, `duration_ms`, `message`.
- `VoiceStateResponse` fields: `phase`, `sequence`, `events`, `pending`, `error`.

- [ ] **Step 1: Write failing bounded-store tests**

Cover session reset, monotonically increasing sequence values, `after` filtering, a 200-event cap, pending approval preservation after disconnect, and user-safe error messages that never echo exception details or secrets.

- [ ] **Step 2: Run and confirm RED**

Run: `uv run pytest tests/unit/test_voice_activity_store.py -v`

Expected: the new module is missing.

- [ ] **Step 3: Implement thread-safe store records**

Use a `threading.RLock` and `collections.deque(maxlen=200)`. Define these event kinds exactly:

```python
VoiceActivityKind = Literal[
    "specialist_started",
    "tool_started",
    "tool_finished",
    "approval_required",
    "run_finished",
    "run_error",
]
```

Expose `begin_session`, `set_phase`, `append_event`, `set_pending`, `snapshot`, and `end_session`. `end_session` changes phase but does not erase an unresolved pending approval. Log detailed exceptions server-side; store only fixed safe messages such as `Voice processing failed` or `Voice session disconnected`.

- [ ] **Step 4: Add Pydantic response models and app state**

Add `VoiceActivityEventResponse`, `VoicePendingApprovalResponse`, `VoiceStateResponse`, `VoiceDecisionRequest`, and `VoiceDecisionResponse`. Instantiate one `VoiceActivityStore` as `app.state.voice_activity_store`.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest tests/unit/test_voice_activity_store.py tests/unit/test_server_wiring.py -v`

Expected: all tests pass.

```bash
git add app/voice/activity_store.py app/api/models/models.py app/api/server.py tests/unit/test_voice_activity_store.py
git commit -m "feat(voice): add research activity state"
```

---

### Task 4: Build the shared multi-agent Research voice runtime

**Files:**
- Create: `app/voice/research_runtime.py`
- Create: `tests/unit/test_research_voice_runtime.py`
- Modify: `app/api/server.py`

**Interfaces:**
- Produces `ResearchVoiceRuntime.run_turn(thread_id, question) -> VoiceTurnResult`.
- Produces `ResearchVoiceRuntime.resolve(thread_id, interrupt_id, decisions) -> VoiceDecisionResult`.
- Produces `HitlDecisionCoordinator.resolve(thread_id, interrupt_id, resume)` with first-decision-wins semantics.

- [ ] **Step 1: Write failing runtime tests**

Use a fake nested graph stream. Cover specialist start, tool start/result duration, completed reply, pending interrupt, approve, reject, duplicate visual/spoken decisions, resume failure, and `metadata={"input_source": "voice"}`. Assert the resume callable runs exactly once for duplicate decisions.

- [ ] **Step 2: Run and confirm RED**

Run: `uv run pytest tests/unit/test_research_voice_runtime.py -v`

Expected: the runtime module is missing.

- [ ] **Step 3: Normalize nested graph events**

Run the graph with:

```python
config = {
    "configurable": {"thread_id": thread_id, "actor_id": "mia-agent"},
    "metadata": {"input_source": "voice"},
}
async for namespace, mode, chunk in graph.astream(
    input_value,
    config,
    stream_mode=["updates"],
    subgraphs=True,
):
```

Root specialist nodes emit `specialist_started`. Nested AI tool calls emit `tool_started`; matching ToolMessages emit `tool_finished`. After the stream, inspect `aget_state(config, subgraphs=True)` with the shared helper. A pending interrupt stores its stable id/raw action data and sets `approval_required`; otherwise extract the final plain AI reply and leave the phase at `analyzing` until the sideband worker observes output audio.

- [ ] **Step 4: Implement idempotent decision resolution**

Keep one async lock per thread and a stored result keyed by `(thread_id, interrupt_id)`. Under the lock, return the stored result when present; otherwise verify the currently pending id, execute the supplied resume coroutine with `Command(resume={"decisions": decisions})`, store the outcome, and clear pending only after the graph accepts it. A stale id returns a 409-compatible result and never invokes the graph.

- [ ] **Step 5: Attach the runtime to FastAPI state**

Construct it from the shared `agent_graph` and `voice_activity_store` in lifespan as `app.state.research_voice_runtime`.

- [ ] **Step 6: Run focused tests and commit**

Run: `uv run pytest tests/unit/test_research_voice_runtime.py tests/unit/test_multi_agent_hitl.py tests/unit/test_server_wiring.py -v`

Expected: all tests pass.

```bash
git add app/voice/research_runtime.py app/api/server.py tests/unit/test_research_voice_runtime.py
git commit -m "feat(voice): route spoken research through specialists"
```

---

### Task 5: Expose Research voice HTTP and sideband behavior

**Files:**
- Create: `tests/unit/test_research_voice_api.py`
- Modify: `tests/unit/test_voice_transcript.py`
- Modify: `app/core/config.py`
- Modify: `app/api/models/models.py`
- Modify: `app/api/routers/gptlive_session.py`
- Modify: `app/voice/worker.py`

**Interfaces:**
- `POST /gptlive/session` accepts `surface: "classic" | "research" | null`.
- `GET /voice/{thread_id}/state?after=<sequence>` returns no transcript field.
- `POST /voice/{thread_id}/decision` accepts `interrupt_id` and `decisions`.

- [ ] **Step 1: Write failing API tests**

Mock OpenAI Live creation and the worker. Cover Classic omission compatibility, Research lease acquisition, 409 when a typed owner exists, 409 when the graph is already paused, empty/oversized SDP rejection, allowed and rejected browser origins, state pagination, visual decision forwarding, stale decision 409, and lease release when negotiation or worker execution fails.

Assert a Research worker call receives `surface="research"`, the shared Research runtime, activity store, and its lease. Assert a Classic call still receives `voice_agent_app` and appends to `transcript_store`.

- [ ] **Step 2: Run focused API tests and confirm RED**

Run: `uv run pytest tests/unit/test_research_voice_api.py tests/unit/test_voice_transcript.py -v`

Expected: `surface`, state, and decision contracts do not exist.

- [ ] **Step 3: Validate session input and acquire before negotiation**

Define `sdp: str = Field(min_length=1, max_length=200_000)` and `surface` defaulting to `classic` when omitted. Add `VOICE_ALLOWED_ORIGINS`, defaulting to `http://127.0.0.1:5173,http://localhost:5173`, parse it into an exact allowlist, and return 403 before contacting OpenAI when a browser `Origin` header is present but not allowed. Preserve requests without `Origin` for existing trusted non-browser/Classic callers. For Research, acquire `voice:<request_uuid>` before `_client.live.create`; release it on every exception. Reject an existing pending interrupt before contacting OpenAI.

- [ ] **Step 4: Split worker behavior without duplicating WebRTC**

Keep one sideband connection and transcript buffer. Classic delegates to the existing `_handle_delegation`. Research:

- sets `listening` when connected;
- calls `ResearchVoiceRuntime.run_turn` for a normal utterance;
- when approval is pending, classifies only the short approve/reject utterance and calls `runtime.resolve`;
- speaks the runtime reply via `session.commentary.append`;
- changes to `speaking` on reflected `session.output_audio.delta` events and returns to `listening` after a 350 ms no-audio debounce;
- never appends Research messages to `transcript_store`;
- releases the voice lease in the worker's outer `finally`.

Keep one delegation task reference instead of blocking the sideband event loop inside it. On `session.closed`, cancel the active delegation task, ignore late commentary, and release the lease. A cancelled read-only graph call may finish internally, but approval-gated tools remain paused. Add a test that closes the session during analysis and observes cancellation plus lease release.

- [ ] **Step 5: Add state and decision endpoints**

The state endpoint returns the store snapshot after the requested sequence. The decision endpoint calls the runtime and maps applied/already-applied to 200, stale/mismatched ids to 409. It accepts the same decision objects used by `ApprovalPanel`, including visual edits.

- [ ] **Step 6: Run backend voice regressions and commit**

Run: `uv run pytest tests/unit/test_research_voice_api.py tests/unit/test_voice_transcript.py tests/unit/test_voice_hitl_classify.py tests/unit/test_research_voice_runtime.py -v`

Expected: all tests pass and Classic transcript tests are unchanged.

```bash
git add app/core/config.py app/api/models/models.py app/api/routers/gptlive_session.py app/voice/worker.py tests/unit/test_research_voice_api.py tests/unit/test_voice_transcript.py
git commit -m "feat(voice): expose research session and approval APIs"
```

---

### Task 6: Implement the browser voice lifecycle hook

**Files:**
- Create: `frontend/src/voice/types.ts`
- Create: `frontend/src/voice/voiceApi.ts`
- Create: `frontend/src/voice/useResearchVoice.ts`
- Create: `frontend/src/voice/useResearchVoice.test.tsx`

**Interfaces:**
- Produces `useResearchVoice(threadId, enabled)` returning `phase`, `active`, `events`, `pending`, `error`, `start`, `end`, and `submitDecision`.
- Uses the backend field names from Tasks 3 and 5 without a second schema.

- [ ] **Step 1: Write failing lifecycle tests**

Mock `navigator.mediaDevices.getUserMedia`, `RTCPeerConnection`, `RTCDataChannel`, audio playback, timers, and fetch. Cover permission denial, data-channel-before-offer ordering, ICE-gathering completion, `surface: "research"`, `session.started`, state polling with `after`, server 409, connection loss, `session.closed`, explicit end, unmount cleanup, and idempotent cleanup.

Assert cleanup stops every microphone track, sends `{"type":"session.close"}` when the channel is open, keeps media alive while finalization is pending, then closes channel and peer connection, clears polling, removes the audio element, and restores inactive state after `session.closed` or the forced timeout.

- [ ] **Step 2: Run and confirm RED**

Run: `npm test -- --run src/voice/useResearchVoice.test.tsx`

Expected: the hook module is missing.

- [ ] **Step 3: Implement typed API functions**

Add `createResearchVoiceSession`, `getResearchVoiceState`, and `submitResearchVoiceDecision` using `API_BASE`. On non-2xx responses, surface the server detail string.

- [ ] **Step 4: Implement the WebRTC state machine**

Create the data channel before `createOffer`, add microphone tracks, wait for ICE gathering to complete with a 10-second timeout, POST the SDP offer, apply the answer, and transition from `Connecting…` only after `session.started`. Poll voice state only while active. Use one cleanup function guarded by a ref. Explicit end sends `session.close`, keeps media/events alive for finalization, and performs forced cleanup after 15 seconds if `session.closed` never arrives, matching the current GPT-Live WebRTC lifecycle.

- [ ] **Step 5: Run tests and commit**

Run: `npm test -- --run src/voice/useResearchVoice.test.tsx`

Expected: all lifecycle tests pass.

```bash
git add frontend/src/voice/types.ts frontend/src/voice/voiceApi.ts frontend/src/voice/useResearchVoice.ts frontend/src/voice/useResearchVoice.test.tsx
git commit -m "feat(voice): manage research WebRTC lifecycle"
```

---

### Task 7: Replace the Research composer with the approved voice bar

**Files:**
- Create: `frontend/src/voice/VoiceModeBar.tsx`
- Create: `frontend/src/voice/VoiceModeBar.test.tsx`
- Create: `frontend/src/voice/ResearchVoiceContext.tsx`
- Create: `frontend/src/desk/ResearchComposer.tsx`
- Create: `frontend/src/desk/ResearchComposer.test.tsx`
- Modify: `frontend/src/desk/DeskView.tsx`
- Modify: `frontend/src/desk/DeskView.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/clients/ClientWorkspace.tsx`

**Interfaces:**
- `DeskViewProps = { threadId: string; voiceEnabled?: boolean }` with default `false`.
- `ResearchComposer` implements CopilotKit v2's `CopilotChatInputProps` slot contract.

- [ ] **Step 1: Write failing presentation tests**

Cover exact labels `Connecting…`, `Listening…`, `Analyzing…`, `Speaking…`, `Approval required`, `Voice mode · Text input locked`, `Say Approve or Reject · or use the card`, and `End voice mode`. Assert the voice bar contains no specialist name. Assert reduced-motion styles suppress the waveform animation.

In `DeskView.test.tsx`, assert `/research` capability renders a microphone action and `ClientWorkspace` does not. Assert active voice renders no textbox and inactive voice restores it.

- [ ] **Step 2: Run component tests and confirm RED**

Run: `npm test -- --run src/voice/VoiceModeBar.test.tsx src/desk/ResearchComposer.test.tsx src/desk/DeskView.test.tsx`

Expected: the new components and `voiceEnabled` prop are absent.

- [ ] **Step 3: Implement the presentation-only bar**

Render a compact bordered bar with an accessible status region, five animated columns for listening/speaking, a restrained analyzing motion, the lock caption, and an `End voice mode` button. Keep all activity detail out of this component.

- [ ] **Step 4: Use CopilotKit's input slot**

`ResearchComposer` renders `VoiceModeBar` when the voice context is active. Otherwise it renders `CopilotChatInput` with the existing visual props plus a microphone button. Disable microphone start when `isRunning`, a typed approval is pending, or voice is disabled. Do not query or mutate CopilotKit DOM nodes.

Pass the slot component through `CopilotChat input={ResearchComposer}`. Wrap only voice-enabled `DeskView` in `ResearchVoiceContext`. In `App.tsx` pass `voiceEnabled` for `/research`; leave `ClientWorkspace` explicit with `voiceEnabled={false}`.

- [ ] **Step 5: Run tests and commit**

Run: `npm test -- --run src/voice/VoiceModeBar.test.tsx src/desk/ResearchComposer.test.tsx src/desk/DeskView.test.tsx`

Expected: all tests pass.

```bash
git add frontend/src/voice/VoiceModeBar.tsx frontend/src/voice/VoiceModeBar.test.tsx frontend/src/voice/ResearchVoiceContext.tsx frontend/src/desk/ResearchComposer.tsx frontend/src/desk/ResearchComposer.test.tsx frontend/src/desk/DeskView.tsx frontend/src/desk/DeskView.test.tsx frontend/src/App.tsx frontend/src/clients/ClientWorkspace.tsx
git commit -m "feat(research): add exclusive animated voice composer"
```

---

### Task 8: Merge voice activity and HITL into the existing Research UI

**Files:**
- Create: `frontend/src/voice/ResearchVoiceApproval.tsx`
- Create: `frontend/src/voice/ResearchVoiceApproval.test.tsx`
- Modify: `frontend/src/desk/activity.ts`
- Modify: `frontend/src/desk/activity.test.ts`
- Modify: `frontend/src/desk/DeskActivityRail.tsx`
- Modify: `frontend/src/desk/DeskActivityRail.test.tsx`
- Modify: `frontend/src/desk/useDeskInterrupt.tsx`
- Modify: `frontend/src/desk/DeskView.tsx`

**Interfaces:**
- Adds `voiceActivityToAgUi(event)` and optional `voiceEvents` input to `DeskActivityRail`.
- `ResearchVoiceApproval` adapts `VoicePendingApproval` to the existing `ApprovalPanel`.
- `useDeskInterrupt(onPendingChange)` reports typed approval mount/unmount to the composer gate.

- [ ] **Step 1: Write failing activity and approval tests**

Map every backend voice activity kind to the existing reducer contract. Assert specialist, tool, duration, waiting, done, and error rows appear once in sequence order. Render a voice email approval and assert the generated-report selector and edit workflow remain available. Click approve twice and assert the API function is called once.

- [ ] **Step 2: Run and confirm RED**

Run: `npm test -- --run src/desk/activity.test.ts src/desk/DeskActivityRail.test.tsx src/voice/ResearchVoiceApproval.test.tsx`

Expected: external activity and the voice approval adapter are absent.

- [ ] **Step 3: Normalize voice events into the existing reducer**

Use these mappings:

```typescript
specialist_started -> STEP_STARTED
tool_started       -> TOOL_CALL_START
tool_finished      -> TOOL_CALL_RESULT
approval_required  -> RUN_FINISHED with outcome.type = "interrupt"
run_finished       -> RUN_FINISHED
run_error          -> RUN_ERROR
```

Track the last consumed sequence in a ref so polling does not duplicate rows. Keep CopilotKit subscription behavior unchanged for typed runs.

- [ ] **Step 4: Reuse the approval card**

Adapt the pending payload through `readApproval({ metadata: { langgraph: { raw: pending } } })`. Submit the card's decisions with the stable interrupt id. Lock the card immediately after the first click; applied and already-applied responses both clear the local submission state from the user's perspective.

Render the card above the composer while pending, including after a disconnect. Spoken decisions update the same polled state, so a card resolved by speech disappears without a second resume.

- [ ] **Step 5: Run frontend feature tests and commit**

Run: `npm test -- --run src/desk/activity.test.ts src/desk/DeskActivityRail.test.tsx src/desk/ApprovalPanel.test.tsx src/voice/ResearchVoiceApproval.test.tsx src/desk/DeskView.test.tsx`

Expected: all tests pass.

```bash
git add frontend/src/voice/ResearchVoiceApproval.tsx frontend/src/voice/ResearchVoiceApproval.test.tsx frontend/src/desk/activity.ts frontend/src/desk/activity.test.ts frontend/src/desk/DeskActivityRail.tsx frontend/src/desk/DeskActivityRail.test.tsx frontend/src/desk/useDeskInterrupt.tsx frontend/src/desk/DeskView.tsx
git commit -m "feat(research): unify voice activity and approvals"
```

---

### Task 9: Complete automated and live acceptance

**Files:**
- Modify: `docs/VOICE.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Documents Research voice session, state, decision, hidden-history, and Classic compatibility contracts.

- [ ] **Step 1: Run all backend tests**

Run: `uv run pytest tests/ -v`

Expected: the complete backend suite passes.

- [ ] **Step 2: Run all frontend tests and production build**

Run:

```bash
npm test
npm run build
```

Run from `frontend/`. Expected: the complete Vitest suite and TypeScript/Vite build pass.

- [ ] **Step 3: Update documentation**

Document the new Research-only flow, exact English states, three HTTP contracts, voice source tagging, lease behavior, first-decision-wins rule, and manual recovery after disconnect. Keep the Classic section clearly separated.

- [ ] **Step 4: Restart the application from this worktree**

Stop only the existing project processes on ports 8000 and 5173, then start FastAPI and Vite from this worktree. Confirm:

- `http://127.0.0.1:8000/health` returns healthy;
- `http://127.0.0.1:5173/research` loads;
- `/clients/<id>` remains text-only.

- [ ] **Step 5: Perform microphone acceptance scenarios**

Run these scenarios in order:

1. Start and end voice without asking a question; text returns and the mic is released.
2. Ask for a current stock price; Finance appears in Intelligence and the answer is spoken.
3. Ask an open-ended market question; RAG appears, not Browser unless a site is named.
4. Ask for a client's portfolio analysis; Portfolio and its tools appear with durations.
5. Request an email; approve verbally and verify one send only.
6. Request another email; attach a generated report and approve from the visual card.
7. Disconnect while approval is pending; verify the card remains and resolves visually.
8. End voice, type a contextual follow-up, and verify the graph remembers the spoken context while no voice transcript appears.
9. Open a second tab on the same thread and verify concurrent typed/voice starts receive 409.
10. Deny microphone permission and verify the composer remains available.

- [ ] **Step 6: Commit documentation and any acceptance-only test correction**

```bash
git add docs/VOICE.md AGENTS.md CLAUDE.md
git commit -m "docs(voice): document multi-agent research mode"
```

- [ ] **Step 7: Record final evidence without merging**

Capture the exact passing test counts, build result, live URLs, manual scenarios, branch name, and final commit. Leave `feat/product-ui-modernization` unmerged and unpushed unless the user later asks.
