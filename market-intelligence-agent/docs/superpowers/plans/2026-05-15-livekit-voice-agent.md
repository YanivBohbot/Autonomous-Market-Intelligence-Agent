# LiveKit Voice Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time voice I/O to the existing Market Intelligence Agent so a user can speak a question into a browser and hear the agent answer back, while reusing the existing LangGraph workflow (RAG + grader + tools + HITL) unchanged.

**Architecture:** A new `livekit-agents` Python worker process joins a LiveKit room as a participant. It runs a pipeline `Deepgram STT → langchain.LLMAdapter(graph=agent_app) → ElevenLabs TTS` with Silero VAD and a multilingual turn detector. The LangGraph compiled app is imported directly from `app.agent.graph.build_agent_app` — the voice worker is just another transport (alongside the FastAPI `/chat` routers). A minimal `/livekit/token` FastAPI endpoint mints short-lived JWTs, and the existing Streamlit UI embeds a LiveKit JS client via `st.components.v1.html` behind a sidebar toggle so users can speak from the same browser tab they use for text chat.

**Tech Stack:**
- `livekit-agents[deepgram,elevenlabs,silero,turn-detector,langchain]` (Python voice worker)
- `livekit-api` (server-side token minting)
- LiveKit Cloud (free tier) as the SFU
- Deepgram Nova-3 STT (~150 ms TTFT), ElevenLabs Flash v2.5 TTS (~75 ms TTFA)
- Existing stack: LangGraph workflow in `app/agent/graph.py`, FastAPI on :8000, SQLite checkpointer

**Why this shape (locked decisions, do not re-litigate during execution):**
1. **Pipeline, not speech-to-speech.** S2S (OpenAI Realtime) is lower latency but bypasses our LangGraph workflow entirely — we'd lose RAG, the grader, MCP tools, and HITL. Pipeline preserves them.
2. **`langchain.LLMAdapter` over a custom HTTP bridge.** The LiveKit Python SDK ships first-class LangGraph support (`livekit.plugins.langchain.LLMAdapter(graph=…)`). It expects a `StateGraph` compiled with a checkpointer and routes the voice session's `ChatContext` through it. This is the canonical pattern.
3. **Voice worker runs as a separate process, not inside the FastAPI app.** `livekit-agents` owns its own event loop, CLI, and worker lifecycle (`agents.cli.run_app`). It imports `build_agent_app` and shares the same SQLite checkpointer file → voice and text sessions can resume each other if the same `thread_id` is used.
4. **HITL in voice scope = MVP only.** Side-effect tools (send_email, write_file, save_memory) emit a verbal "Approve sending email to X? Say yes or no." prompt. The agent listens for the next user turn and resumes the graph with `Command(resume="approve" | "reject")`. Read-only tools bypass the interrupt as today.
5. **Frontend = LiveKit's hosted Sandbox first, then embedded in Streamlit.** In Task 3 we smoke-test against LiveKit's free public playground (https://agents-playground.livekit.io) before any frontend work exists. Once the voice pipeline is proven, Task 7 embeds a LiveKit JS client into the existing Streamlit UI via `st.components.v1.html`, behind a `🎤 Enable voice` sidebar toggle. No separate page, no extra port.

---

## File Structure

**New files (under `market-intelligence-agent/`):**
- `app/voice/__init__.py` — package marker
- `app/voice/worker.py` — `livekit-agents` worker entrypoint (`agents.cli.run_app`)
- `app/voice/session.py` — `MarketIntelAssistant(Agent)` subclass + `AgentSession` factory
- `app/voice/hitl.py` — verbal HITL bridge: detect graph interrupt, speak prompt, resume on next turn
- `app/api/routers/livekit_token.py` — `POST /livekit/token` → mints a JWT for a browser participant
- `app/ui/voice_panel.py` — Streamlit helper that emits the LiveKit JS client via `st.components.v1.html`
- `docs/VOICE.md` — operator guide (env, run order, troubleshooting)
- `tests/voice/__init__.py` — package marker (tests deferred per project convention)

**Modified files:**
- `app/core/config.py` — five new settings: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`
- `app/api/server.py` — register `livekit_token` router + CORS for `localhost:8080`
- `app/api/models/models.py` — add `LiveKitTokenRequest`, `LiveKitTokenResponse`
- `app/ui/app.py` — add `🎤 Voice mode` sidebar toggle that renders `voice_panel.render_voice_panel()` above the chat
- `pyproject.toml` — add LiveKit deps
- `market-intelligence-agent/CLAUDE.md` — add a "Voice mode" section to the architecture doc
- `docs/TOOLS.md` — no change (no new agent-callable tools)
- `.env.example` (recreate, gitignored — see commit `f56318c`) is **not** restored; instead document keys in `docs/VOICE.md`

**Why Streamlit (not a standalone HTML page):** the existing UI on port 8080 already handles auth, session/thread state, and the text chat. Embedding the LiveKit JS client via `st.components.v1.html` keeps users in one tab and reuses the existing token-fetch CORS allowlist. The voice panel runs in Streamlit's iframe (which already passes `allow="microphone"`), so the only extra plumbing is a sidebar toggle. Voice and text sessions stay on **different `thread_id`s** for this plan (`voice-<room>` vs `web_session_<uuid>`) — unified transcripts are a follow-up.

**File responsibilities:**
- `worker.py` is a thin entrypoint — it loads env, builds the agent app once, and hands off to `agents.cli.run_app`. The session factory lives in `session.py` so it stays unit-testable later.
- `hitl.py` overrides the `Agent.llm_node` to inspect graph state after each LLM step; if `snapshot.next` is non-empty (interrupt), it intercepts and synthesizes a `"Should I … ? Say yes or no."` reply, then maps the next user turn to `Command(resume=…)`.
- `livekit_token.py` is the only HTTP surface the browser hits for voice; everything else is WebRTC straight to LiveKit Cloud.

---

## Phase 0 — Pre-flight (one-time, not in repo)

These are operator steps, NOT code. List them in `docs/VOICE.md` (Task 11). Do **not** create tasks for them — they happen before Task 1.

1. Sign up at https://cloud.livekit.io (free tier is enough for dev).
2. Create a project → copy `LIVEKIT_URL` (looks like `wss://your-proj.livekit.cloud`), `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
3. Sign up at https://console.deepgram.com → create a key → copy `DEEPGRAM_API_KEY`.
4. Sign up at https://elevenlabs.io → Profile → API Keys → copy `ELEVENLABS_API_KEY`.
5. Pick an ElevenLabs voice (default: `Rachel` / voice_id `21m00Tcm4TlvDq8ikWAM`). Note the voice_id for `session.py`.
6. Put all five keys in `market-intelligence-agent/.env`.

---

## Phase 1 — Foundation: deps, config, smoke worker

### Task 1: Add LiveKit dependencies

**Files:**
- Modify: `market-intelligence-agent/pyproject.toml` (add to `[project.dependencies]`)

- [ ] **Step 1: Add the LiveKit packages**

Append to `[project.dependencies]` in `pyproject.toml` (alphabetical with existing deps):

```toml
"livekit-agents[deepgram,elevenlabs,silero,turn-detector,langchain]>=1.2.0",
"livekit-api>=0.8.0",
```

- [ ] **Step 2: Install**

Run from `market-intelligence-agent/`:
```bash
uv sync
```
Expected: completes without conflict; new packages appear under `.venv/Lib/site-packages/livekit/`.

- [ ] **Step 3: Verify importable**

```bash
uv run python -c "from livekit.agents import AgentSession, Agent; from livekit.plugins import deepgram, elevenlabs, silero, langchain; print('ok')"
```
Expected output: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(voice): add livekit-agents and provider plugin deps"
```

---

### Task 2: Extend `Settings` with voice-stack env vars

**Files:**
- Modify: `market-intelligence-agent/app/core/config.py`

- [ ] **Step 1: Add the five new fields**

Open `app/core/config.py`. Find the `Settings(BaseSettings)` class. Add these fields (place them after the existing required keys, before the optional defaults):

```python
    LIVEKIT_URL: str
    LIVEKIT_API_KEY: str
    LIVEKIT_API_SECRET: str
    DEEPGRAM_API_KEY: str
    ELEVENLABS_API_KEY: str
    ELEVENLABS_VOICE_ID: str = "21m00Tcm4TlvDq8ikWAM"   # Rachel
```

- [ ] **Step 2: Verify config loads with the new keys in `.env`**

Make sure `.env` has the five LiveKit/Deepgram/ElevenLabs keys from Phase 0, then run:
```bash
uv run python -c "from app.core.config import settings; print(settings.LIVEKIT_URL[:10], settings.DEEPGRAM_API_KEY[:6])"
```
Expected: first 10 chars of the LK URL and first 6 chars of the DG key — no `ValidationError`.

- [ ] **Step 3: Commit**

```bash
git add app/core/config.py
git commit -m "feat(voice): add LiveKit + Deepgram + ElevenLabs settings keys"
```

---

### Task 3: Stub the voice worker entrypoint (no graph yet)

This task gets a barebones LiveKit worker process connecting to LiveKit Cloud and saying "hello" with a hard-coded prompt. It proves the audio plumbing works before we wire the LangGraph integration.

**Files:**
- Create: `market-intelligence-agent/app/voice/__init__.py` (empty)
- Create: `market-intelligence-agent/app/voice/worker.py`
- Create: `market-intelligence-agent/app/voice/session.py`

- [ ] **Step 1: Create empty package marker**

Create `app/voice/__init__.py` with no content (single newline).

- [ ] **Step 2: Create the session factory**

Create `app/voice/session.py` with:

```python
"""Voice session factory: builds the AgentSession with STT/LLM/TTS pipeline."""
from livekit.agents import Agent, AgentSession
from livekit.plugins import deepgram, elevenlabs, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from app.core.config import settings


class MarketIntelAssistant(Agent):
    """Voice persona. Instructions stay short — verbal answers, no markdown."""

    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a market intelligence voice assistant. "
                "Keep replies under 30 words. Speak naturally, no bullet points, "
                "no markdown. Spell out numbers when reading them. "
                "If asked to send an email or save data, confirm verbally first."
            ),
        )


def build_voice_session() -> AgentSession:
    """Stub session — Task 4 swaps the LLM for the LangGraph adapter."""
    from livekit.plugins import openai as lk_openai
    return AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3", language="en-US",
                         api_key=settings.DEEPGRAM_API_KEY),
        llm=lk_openai.LLM(model="gpt-4o-mini", api_key=settings.OPENAI_API_KEY),
        tts=elevenlabs.TTS(
            model_id="eleven_flash_v2_5",
            voice_id=settings.ELEVENLABS_VOICE_ID,
            api_key=settings.ELEVENLABS_API_KEY,
        ),
        turn_detection=MultilingualModel(),
    )
```

- [ ] **Step 3: Create the worker entrypoint**

Create `app/voice/worker.py` with:

```python
"""LiveKit Agents worker. Run with:

    uv run python -m app.voice.worker dev

For production-style worker (multi-room):

    uv run python -m app.voice.worker start
"""
import logging

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import JobContext

from app.voice.session import MarketIntelAssistant, build_voice_session

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice.worker")


async def entrypoint(ctx: JobContext) -> None:
    logger.info("voice session starting for room=%s", ctx.room.name)
    session = build_voice_session()
    await session.start(agent=MarketIntelAssistant(), room=ctx.room)
    await ctx.connect()
    await session.generate_reply(
        instructions="Greet the user briefly and ask what they want to know."
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
```

- [ ] **Step 4: Smoke-test the worker against LiveKit Cloud**

```bash
uv run python -m app.voice.worker dev
```
Expected log lines: `registered worker`, `available connections` to your LiveKit Cloud URL. The process stays running and waits for a participant. Leave it running, open a second terminal, and connect via LiveKit's hosted playground:

1. Go to https://agents-playground.livekit.io
2. Enter your `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (the playground mints a token client-side)
3. Click "Connect"
4. Speak: "Hello, can you hear me?"
5. Expected: agent transcribes your speech, gpt-4o-mini answers, voice plays back through the browser.

Kill the worker with Ctrl+C.

- [ ] **Step 5: Commit**

```bash
git add app/voice/
git commit -m "feat(voice): livekit-agents worker stub with STT/LLM/TTS pipeline"
```

---

## Phase 2 — Plug the existing LangGraph workflow into the voice pipeline

### Task 4: Replace stub LLM with `langchain.LLMAdapter(graph=agent_app)`

This is the core integration. We swap the placeholder `openai.LLM` for an adapter that routes every voice turn through the compiled LangGraph workflow, so RAG, the grader, web search, and tool calls all run exactly as in text mode.

**Files:**
- Modify: `market-intelligence-agent/app/voice/session.py`
- Modify: `market-intelligence-agent/app/voice/worker.py`

- [ ] **Step 1: Replace the LLM in the session factory**

Edit `app/voice/session.py`. Replace the `build_voice_session()` function body with:

```python
def build_voice_session(agent_app) -> AgentSession:
    """Wire the compiled LangGraph app in as the LLM. `agent_app` is the result
    of `app.agent.graph.build_agent_app(checkpointer, store)`."""
    from livekit.plugins import langchain as lk_langchain
    return AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3", language="en-US",
                         api_key=settings.DEEPGRAM_API_KEY),
        llm=lk_langchain.LLMAdapter(graph=agent_app),
        tts=elevenlabs.TTS(
            model_id="eleven_flash_v2_5",
            voice_id=settings.ELEVENLABS_VOICE_ID,
            api_key=settings.ELEVENLABS_API_KEY,
        ),
        turn_detection=MultilingualModel(),
        preemptive_generation=True,
    )
```

Also remove the now-unused `from livekit.plugins import openai as lk_openai` import that was inside the old function body.

- [ ] **Step 2: Build the LangGraph app inside the worker entrypoint**

Edit `app/voice/worker.py`. Replace the body of `entrypoint` with:

```python
async def entrypoint(ctx: JobContext) -> None:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    logger.info("voice session starting for room=%s", ctx.room.name)

    async with AsyncSqliteSaver.from_conn_string("data/checkpoints.db") as saver:
        from app.agent.graph import build_agent_app
        from app.agent.memory.store import build_store

        agent_app = build_agent_app(checkpointer=saver, store=build_store())
        session = build_voice_session(agent_app)

        await session.start(agent=MarketIntelAssistant(), room=ctx.room)
        await ctx.connect()
        await session.generate_reply(
            instructions="Greet the user briefly and ask what they want to know."
        )
```

(Verify `app.agent.memory.store.build_store` exists; if the project uses a different builder name, match it. Check `app/agent/memory/store.py` before editing.)

- [ ] **Step 3: Smoke-test the integration**

```bash
uv run python -m app.voice.worker dev
```
Connect via the LiveKit playground (same as Task 3 Step 4). Ask a question that exercises RAG: "What does our internal documentation say about quarterly reporting?" The voice answer should now reflect Pinecone-retrieved content, not generic gpt-4o-mini output.

Try a tool call: "What's the current price of Apple stock?" The graph should call `yfinance_get_ticker_info`, then the answer should be spoken back.

- [ ] **Step 4: Commit**

```bash
git add app/voice/session.py app/voice/worker.py
git commit -m "feat(voice): route voice turns through the LangGraph workflow via LLMAdapter"
```

---

### Task 5: Force voice-style output via a system instruction prefix

The voice persona's `instructions=` argument in `MarketIntelAssistant.__init__` only steers the `Agent` shell — the actual text comes from the LangGraph `generate` node, which uses `SYSTEM_PROMPT` from `app/agent/prompts/system.py` and is tuned for chat, not voice. We need a way to prefix voice-style guardrails without forking the prompt.

**Files:**
- Modify: `market-intelligence-agent/app/voice/session.py`

- [ ] **Step 1: Add a TTS text transform for spoken safety**

In `app/voice/session.py`, import the transforms helper and apply emoji + markdown filters:

```python
from livekit.agents import text_transforms
```

Then in `build_voice_session`, add to the `AgentSession(...)` kwargs:

```python
        tts_text_transforms=["filter_emoji", "filter_markdown"],
```

- [ ] **Step 2: Inject a voice-mode preamble via `ChatContext`**

Still in `build_voice_session`, before returning the session, prepend a system message:

```python
    from livekit.agents import ChatContext
    chat_ctx = ChatContext()
    chat_ctx.add_message(
        role="system",
        content=(
            "VOICE MODE. Keep every reply under 30 words. "
            "Never use markdown, bullet points, or numbered lists. "
            "Spell out numbers and acronyms. End with a brief question "
            "to keep the conversation flowing."
        ),
    )
```

Then pass `chat_ctx=chat_ctx` to the `AgentSession(...)` constructor.

(If the `AgentSession` constructor doesn't accept `chat_ctx` directly, attach it on the `MarketIntelAssistant` instance via `super().__init__(chat_ctx=chat_ctx, instructions=…)`. Check the installed `livekit.agents` version's signature when implementing.)

- [ ] **Step 3: Smoke-test that responses got shorter**

Restart the worker. Ask: "Summarize Apple's last quarterly earnings." Expected: answer ≤ 30 words, no asterisks, no "**" or "*" leaking into TTS.

- [ ] **Step 4: Commit**

```bash
git add app/voice/session.py
git commit -m "feat(voice): apply voice-mode preamble and TTS text filters"
```

---

## Phase 3 — Frontend: token endpoint + minimal browser page

### Task 6: Add `POST /livekit/token` endpoint to FastAPI

**Files:**
- Create: `market-intelligence-agent/app/api/routers/livekit_token.py`
- Modify: `market-intelligence-agent/app/api/models/models.py`
- Modify: `market-intelligence-agent/app/api/server.py`

- [ ] **Step 1: Add request/response models**

Edit `app/api/models/models.py`. Append:

```python
class LiveKitTokenRequest(BaseModel):
    identity: str
    room: str = "market-intel-voice"


class LiveKitTokenResponse(BaseModel):
    token: str
    url: str
    room: str
```

- [ ] **Step 2: Create the router**

Create `app/api/routers/livekit_token.py`:

```python
"""Mints short-lived LiveKit JWTs so the browser can join a voice room."""
import logging

from fastapi import APIRouter
from livekit import api

from app.api.models.models import LiveKitTokenRequest, LiveKitTokenResponse
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/livekit/token", response_model=LiveKitTokenResponse)
async def issue_token(payload: LiveKitTokenRequest) -> LiveKitTokenResponse:
    grants = api.VideoGrants(
        room_join=True,
        room=payload.room,
        can_publish=True,
        can_subscribe=True,
    )
    token = (
        api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(payload.identity)
        .with_name(payload.identity)
        .with_grants(grants)
        .to_jwt()
    )
    return LiveKitTokenResponse(
        token=token,
        url=settings.LIVEKIT_URL,
        room=payload.room,
    )
```

- [ ] **Step 3: Register the router in the FastAPI app**

Edit `app/api/server.py`. Find where existing routers (`health`, `stream`, `approve`) are included. Add:

```python
from app.api.routers import livekit_token as livekit_token_router
...
app.include_router(livekit_token_router.router)
```

- [ ] **Step 4: Smoke-test the endpoint**

Start FastAPI:
```bash
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload
```

In another terminal:
```bash
curl -X POST http://localhost:8000/livekit/token -H "Content-Type: application/json" -d "{\"identity\":\"test-user\"}"
```

Expected: JSON `{"token":"<long jwt>","url":"wss://...","room":"market-intel-voice"}`. Paste the token into https://jwt.io and verify the `video.room` grant is `market-intel-voice`.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/livekit_token.py app/api/models/models.py app/api/server.py
git commit -m "feat(voice): POST /livekit/token mints scoped room-join JWTs"
```

---

### Task 7: Embed the LiveKit client in the Streamlit UI

We keep the existing Streamlit app on port 8080. Voice mode is a **sidebar toggle** that, when enabled, renders an `st.components.v1.html` panel hosting the LiveKit JS client. Mic and audio output happen inside Streamlit's iframe; the panel posts to `POST /livekit/token` for a JWT and connects to LiveKit Cloud directly via WebRTC.

**Files:**
- Create: `market-intelligence-agent/app/ui/voice_panel.py`
- Modify: `market-intelligence-agent/app/ui/app.py`
- Modify: `market-intelligence-agent/app/api/server.py` (CORS)

- [ ] **Step 1: Add CORS to FastAPI so the iframe can call `/livekit/token`**

Edit `app/api/server.py`. Add near the top of the file (after `app = FastAPI(...)`):

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)
```

- [ ] **Step 2: Create the voice panel helper**

Create `app/ui/voice_panel.py`:

```python
"""Streamlit helper that embeds the LiveKit JS client as a components.html panel."""
import os
import streamlit.components.v1 as components

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")

_HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://cdn.jsdelivr.net/npm/livekit-client@2.5.5/dist/livekit-client.umd.min.js"></script>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; }}
    .row {{ display: flex; gap: 0.5rem; align-items: center; }}
    button {{ font-size: 1rem; padding: 0.5rem 1rem; cursor: pointer; }}
    button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    #status {{ margin-left: 0.5rem; color: #555; font-size: 0.9rem; }}
    #log {{
      margin-top: 0.75rem; padding: 0.5rem; background: #f4f4f4;
      border-radius: 6px; min-height: 80px; max-height: 180px;
      overflow-y: auto; white-space: pre-wrap; font-size: 0.85rem;
    }}
  </style>
</head>
<body>
  <div class="row">
    <button id="connect">🎤 Connect</button>
    <button id="disconnect" disabled>Disconnect</button>
    <span id="status">idle</span>
  </div>
  <div id="log"></div>

  <script>
    const TOKEN_URL = "{api_url}/livekit/token";
    const log = (m) => {{
      const el = document.getElementById("log");
      el.textContent += m + "\\n";
      el.scrollTop = el.scrollHeight;
    }};
    const setStatus = (s) => document.getElementById("status").textContent = s;
    let room = null;

    document.getElementById("connect").onclick = async () => {{
      try {{
        setStatus("fetching token...");
        const res = await fetch(TOKEN_URL, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            identity: "user-" + Math.random().toString(36).slice(2, 8),
            room: "market-intel-voice"
          }}),
        }});
        if (!res.ok) throw new Error("token endpoint returned " + res.status);
        const {{ token, url }} = await res.json();
        log("got token, connecting to " + url);

        room = new LivekitClient.Room({{ adaptiveStream: true, dynacast: true }});
        room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {{
          if (track.kind === "audio") {{
            const el = track.attach();
            document.body.appendChild(el);
            log("agent audio attached");
          }}
        }});
        room.on(LivekitClient.RoomEvent.Disconnected, () => {{
          setStatus("disconnected");
          log("room disconnected");
        }});

        await room.connect(url, token);
        await room.localParticipant.setMicrophoneEnabled(true);
        setStatus("connected — speak now");
        log("mic enabled");
        document.getElementById("connect").disabled = true;
        document.getElementById("disconnect").disabled = false;
      }} catch (err) {{
        setStatus("error");
        log("error: " + err.message);
      }}
    }};

    document.getElementById("disconnect").onclick = async () => {{
      if (room) {{ await room.disconnect(); }}
      document.getElementById("connect").disabled = false;
      document.getElementById("disconnect").disabled = true;
      setStatus("idle");
    }};
  </script>
</body>
</html>
"""


def render_voice_panel(height: int = 320) -> None:
    """Embed the LiveKit voice client in the current Streamlit container."""
    html = _HTML_TEMPLATE.format(api_url=API_URL)
    components.html(html, height=height)
```

- [ ] **Step 3: Wire the sidebar toggle into the Streamlit app**

Edit `app/ui/app.py`. Insert just below the existing session-state init block (after the `if "last_action" not in st.session_state:` block, line ~25, before the "Affichage de l'historique" comment):

```python
# --- Voice mode (LiveKit-backed) ---
from app.ui.voice_panel import render_voice_panel

with st.sidebar:
    st.markdown("### 🎤 Voice mode")
    voice_on = st.toggle(
        "Enable voice",
        value=False,
        help="Speak to the agent via your mic. Requires the LiveKit worker running.",
    )
    if voice_on:
        st.caption(
            "Click **Connect** in the panel below, allow mic access, then speak. "
            "Voice runs on a separate `thread_id` from the text chat."
        )
        render_voice_panel(height=280)
```

- [ ] **Step 4: Smoke-test the full loop**

Two terminals (no more standalone HTTP server — Streamlit hosts the page):

1. `uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload`
2. `uv run python -m app.voice.worker dev`
3. `uv run streamlit run app/ui/app.py --server.port 8080 --server.address 0.0.0.0`

Open http://localhost:8080 in Chrome. In the sidebar, flip **Enable voice** → ON. The LiveKit panel renders. Click **🎤 Connect**, allow the mic when Chrome prompts, ask: *"What's the latest news on Tesla?"*

Expected:
- `status` shows `connected — speak now`
- The log shows `mic enabled` and `agent audio attached`
- The voice agent's reply plays through your speakers
- The text chat on the right is unaffected; both can run independently

- [ ] **Step 5: Verify CORS / mic permissions if smoke fails**

Common failures and fixes:
- **`status: error — Failed to fetch`** → browser blocked the cross-origin POST. Confirm Step 1 added the CORS middleware and FastAPI was restarted.
- **Browser never prompts for mic** → Streamlit's iframe may have stripped `allow="microphone"` in older versions. Upgrade Streamlit: `uv add 'streamlit>=1.30'`.
- **`401 Unauthorized` in log** → `LIVEKIT_API_SECRET` in `.env` doesn't match the project on LiveKit Cloud.

- [ ] **Step 6: Commit**

```bash
git add app/ui/voice_panel.py app/ui/app.py app/api/server.py
git commit -m "feat(voice): embed LiveKit client in Streamlit sidebar via components.html"
```

---

## Phase 4 — HITL voice flow

When the LangGraph workflow interrupts (a side-effect tool is queued), the voice agent must **not** silently stall. It must verbalize the pending action and listen for an explicit yes/no, then call `Command(resume=…)` on the graph.

The `langchain.LLMAdapter` advances the graph to the first interrupt and returns whatever the last `AIMessage` contained — but the graph is then paused. We need to detect that pause, generate a spoken approval prompt, and on the next user utterance, resume the graph with a verdict.

### Task 8: Verbal HITL bridge

**Files:**
- Create: `market-intelligence-agent/app/voice/hitl.py`
- Modify: `market-intelligence-agent/app/voice/session.py`

- [ ] **Step 1: Create the HITL helper**

Create `app/voice/hitl.py`:

```python
"""Verbal HITL: bridge LangGraph interrupts to spoken yes/no turns."""
import logging
import re

from langgraph.types import Command

logger = logging.getLogger(__name__)

_AFFIRMATIVE = re.compile(r"\b(yes|yeah|yep|sure|ok(ay)?|approve|go ahead|do it|confirm)\b", re.I)
_NEGATIVE = re.compile(r"\b(no|nope|cancel|stop|don'?t|reject|deny)\b", re.I)


def classify_verdict(utterance: str) -> str | None:
    """Return 'approve', 'reject', or None if ambiguous."""
    if _NEGATIVE.search(utterance):
        return "reject"
    if _AFFIRMATIVE.search(utterance):
        return "approve"
    return None


async def is_interrupted(agent_app, thread_id: str) -> tuple[bool, str | None]:
    """Return (is_paused, action_description) for the given thread."""
    snapshot = await agent_app.aget_state({"configurable": {"thread_id": thread_id}})
    if not snapshot.next:
        return False, None
    last = snapshot.values["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return True, "an action"
    descs = [f"{tc['name']} with args {tc['args']}" for tc in tool_calls]
    return True, "; ".join(descs)


async def resume_with(agent_app, thread_id: str, verdict: str):
    """Resume the paused graph with 'approve' or 'reject'."""
    config = {"configurable": {"thread_id": thread_id}}
    return await agent_app.ainvoke(Command(resume=verdict), config)
```

- [ ] **Step 2: Override `llm_node` in the assistant to insert the HITL bridge**

Edit `app/voice/session.py`. Convert `MarketIntelAssistant` to override `llm_node`:

```python
from typing import AsyncIterable
from livekit.agents import ModelSettings, llm, FunctionTool

class MarketIntelAssistant(Agent):
    def __init__(self, agent_app, thread_id: str) -> None:
        super().__init__(
            instructions=(
                "You are a market intelligence voice assistant. "
                "Keep replies under 30 words. Speak naturally, no bullet points, "
                "no markdown. Spell out numbers. Before any side-effect action "
                "(send email, save data, write file), confirm verbally first."
            ),
        )
        self._agent_app = agent_app
        self._thread_id = thread_id

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[FunctionTool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[llm.ChatChunk]:
        from app.voice.hitl import classify_verdict, is_interrupted, resume_with

        paused, action = await is_interrupted(self._agent_app, self._thread_id)
        if paused:
            last_user = next(
                (m.content for m in reversed(chat_ctx.items) if m.role == "user"),
                "",
            )
            verdict = classify_verdict(str(last_user))
            if verdict is None:
                yield llm.ChatChunk(
                    delta=llm.ChoiceDelta(
                        content=f"I need confirmation before {action}. Say yes or no.",
                        role="assistant",
                    )
                )
                return
            await resume_with(self._agent_app, self._thread_id, verdict)

        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            yield chunk
```

(Note: the exact `ChatChunk` / `ChoiceDelta` constructor signature varies by livekit-agents version. If the version installed is ≥ 1.2, use `llm.ChatChunk(delta=…)`. Verify by running `uv run python -c "from livekit.agents import llm; help(llm.ChatChunk.__init__)"` before implementing this step.)

- [ ] **Step 3: Pass `agent_app` and `thread_id` from the worker**

Edit `app/voice/worker.py` `entrypoint`. Replace:

```python
        await session.start(agent=MarketIntelAssistant(), room=ctx.room)
```

with:

```python
        thread_id = f"voice-{ctx.room.name}"
        await session.start(
            agent=MarketIntelAssistant(agent_app, thread_id),
            room=ctx.room,
        )
```

- [ ] **Step 4: Smoke-test the HITL voice flow**

Restart everything. In the browser, say: "Send an email to test@example.com with the subject hello and body world."

Expected sequence:
1. Agent transcribes the request.
2. Graph reaches `approval_node`, interrupts on `send_email`.
3. Next assistant turn speaks: "I need confirmation before send_email with args …. Say yes or no."
4. You say: "Yes."
5. Agent resumes the graph with `Command(resume="approve")`, the email is sent (or simulated if `EMAIL_SENDER` is the placeholder), and the agent voices the result.

Re-test the reject path: ask the same thing, then say "No." The graph cancels the batch and the agent voices the cancellation.

- [ ] **Step 5: Commit**

```bash
git add app/voice/hitl.py app/voice/session.py app/voice/worker.py
git commit -m "feat(voice): verbal HITL — speak side-effect prompts, parse yes/no, resume graph"
```

---

## Phase 5 — Docs + final smoke

### Task 9: Document operator setup

**Files:**
- Create: `market-intelligence-agent/docs/VOICE.md`

- [ ] **Step 1: Write the operator guide**

Create `docs/VOICE.md`:

```markdown
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

Voice and text sessions share `data/checkpoints.db`. Use the same `thread_id`
(`voice-<room>` for voice, `default_thread` for text) to keep them isolated, or
match them to share state.

## HITL in voice

Read-only tools run silently. Side-effect tools (`send_email`, `write_file`,
`save_memory`) trigger a verbal "Say yes or no" prompt. The next user utterance
is parsed for affirmative/negative tokens and resumes the graph accordingly.

## Latency targets

| Stage          | Budget |
| -------------- | ------ |
| STT TTFT       | <200ms |
| Graph TTFT     | <500ms (RAG adds ~200ms vs text mode) |
| TTS TTFA       | <100ms |
| End-to-end     | <900ms |

## Troubleshooting

- **"No audio"** in browser → check Chrome's mic permission for `localhost:9000`.
- **`401 Unauthorized` on token** → `LIVEKIT_API_SECRET` mismatch.
- **Worker exits with `Address already in use`** → another instance is running.
- **Robotic TTS reading "asterisk asterisk word"** → markdown leaked through;
  confirm `tts_text_transforms=["filter_markdown"]` is set.
- **Agent talks over user** → check `turn_detection=MultilingualModel()` is wired.
```

- [ ] **Step 2: Add a Voice section to `CLAUDE.md`**

Edit `market-intelligence-agent/CLAUDE.md`. After the "API routers" section, insert a new section:

```markdown
### Voice mode (`app/voice/` + Streamlit panel)

A separate `livekit-agents` worker process (`uv run python -m app.voice.worker dev`)
joins LiveKit Cloud rooms and runs the pipeline
`Deepgram STT → langchain.LLMAdapter(graph=agent_app) → ElevenLabs TTS`. The
worker imports the **same** compiled LangGraph workflow as the FastAPI app —
RAG, grader, tools, and HITL behave identically; only the transport differs.

- `app/voice/worker.py` — entrypoint; `agents.cli.run_app`.
- `app/voice/session.py` — `MarketIntelAssistant` + `AgentSession` factory.
- `app/voice/hitl.py` — verbalizes interrupts and maps yes/no to `Command(resume=…)`.
- `app/api/routers/livekit_token.py` — `POST /livekit/token` mints room-join JWTs.
- `app/ui/voice_panel.py` — `render_voice_panel()` injects a LiveKit JS client into
  the existing Streamlit app via `st.components.v1.html`. Activated by the
  `🎤 Enable voice` sidebar toggle in `app/ui/app.py`. Voice and text sessions
  use different `thread_id`s (`voice-<room>` vs `web_session_<uuid>`).

See `docs/VOICE.md` for env vars and run order.
```

- [ ] **Step 3: Commit**

```bash
git add docs/VOICE.md CLAUDE.md
git commit -m "docs(voice): operator guide and CLAUDE.md architecture section"
```

---

### Task 10: End-to-end smoke checklist

**Files:** none — this is a manual validation pass.

- [ ] **Step 1: Cold-start the system**

Kill any running processes. From `market-intelligence-agent/`:
1. `uv run uvicorn app.api.server:app --port 8000 --reload`
2. `uv run python -m app.voice.worker dev`
3. `uv run streamlit run app/ui/app.py --server.port 8080 --server.address 0.0.0.0`
4. Open http://localhost:8080 in Chrome → sidebar → toggle **🎤 Enable voice** → click **🎤 Connect** in the embedded panel.

- [ ] **Step 2: Walk through each capability verbally**

For each item below, say it into the mic and verify the spoken answer matches the expected behavior:

| Capability | Utterance | Expected behavior |
| --- | --- | --- |
| RAG | "What does our internal docs say about Q1 revenue?" | Pinecone-retrieved answer, no web search |
| Web fallback | "What happened in markets yesterday?" | Tavily called, recent answer |
| yfinance tool | "What's the price of Apple stock?" | `yfinance_get_ticker_info` called, price voiced |
| CRM tool | "How many customers do we have?" | `read_query` called, count voiced |
| Read-only memory | "What do you remember about me?" | `list_memories` runs without HITL prompt |
| HITL approve | "Send an email to test@example.com saying hi" | Verbal confirm → "yes" → email sent/simulated |
| HITL reject | Same as above, but answer "no" | Cancellation voiced |
| Barge-in | Interrupt a long answer mid-sentence | Agent stops within ~200ms |

- [ ] **Step 3: Final commit (if any fixes made during smoke)**

If smoke caught nothing, no commit. If it did, fix and commit with `fix(voice): <what>`.

---

## Out of scope (intentionally NOT in this plan)

- Multi-user voice rooms (rooms are 1:1 for now)
- Persistent voice transcript log to disk (handled by LangGraph checkpointer for messages; raw audio is not stored)
- Per-tool fine-grained voice approval ("approve email, reject write_file in same batch") — the existing atomic-batch HITL rule applies
- Phone / SIP integration (LiveKit supports it via Twilio SIP — add later as a separate plan)
- Unified voice + text transcript in one Streamlit chat history (voice runs on its own `thread_id`; merging is a follow-up)
- A native Streamlit component (would need a React build); we use `st.components.v1.html` instead
- Voice biometrics / speaker identification
- Tests — deferred per project convention; add a separate `2026-MM-DD-voice-tests.md` plan when ready

---

## Risks and how this plan mitigates them

| Risk | Mitigation |
| --- | --- |
| `langchain.LLMAdapter` version mismatch with our LangGraph version | Task 1 pins `livekit-agents>=1.2.0`; Task 4 Step 3 smoke-tests the integration before downstream work |
| Latency budget blown by adding RAG to every voice turn | Task 4 enables `preemptive_generation=True`; if still too slow, add a voice-mode toggle to skip the grader (out of scope here, follow-up) |
| TTS reads markdown leaked from `SYSTEM_PROMPT` | Task 5 Step 1 adds `filter_markdown` text transform |
| User keeps talking during agent response | `turn_detection=MultilingualModel()` (Task 3) handles barge-in via built-in VAD interruption |
| HITL ambiguous response ("maybe", "I think so") | `classify_verdict` returns `None`; agent re-prompts (Task 8 Step 2). Never silently approves. |
| Worker crashes mid-conversation | LangGraph checkpointer preserves state; restarting the worker resumes the same `thread_id` (`voice-<room>`) on reconnect |
| LiveKit Cloud free-tier limits | Documented in `docs/VOICE.md`; production needs paid plan or self-hosted SFU (separate plan) |
