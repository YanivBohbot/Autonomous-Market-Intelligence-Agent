# MIA Dev Console (local-dev frontend)

A React + Vite + Tailwind dev tool for testing the Market Intelligence Agent:
chat streaming, human-in-the-loop approval, live agent activity, health/session
controls, and voice. Local development only — not part of the AWS deployment.

## Run

1. Start the backend (from `market-intelligence-agent/`):
   ```bash
   uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload
   ```
2. Start the frontend (from `market-intelligence-agent/frontend/`):
   ```bash
   npm install   # first time only
   npm run dev
   ```
3. Open http://localhost:5173

Voice also requires the LiveKit worker:
```bash
uv run python -m app.voice.worker dev
```

The Vite dev server proxies `/stream`, `/approve`, `/health`, `/livekit` to
`http://127.0.0.1:8000`. Override with `VITE_API_TARGET` if the backend runs elsewhere.

## Test
```bash
npm test
```
