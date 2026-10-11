# Voice Mode

OpenAI GPT-Live (client delegation) powers voice in the React **Research**
workspace. Audio flows directly between the browser and OpenAI over WebRTC; FastAPI
keeps the API key server-side and runs the sideband delegation worker.

## Required env (added to `.env`)

```
OPENAI_API_KEY=...            # already required for text mode; reused for voice
OPENAI_LIVE_MODEL=gpt-live-1  # optional, this is the default
OPENAI_LIVE_VOICE=marin       # optional, any built-in GPT-Live voice
```

No extra sign-up — voice uses the same OpenAI account/key as text mode. There is no
separate STT/TTS provider anymore (GPT-Live does both).

## Run order

```bash
# 1. FastAPI (mints GPT-Live sessions at /gptlive/session, runs the delegation
#    worker as a background task per session, plus the existing text routers)
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload

# 2. React console
cd frontend
npm run dev
# open http://localhost:5173/research and press the mic in the composer
```

There is no separate voice worker process — the delegation loop runs inside the
FastAPI process as an `asyncio.create_task` spawned per session
(`app/api/routers/gptlive_session.py`).

## Shared transport

```
Mic (browser, WebRTC) ──────────────► OpenAI GPT-Live session
                                             │
Browser ──POST offer.sdp──► FastAPI ──client.live.create()──► (creates the session,
   ◄──answer.sdp──────────────┘             returns SDP answer + session_id)
                                             │
FastAPI spawns a background task that attaches via
client.live.sideband.connect(session_id) — this is the "delegation worker"
(app/voice/worker.py):
                                             │
                          session.delegation.created
                                             │
                          delegation worker invokes app.state.agent_app
                                             │
                          connection.session.commentary.append(delegation_id, content)
                                             │
Browser speaker ◄── GPT-Live TTS ◄──────────┘
```

The backend never handles raw audio. `POST /gptlive/session` accepts the SDP offer,
an optional `thread_id`, and `surface` (must be `research`, the default; `classic` is rejected with 422). The sideband worker receives transcript text and
returns commentary for GPT-Live to speak.

## Research voice

Research voice is available only at `/research`. It is continuous rather than a
push-to-talk form: the composer displays **Connecting…**, **Listening…**,
**Analyzing…**, **Speaking…**, or **Approval required**, with an animated waveform
that respects reduced-motion settings. While voice is active the text composer is
locked; users must choose either typing or speaking, never both at once.

Research text and voice use the same `app.state.agent_app`, `thread_id`, SQLite
checkpoint, specialists, and activity timeline. Voice graph inputs carry
`metadata.input_source="voice"`; transcript text is not exposed through the
Research polling API. A per-thread lease rejects overlapping text/voice turns with
HTTP 409, and a pre-existing approval must be resolved before voice can start.

The React client polls `GET /voice/{thread_id}/state?after=<sequence>` for incremental
phase/activity data and any pending approval. Side-effect tools render the same
visual approval cards as typed Research, including generated-report selection and
edit/reject options. The card remains visible after voice disconnects. Decisions go
to `POST /voice/{thread_id}/decision`; a stable interrupt ID and first-decision-wins
coordinator make repeated submissions idempotent (`already_applied`) while stale
decisions return HTTP 409.

## Transcript in the chat

Spoken turns appear in the Research chat. While the user speaks, a live caption is
built from the `session.input_transcript.delta` events on the data channel. When a
turn finishes, the client reloads the committed user/assistant messages from
`/copilot/market-desk/history` on `run_finished`/`approval_required`, replacing the
caption. See `docs/superpowers/specs/2026-10-11-research-voice-chat-transcript-design.md`.

## Hebrew support

`app/voice/session.py`'s `VOICE_INSTRUCTIONS` tells the model to respond in whatever
language the user speaks, including Hebrew, and `app/voice/hitl.py`'s `classify_verdict`
recognizes Hebrew כן/לא alongside English yes/no. A scripted check (Hebrew instructions +
delegation + a Hebrew `commentary.append` reply) confirmed the model accepts Hebrew
instructions and produces Hebrew TTS audio with a Hebrew output transcript. Hebrew **speech
recognition** (user speaking Hebrew into a real mic) was not fully confirmed by that script
— a synthetic PCM clip didn't reliably trigger `session.input_transcript.delta`. Verify with
a real browser + mic before relying on Hebrew STT in production.

## Troubleshooting

- **"No audio"** in browser → check Chrome's mic permission for the active local origin (`localhost:5173`).
- **`status: error — Failed to fetch`** in voice panel → CORS not applied; confirm
  `CORSMiddleware` is in `server.py` and FastAPI was restarted after the change.
- **Session created but nothing spoken** → check the FastAPI server logs for
  `[voice.worker]` lines; the sideband delegation task logs every attach/delegation/close.
- **`invalid_type ... session.delegation`** → don't pass `"delegation": None` in the session
  config; omit the key entirely to get the "your application" (client) default, or pass
  `{"type": "client"}` explicitly.
- **Robotic TTS reading `{"binary_score":"yes"}`** → grader JSON leaked through; confirm
  `strip_binary_score_prefix` in `app/voice/session.py` is applied to the final reply text.
