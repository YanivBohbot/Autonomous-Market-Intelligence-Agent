# MIA Dev Console (local-dev frontend)

A React + Vite + Tailwind dev tool for testing the Market Intelligence Agent:
chat streaming, human-in-the-loop approval, live agent activity, health/session
controls, and voice. Local development only — not part of the AWS deployment.

## Run

`uv` commands run from `market-intelligence-agent/`; `npm` commands from
`market-intelligence-agent/frontend/`.

### 1. Backend (required)
```bash
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend
```bash
npm install   # first time only
npm run dev
```
Then open http://localhost:5173

The Vite dev server proxies `/stream`, `/approve`, `/health`, `/livekit` to
`http://127.0.0.1:8000`. Override with `VITE_API_TARGET` if the backend runs elsewhere.

### 3. Voice mode (optional)
Voice needs the LiveKit worker running **alongside** the backend and frontend, plus
voice keys in `.env` (`LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`,
`DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`). In a third terminal:
```bash
uv run python -m app.voice.worker dev
```
Then open the voice panel in the dev console (http://localhost:5173) and connect.
See [`../docs/VOICE.md`](../docs/VOICE.md) for env setup, audio routing, and troubleshooting.

## Test
```bash
npm test
```
