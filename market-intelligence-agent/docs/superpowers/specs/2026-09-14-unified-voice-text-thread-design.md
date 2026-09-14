# Unified Voice + Text Conversation Thread

**Author:** Yaniv Bohbot (with Claude pair-programming)
**Date:** 2026-09-14
**Status:** Approved — ready for implementation
**Companion plan:** `docs/superpowers/plans/2026-09-14-unified-voice-text-thread.md`

## Problem

Voice and text mode currently run on separate LangGraph threads (`voice-<gpt_live_session_id>` vs `web_session_<uuid>`, per `CLAUDE.md`), so they are two independent conversations with independent memory even though they run in the same browser tab. A user who greets the agent by voice, sees the (Hebrew) greeting appear in the main Streamlit chat (already shipped this session via `app/voice/transcript_store.py` + a polling fragment in `app/ui/app.py`), and then types a reply gets no continuity — the typed message starts a brand-new conversation the agent has no memory of.

Separately, `app/api/routers/stream.py`'s `/stream` endpoint always calls `agent_app.astream(inputs, config, ...)` with a fresh `{"question": ...}` input — never `Command(resume=...)`. If a shared thread is paused awaiting HITL approval and a plain new message is sent into it via `/stream`, LangGraph will not resume the pending interrupt correctly; this is the same class of bug already tracked as "thread poisoning on MCP tool error" in project memory.

## Goals

1. One LangGraph thread per browser tab, shared by text and voice, so replying by voice to something asked in text (or vice versa) continues the same conversation.
2. HITL interrupts stay safe under the unified thread regardless of which modality triggered them:
   - Approve/Reject buttons work (existing `/approve` path, unchanged).
   - Spoken "yes"/"no" during voice keeps working (existing `hitl.py` path, unchanged).
   - Free-typed text is blocked while a pause is pending (`chat_input(disabled=...)`, matching today's text-only behavior) — confirmed with the user; no interrupt-resume logic is added to `/stream`.
3. Streamlit must learn about a pause that originated from a *voice* turn (today it only learns about pauses from its own synchronous `/stream` call), so it can disable input and show the buttons regardless of origin, and re-enable when voice resolves it via spoken yes/no.

## Non-goals

- Changing `/stream`'s fresh-input behavior for the non-paused case.
- Adding text-based interrupt resume (typing "yes" while paused) — user explicitly chose buttons/voice-only for resume.
- Disabling voice's existing spoken yes/no — user explicitly chose to keep it.
- Any change to the LangGraph graphs themselves (`app/agent/graph.py`, `app/voice/graph.py`) — both already compile against the same checkpointer instance (`app/api/server.py`) and share `AgentState`, and `app/voice/graph.py`'s docstring already anticipates thread sharing. No graph-level change is needed.

## Solution

### 1. Single shared `thread_id`

`app/ui/app.py` stops generating a separate `voice_thread_id`. `st.session_state.thread_id` (already used for `/stream`) is passed into `render_voice_panel(thread_id=..., height=...)`, which already forwards it to `POST /gptlive/session` → `run_delegation_worker(session_id, thread_id, agent_app)`. No change needed in `gptlive_session.py` beyond what's already there (`thread_id = payload.thread_id or f"voice-{session_id}"`).

### 2. Extend the polling endpoint with pause status

`GET /voice/{thread_id}/transcript` (in `app/api/routers/gptlive_session.py`) gains two response fields, computed by calling the existing `app/voice/hitl.py::is_interrupted(agent_app, thread_id)` helper (no new interrupt-detection logic — reuse):

```python
class VoiceTranscriptResponse(BaseModel):
    messages: list[VoiceTranscriptEntry]
    last_id: int
    paused: bool
    action: str | None
```

`is_interrupted` needs an `agent_app`; either compiled graph works since both share the same checkpointer and `AgentState` schema, so the pause/resume state lives in the checkpointer, not in either graph object. The endpoint uses `request.app.state.voice_agent_app` (already in scope in this router).

### 3. Streamlit reacts to pause transitions

The existing polling fragment in `app/ui/app.py` (`_poll_voice_transcript`, `run_every="1s"`, gated on `st.session_state.voice_on`) additionally reads `paused`/`action` from each response and compares against `st.session_state.awaiting_approval`:

- `False → True`: set `st.session_state.awaiting_approval = True`, `st.session_state.last_action = action`, call `st.rerun()`. This is a full rerun (fragments' `st.rerun()` defaults to full-app scope), so it renders the existing Approve/Reject block and disables `chat_input`, identical to what a text-triggered interrupt does today.
- `True → False`: clear `awaiting_approval`, call `st.rerun()`. Covers voice resolving the pause via spoken yes/no — buttons disappear, typing re-enables.
- No-op (no rerun) when the polled state matches what Streamlit already believes, to avoid a rerun loop.

### 4. Docs

`CLAUDE.md`'s "Voice and text sessions use different `thread_id`s" line is corrected to describe the shared thread.

## Data flow (pause originating from voice)

```
user speaks "send an email to..." 
  → worker.py: agent_app.ainvoke(...) 
  → approval_node interrupts (side-effect tool call) 
  → worker.py's is_interrupted() check (next turn) would see paused=True,
    but the CURRENT turn's ainvoke already returned with the graph paused —
    worker asks "Say yes or no" via commentary.append + transcript_store
  → Streamlit fragment polls /voice/{thread}/transcript within ~1s,
    sees paused=True, action="send_email with args {...}"
  → st.session_state.awaiting_approval = True, st.rerun()
  → chat_input disabled, Approve/Reject buttons shown
  → user says "yes" OR clicks Approve
    - voice path: hitl.classify_verdict("yes") → resume_with() → graph resumes,
      transcript_store gets the final reply; next poll sees paused=False → clears flag
    - button path: POST /approve → Command(resume="approve") → existing code path,
      awaiting_approval cleared synchronously (unchanged)
```

## Error handling

- Polling endpoint failures (network error, non-2xx) are already swallowed by the fragment's existing `try/except requests.exceptions.RequestException: return` — a transient failure just means the pause is detected on a later tick, not a broken state.
- `is_interrupted` already only reports `paused=True` when the graph is specifically stopped at the `approval` node (not for any other non-empty `snapshot.next`), so unrelated paused states (e.g. a retry-pending task) don't spuriously lock the UI — this logic is unchanged, just reused.

## Testing

- Unit test for the extended transcript endpoint: mock `app.voice.hitl.is_interrupted` to return `(True, "send_email with args {...}")` and assert the response includes `paused=True` and the action string; mock it to return `(False, None)` and assert `paused=False`. Follows the mocking style already used in `tests/unit/test_hitl_interrupt.py`.
- Existing `tests/unit/test_voice_transcript.py` extended to assert the new response fields are present and default to `paused=False` for a thread with no interrupt.
- Manual click-through (both directions) once servers are running: voice-triggered pause shows buttons in the main chat; approving by voice clears them; approving by button also clears them.

## Files touched

- `app/api/models/models.py` — `VoiceTranscriptResponse` gains `paused`, `action`.
- `app/api/routers/gptlive_session.py` — `get_voice_transcript` calls `is_interrupted`.
- `app/ui/app.py` — drop `voice_thread_id`, share `thread_id`; extend `_poll_voice_transcript` with pause-transition handling.
- `CLAUDE.md` — correct the thread_id documentation.
- `tests/unit/test_voice_transcript.py` — new assertions for `paused`/`action`.
