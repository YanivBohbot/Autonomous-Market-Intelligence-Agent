# Voice Mode

OpenAI GPT-Live (client delegation) over the existing LangGraph workflow.

## Required env (added to `.env`)

```
OPENAI_API_KEY=...            # already required for text mode; reused for voice
OPENAI_LIVE_MODEL=gpt-live-1  # optional, this is the default
OPENAI_LIVE_VOICE=marin       # optional, any built-in GPT-Live voice
```

No extra sign-up — voice uses the same OpenAI account/key as text mode. There is no
separate STT/TTS provider anymore (GPT-Live does both).

## Run order (two terminals)

```bash
# 1. FastAPI (mints GPT-Live sessions at /gptlive/session, runs the delegation
#    worker as a background task per session, plus the existing text routers)
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload

# 2. Streamlit UI (hosts both text chat AND the embedded voice panel)
uv run streamlit run app/ui/app.py --server.port 8080 --server.address 0.0.0.0
# then open http://localhost:8080 and flip "🎤 Enable voice" in the sidebar
```

There is no separate voice worker process — the delegation loop runs inside the
FastAPI process as an `asyncio.create_task` spawned per session
(`app/api/routers/gptlive_session.py`).

## How it routes

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
                          app.voice.graph.build_voice_agent_app(...).ainvoke(...)
                                             │   (generate → approval → tools → ...)
                                             │
                          connection.session.commentary.append(delegation_id, content)
                                             │
Browser speaker ◄── GPT-Live TTS ◄──────────┘
```

Audio flows directly between the browser and OpenAI over WebRTC — our backend never
touches raw audio, only the sideband control channel (transcripts in, commentary out).

Voice and text sessions share `data/checkpoints.db` AND the same `thread_id`:
Streamlit mints one `web_session_<uuid>` per browser tab and passes it to both
`/stream` (text) and `/gptlive/session` (voice), so a voice turn and a text turn
in the same tab continue one conversation rather than two isolated ones. (A voice
session started without a caller-supplied `thread_id` still falls back to
`voice-<gpt_live_session_id>`.)

## HITL in voice

Read-only tools run silently. Side-effect tools (`send_email`, `write_file`, `save_memory`)
trigger a verbal "Say yes or no" prompt via `commentary.append`. The next user utterance
(buffered from `session.input_transcript.delta`) is parsed for affirmative/negative tokens
— in English or Hebrew — and resumes the graph with `Command(resume="approve"|"reject")`.

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

- **"No audio"** in browser → check Chrome's mic permission for `localhost:8080`.
- **`status: error — Failed to fetch`** in voice panel → CORS not applied; confirm
  `CORSMiddleware` is in `server.py` and FastAPI was restarted after the change.
- **Browser never prompts for mic** → Streamlit's iframe may have stripped `allow="microphone"`;
  upgrade Streamlit: `uv add 'streamlit>=1.30'`.
- **Session created but nothing spoken** → check the FastAPI server logs for
  `[voice.worker]` lines; the sideband delegation task logs every attach/delegation/close.
- **`invalid_type ... session.delegation`** → don't pass `"delegation": None` in the session
  config; omit the key entirely to get the "your application" (client) default, or pass
  `{"type": "client"}` explicitly.
- **Robotic TTS reading `{"binary_score":"yes"}`** → grader JSON leaked through; confirm
  `strip_binary_score_prefix` in `app/voice/session.py` is applied to the final reply text.
