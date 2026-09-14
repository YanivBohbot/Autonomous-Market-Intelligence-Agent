# Unified Voice + Text Conversation Thread Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Text mode and voice mode share one LangGraph thread per browser tab, and the Streamlit UI shows/clears the Approve/Reject HITL prompt regardless of whether the pause was triggered by a typed or a spoken turn.

**Architecture:** `app/ui/app.py` stops minting a separate `voice_thread_id` and passes its existing `thread_id` into the voice panel. `GET /voice/{thread_id}/transcript` (already returning new transcript messages) also reports whether the graph is currently paused at the `approval` node, reusing `app/voice/hitl.py::is_interrupted`. The Streamlit polling fragment that already mirrors voice text into the chat now also drives `st.session_state.awaiting_approval` off that field.

**Tech Stack:** FastAPI (Pydantic response models), Streamlit (`st.fragment`), pytest + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-09-14-unified-voice-text-thread-design.md`

## Global Constraints

- Free-typed text stays blocked while a pause is pending — no interrupt-resume logic is added to `/stream`. (spec "Non-goals")
- Spoken yes/no must keep working exactly as today — no changes to `app/voice/hitl.py` or `app/voice/worker.py`'s confirmation flow. (spec "Non-goals")
- No changes to `app/agent/graph.py` or `app/voice/graph.py`. (spec "Non-goals")
- Reuse `app/voice/hitl.py::is_interrupted(agent_app, thread_id) -> tuple[bool, str | None]` for pause detection — do not duplicate its logic. (spec "Solution" §2)

---

### Task 1: Extend the transcript endpoint with pause status

**Files:**
- Modify: `app/api/models/models.py` (the `VoiceTranscriptResponse` class, currently `messages: list[VoiceTranscriptEntry]`, `last_id: int`)
- Modify: `app/api/routers/gptlive_session.py:54-58` (`get_voice_transcript`)
- Test: `tests/unit/test_voice_transcript.py`

**Interfaces:**
- Consumes: `app.voice.hitl.is_interrupted(agent_app, thread_id: str) -> tuple[bool, str | None]` (existing, unchanged).
- Produces: `VoiceTranscriptResponse` now has `paused: bool` and `action: str | None`, consumed by Task 2.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_voice_transcript.py` (existing file — keep its current imports and `client = TestClient(app)`):

```python
from unittest.mock import AsyncMock, patch


def test_transcript_endpoint_reports_paused_state():
    thread_id = "voice-test-thread-paused"

    with patch(
        "app.api.routers.gptlive_session.is_interrupted",
        new=AsyncMock(return_value=(True, "send_email with args {'to': 'x@y.com'}")),
    ):
        res = client.get(f"/voice/{thread_id}/transcript", params={"after": 0})

    assert res.status_code == 200
    body = res.json()
    assert body["paused"] is True
    assert body["action"] == "send_email with args {'to': 'x@y.com'}"


def test_transcript_endpoint_reports_not_paused():
    thread_id = "voice-test-thread-not-paused"

    with patch(
        "app.api.routers.gptlive_session.is_interrupted",
        new=AsyncMock(return_value=(False, None)),
    ):
        res = client.get(f"/voice/{thread_id}/transcript", params={"after": 0})

    assert res.status_code == 200
    body = res.json()
    assert body["paused"] is False
    assert body["action"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_voice_transcript.py -v`
Expected: the two new tests FAIL with `KeyError: 'paused'` (field doesn't exist yet in the response).

- [ ] **Step 3: Extend the response model**

In `app/api/models/models.py`, change:

```python
class VoiceTranscriptResponse(BaseModel):
    messages: list[VoiceTranscriptEntry]
    last_id: int
```

to:

```python
class VoiceTranscriptResponse(BaseModel):
    messages: list[VoiceTranscriptEntry]
    last_id: int
    paused: bool
    action: Optional[str] = None
```

(`Optional` is already imported at the top of this file.)

- [ ] **Step 4: Wire the endpoint to `is_interrupted`**

In `app/api/routers/gptlive_session.py`, add the import and update the endpoint:

```python
from app.voice.hitl import is_interrupted
```

Replace:

```python
@router.get("/voice/{thread_id}/transcript", response_model=VoiceTranscriptResponse)
async def get_voice_transcript(thread_id: str, after: int = 0) -> VoiceTranscriptResponse:
    entries = transcript_store.get_after(thread_id, after)
    last_id = entries[-1]["id"] if entries else after
    return VoiceTranscriptResponse(messages=entries, last_id=last_id)
```

with:

```python
@router.get("/voice/{thread_id}/transcript", response_model=VoiceTranscriptResponse)
async def get_voice_transcript(
    thread_id: str, request: Request, after: int = 0
) -> VoiceTranscriptResponse:
    entries = transcript_store.get_after(thread_id, after)
    last_id = entries[-1]["id"] if entries else after
    agent_app = request.app.state.voice_agent_app
    paused, action = await is_interrupted(agent_app, thread_id)
    return VoiceTranscriptResponse(
        messages=entries, last_id=last_id, paused=paused, action=action
    )
```

Note: `Request` is already imported in this file (used by `create_session`). `after` keeps its default and must stay last in the parameter list for plain Python syntax; FastAPI resolves `thread_id` from the path, `request` by type, and `after` from the query string regardless of order.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_voice_transcript.py -v`
Expected: all tests PASS, including the two new ones and the three pre-existing ones in this file.

- [ ] **Step 6: Run the full suite to check nothing else broke**

Run: `uv run pytest tests/ -q`
Expected: all tests PASS (40 existing + 2 new = 42).

- [ ] **Step 7: Commit**

```bash
git add app/api/models/models.py app/api/routers/gptlive_session.py tests/unit/test_voice_transcript.py
git commit -m "feat(voice): report HITL pause status from the transcript endpoint"
```

---

### Task 2: Share one thread_id between text and voice, and react to voice-triggered pauses in Streamlit

**Files:**
- Modify: `app/ui/app.py`

**Interfaces:**
- Consumes: `VoiceTranscriptResponse` fields from Task 1 (`paused: bool`, `action: str | None`), via the existing `GET /voice/{thread_id}/transcript` call already made in `_poll_voice_transcript`.
- Produces: nothing consumed by a later task — this is the last code task.

- [ ] **Step 1: Remove the separate voice thread id**

In `app/ui/app.py`, delete these lines (currently lines 18-19):

```python
if "voice_thread_id" not in st.session_state:
    st.session_state.voice_thread_id = f"voice_session_{uuid.uuid4().hex[:8]}"
```

- [ ] **Step 2: Pass the shared thread_id into the voice panel**

Change:

```python
        render_voice_panel(st.session_state.voice_thread_id, height=380)
```

to:

```python
        render_voice_panel(st.session_state.thread_id, height=380)
```

Also update the caption text just above it — change:

```python
        st.caption(
            "Click **Connect** in the panel below, allow mic access, then speak. "
            "Voice runs on a separate `thread_id` from the text chat — the agent's "
            "spoken replies also appear as text in the chat below."
        )
```

to:

```python
        st.caption(
            "Click **Connect** in the panel below, allow mic access, then speak. "
            "Voice shares the same conversation as the text chat below — the "
            "agent's spoken replies also appear here as text."
        )
```

- [ ] **Step 3: Point the polling fragment at the shared thread_id**

Change:

```python
        res = requests.get(
            f"{API_URL}/voice/{st.session_state.voice_thread_id}/transcript",
            params={"after": st.session_state.voice_transcript_last_id},
            timeout=5,
        )
```

to:

```python
        res = requests.get(
            f"{API_URL}/voice/{st.session_state.thread_id}/transcript",
            params={"after": st.session_state.voice_transcript_last_id},
            timeout=5,
        )
```

- [ ] **Step 4: React to pause transitions in the fragment**

Replace the whole `_poll_voice_transcript` function body (currently):

```python
@st.fragment(run_every="1s")
def _poll_voice_transcript():
    if not st.session_state.get("voice_on"):
        return
    try:
        res = requests.get(
            f"{API_URL}/voice/{st.session_state.thread_id}/transcript",
            params={"after": st.session_state.voice_transcript_last_id},
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
    except requests.exceptions.RequestException:
        return

    new_messages = data.get("messages", [])
    if not new_messages:
        return
    st.session_state.voice_transcript_last_id = data.get(
        "last_id", st.session_state.voice_transcript_last_id
    )
    for m in new_messages:
        st.session_state.messages.append({"role": m["role"], "content": m["content"]})
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
```

with:

```python
@st.fragment(run_every="1s")
def _poll_voice_transcript():
    if not st.session_state.get("voice_on"):
        return
    try:
        res = requests.get(
            f"{API_URL}/voice/{st.session_state.thread_id}/transcript",
            params={"after": st.session_state.voice_transcript_last_id},
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
    except requests.exceptions.RequestException:
        return

    new_messages = data.get("messages", [])
    if new_messages:
        st.session_state.voice_transcript_last_id = data.get(
            "last_id", st.session_state.voice_transcript_last_id
        )
        for m in new_messages:
            st.session_state.messages.append({"role": m["role"], "content": m["content"]})
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

    # A pause can be triggered by a voice turn, which Streamlit has no other
    # way to learn about — worker.py runs as a background task with no
    # direct line back into this process. Mirror that state into the same
    # awaiting_approval flag the text-mode /stream 'interrupted' event uses.
    paused = data.get("paused", False)
    if paused and not st.session_state.awaiting_approval:
        st.session_state.awaiting_approval = True
        st.session_state.last_action = data.get("action") or ""
        st.rerun()
    elif not paused and st.session_state.awaiting_approval:
        st.session_state.awaiting_approval = False
        st.rerun()
```

- [ ] **Step 5: Verify the file still parses**

Run: `uv run python -c "import ast; ast.parse(open('app/ui/app.py', encoding='utf-8').read())"`
Expected: no output (success).

- [ ] **Step 6: Manual verification — voice-triggered pause shows the buttons**

1. Start the backend: `uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload`
2. Start the frontend: `uv run streamlit run app/ui/app.py --server.port 8080`
3. In the browser, enable voice, click Connect, and ask the agent to do something that requires approval (e.g. "send an email to test@example.com saying hi").
4. Confirm: within ~1s of the agent asking for confirmation, the main chat shows the Approve/Reject buttons and the chat input becomes disabled — without ever using the text box.
5. Say "yes". Confirm: the buttons disappear and the chat input re-enables within ~1s, without clicking anything.
6. Repeat steps 3-4, then this time click the on-screen **Approve** button instead of speaking. Confirm it still works exactly as before (unchanged code path).

- [ ] **Step 7: Manual verification — shared memory across modalities**

1. With voice connected, ask a question by voice (e.g. "what's Apple's stock price?") and let it answer.
2. Type a follow-up in the text box that only makes sense with that context (e.g. "and Microsoft's?").
3. Confirm the typed reply shows awareness of the prior voice turn (proves both turns landed in the same LangGraph thread).

- [ ] **Step 8: Commit**

```bash
git add app/ui/app.py
git commit -m "feat(voice): share one conversation thread between text and voice, sync HITL pauses"
```

---

### Task 3: Correct the thread_id documentation

**Files:**
- Modify: `CLAUDE.md` (the "Voice mode" section, the line ending `... Voice and text sessions use different thread_ids (voice-<gpt_live_session_id> vs web_session_<uuid>).`)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing (docs-only).

- [ ] **Step 1: Update the line**

In `CLAUDE.md`, find:

```
  `🎤 Enable voice` sidebar toggle in `app/ui/app.py`. Voice and text sessions
  use different `thread_id`s (`voice-<gpt_live_session_id>` vs `web_session_<uuid>`).
```

Replace with:

```
  `🎤 Enable voice` sidebar toggle in `app/ui/app.py`. Voice and text share the
  same `thread_id` (Streamlit generates one `web_session_<uuid>` per browser
  tab and passes it to both `/stream` and `/gptlive/session`), so they're one
  continuous LangGraph conversation. `GET /voice/{thread_id}/transcript`
  mirrors voice turns (and HITL pause state) into the Streamlit chat, since
  the voice delegation worker runs as a background task with no direct line
  back into the Streamlit process.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: correct voice/text thread_id sharing in CLAUDE.md"
```
