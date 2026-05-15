# Voice Mode

LiveKit-based voice I/O over the existing LangGraph workflow.

## Required env (added to `.env`)

```
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM   # optional, defaults to Rachel
```

Sign up:
- LiveKit Cloud: https://cloud.livekit.io (free tier OK for dev)
- Deepgram: https://console.deepgram.com
- ElevenLabs: https://elevenlabs.io → Profile → API Keys

## Run order (three terminals)

```bash
# 1. FastAPI (token endpoint + existing /chat routers)
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload

# 2. LiveKit voice worker
uv run python -m app.voice.worker dev

# 3. Streamlit UI (hosts both text chat AND embedded voice panel)
uv run streamlit run app/ui/app.py --server.port 8080 --server.address 0.0.0.0
# then open http://localhost:8080 and flip "🎤 Enable voice" in the sidebar
```

## How it routes

```
Mic (browser, WebRTC) ─► LiveKit Cloud SFU ─► voice worker
                                                  │
                                                  ├─ Deepgram STT (nova-3)
                                                  ├─ langchain.LLMAdapter(graph=agent_app)
                                                  │     └─► rag → grader → generate → tools → ...
                                                  └─ ElevenLabs TTS (flash v2.5)
                                                          │
Browser speaker ◄─── LiveKit Cloud SFU ◄─── audio track ──┘
```

Voice and text sessions share `data/checkpoints.db`. Voice uses `thread_id = voice-<room>`
and text uses `web_session_<uuid>`, keeping them isolated by default.

## HITL in voice

Read-only tools run silently. Side-effect tools (`send_email`, `write_file`, `save_memory`)
trigger a verbal "Say yes or no" prompt. The next user utterance is parsed for
affirmative/negative tokens and resumes the graph with `Command(resume="approve"|"reject")`.

## Latency targets

| Stage      | Budget                                        |
| ---------- | --------------------------------------------- |
| STT TTFT   | <200 ms                                       |
| Graph TTFT | <500 ms (RAG adds ~200 ms vs text mode)       |
| TTS TTFA   | <100 ms                                       |
| End-to-end | <900 ms                                       |

## Troubleshooting

- **"No audio"** in browser → check Chrome's mic permission for `localhost:8080`.
- **`401 Unauthorized` on token** → `LIVEKIT_API_SECRET` mismatch between `.env` and LiveKit Cloud.
- **Worker exits with `Address already in use`** → another instance is running; kill it first.
- **Robotic TTS reading "asterisk asterisk word"** → markdown leaked through; confirm
  `tts_text_transforms=["filter_markdown", "filter_emoji"]` is set in `session.py`.
- **Agent talks over user** → check `turn_detection=MultilingualModel()` is wired in `build_voice_session`.
- **`status: error — Failed to fetch`** in voice panel → CORS not applied; confirm
  `CORSMiddleware` is in `server.py` and FastAPI was restarted after the change.
- **Browser never prompts for mic** → Streamlit's iframe may have stripped `allow="microphone"`;
  upgrade Streamlit: `uv add 'streamlit>=1.30'`.
