# Interview demo deployment — design

**Date:** 2026-10-18
**Branch:** to be created from `master`
**Status:** approved in conversation, pending spec review

## Problem

The production deployment on AWS AgentCore (`prod/`) runs only the agent: AgentCore Runtime exposes `/invocations` and `/ping`, nothing else. The React console, `/stream`, `/approve`, Market Desk (`/copilot/market-desk`), `/data/*`, `/conversations`, `/workspace` and voice (`/gptlive`, `/voice`) exist only on a developer machine. There is no URL where the full product can be shown.

## Goal

A low-cost, password-protected public URL serving the **whole product** — React console, FastAPI backend, multi-agent graph, MCP tools, voice — for job-interview demos.

Success means:

- `https://market-desk-<ip>.sslip.io/research` opens the console after a password prompt, from any computer or phone;
- every feature that works locally works there: the 5 pages, interactive cards, approval cards, conversation history, Excel reports, browser screenshots, voice (microphone allowed because the site is HTTPS);
- the server can be created in about 30 minutes on demo day and removed afterwards, so the cost is near zero between interviews;
- everything is prepared and tested locally first, at no cost.

## Constraints

- Personal demo: one user (the owner), no high availability.
- Tight budget: no always-on paid service required; under $5/month when the server only exists around interviews.
- No application code change. The multi-agent graph, tools and frontend run as they do locally.
- The AgentCore production (`prod/`, `.github/workflows/deploy.yml`) is untouched.
- Secrets never enter git or a Docker image.

## Non-goals (v1)

- Automated deployment (GitHub Actions) to the demo server.
- Real email sending (stays simulated).
- Multiple user accounts or per-user data.
- High availability, autoscaling, managed databases.
- Migrating or replacing the AgentCore production.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Hosting | One small VM: AWS Lightsail, Ubuntu, 4 GB RAM (~$24/month while it exists) | Cheapest way to run the local setup unchanged. Chromium, Node MCP servers and Python need ~2–3 GB. The same image also runs on Oracle Cloud Always Free or Hugging Face Spaces if the owner switches. |
| Lifecycle | Create the server for demos; snapshot + delete afterwards | Lightsail bills a stopped instance at full price; only deleting stops the charge. |
| Domain | `market-desk-<ip>.sslip.io` | Free, no registration. HTTPS needs a domain name, not a bare IP. One `.env` line to change for a real domain later. |
| Front door | Caddy | Automatic Let's Encrypt HTTPS and renewal, Basic Auth, static files and reverse proxy in a few lines. |
| Frontend serving | Built once (`npm run build`) into the Caddy image, same origin as the API | The frontend already calls relative paths (`/stream`, `/copilot`…), as through the Vite proxy locally: no frontend change. |
| Backend image | The existing `Dockerfile` (Python 3.12, Node 20, Chromium, MCP servers pre-pulled) | Already builds the full local runtime. |
| Workers | One uvicorn process | Turn leases (`ThreadTurnCoordinator`) and voice sessions live in process memory. |
| Email | Simulated (`EMAIL_SENDER` empty) | Nothing leaves during a demo, even if an approval is clicked. |

## Architecture

```
Browser ──HTTPS──► caddy (ports 80/443, public)
                    ├─ Basic Auth on every path
                    ├─ /stream /approve /copilot* /data/* /conversations* /workspace*
                    │  /gptlive* /voice* /health  ──►  api:8000 (internal Docker network)
                    └─ everything else: static files from the frontend build,
                       unknown paths fall back to /index.html (client-side routes)

api (existing Dockerfile)
   FastAPI + compiled multi-agent graph + stdio MCP servers + Chromium
   │
   ├── /app/data            ◄── volume ./data   (checkpoints.db, store.db, workspace/)
   └── /app/customers.db    ◄── bind mount ./data/customers.db
```

### Files to add (`deploy/demo/`)

| File | Content |
|---|---|
| `Dockerfile.web` | Stage 1 `node:20` → `npm ci && npm run build` in `frontend/`. Stage 2 `caddy:2` with `dist/` copied to `/srv` and the `Caddyfile`. |
| `Caddyfile` | Site address from `{$DOMAIN}`; `basic_auth` with `{$DEMO_USER}` / `{$DEMO_PASSWORD_HASH}`; a `handle` per API path prefix → `reverse_proxy api:8000` with response buffering off (`flush_interval -1`) so SSE streams token by token; a final `handle` with `root /srv`, `try_files {path} /index.html`, `file_server`. |
| `docker-compose.yml` | Services `api` (build `..`, `env_file: .env`, volumes, healthcheck on `/health`, `restart: unless-stopped`, no published port) and `caddy` (build `Dockerfile.web`, ports 80/443, volumes for Caddy's certificates and config, `depends_on: api` healthy). |
| `.env.example` | Every variable to fill, no secret values. |
| `setup.sh` | For a fresh Ubuntu server: install Docker Engine + compose plugin, clone the repo, create `data/`, copy `customers.db` into `data/` if absent, check `.env` exists, `docker compose up -d --build`. |
| `README.md` | Demo-day procedure, snapshot/delete procedure, troubleshooting. |

### Data

- `checkpoints.db`, `store.db` and `workspace/` already default to `data/` (`CHECKPOINT_DB_PATH`, `STORE_DB_PATH`, `WORKSPACE_ROOT`): the `./data` volume makes conversations, history, memory, reports and screenshots survive container rebuilds.
- `customers.db` is opened as the bare relative path `customers.db` (`app/data_import/db.py`, the MCP sqlite server in `registry.py`), i.e. `/app/customers.db`, and `.dockerignore` excludes `*.db`. It is bind-mounted from `./data/customers.db`, seeded from the repo copy by `setup.sh`, so Data-page imports persist too.
- The knowledge base stays in Pinecone (`market-intel`, 2833 vectors) plus the committed BM25 corpus `app/rag/kb_chunks.jsonl.gz`, already in the image.

### Configuration (`deploy/demo/.env`, on the server only)

| Variable | Value |
|---|---|
| `DOMAIN` | `market-desk-<ip-with-dashes>.sslip.io` (`localhost` for local tests) |
| `DEMO_USER`, `DEMO_PASSWORD_HASH` | Login; hash produced by `caddy hash-password` |
| `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-4o-mini`, `OPENAI_EMBEDDING_MODEL=text-embedding-3-small` | |
| `PINECONE_API_KEY`, `PINECONE_INDEX_NAME=market-intel` | |
| `TAVILY_API_KEY` | |
| `EMAIL_SENDER=` (empty), SMTP fields empty | Email simulation |
| `COPILOT_ENABLED=true` | Research console endpoint |
| `VOICE_ALLOWED_ORIGINS=https://<DOMAIN>` | Voice origin check (`gptlive_session.py`) |
| `API_URL=http://api:8000` | |
| `ANTHROPIC_API_KEY` | Optional (Claude fallback) |

## Security

- Basic Auth on every path, API included: no anonymous call can spend OpenAI credits. Only the bcrypt hash is stored.
- Public ports: 80 (redirect to HTTPS, ACME) and 443. The API port 8000 is not published. SSH restricted by the Lightsail firewall.
- `.env` lives only on the server (`chmod 600`); `.dockerignore` already excludes `.env`.
- Owner sets a monthly usage limit in the OpenAI dashboard (e.g. $10) as the backstop if the password leaks.
- Agent guardrails unchanged: card blocking, PII masking, moderation, approvals, email recipient guard.

## Cost

| Item | Cost |
|---|---|
| Building and testing locally | $0 |
| Lightsail 4 GB, only on demo days | ~$0.03/hour (~$0.80/day) |
| Snapshot between interviews | a few cents/month |
| Domain (sslip.io) | $0 |
| OpenAI during demos | a few dollars, capped by the usage limit |

## Procedure

1. **Local (no cost):** build both images with Docker Desktop, run with `DOMAIN=localhost` (Caddy's internal certificate), pass the test list below.
2. **Demo day (~30 min):** the owner creates the Lightsail instance (Ubuntu, 4 GB) and a static IP and opens ports 80/443 — billing actions stay with the owner; runs `setup.sh`; fills `.env` with `DOMAIN=market-desk-<ip>.sslip.io`; `docker compose up -d`; Caddy obtains the certificate; the test list is run against the public URL.
3. **After interviews:** snapshot, delete the instance (and release the static IP if detached). Next time: create from the snapshot; the new IP changes the sslip address, so update `DOMAIN` and `VOICE_ALLOWED_ORIGINS`.

## Tests

Local (`https://localhost`) and again on the public URL:

1. Both images build.
2. Without the password every path returns 401; with it, `/health` returns 200.
3. The 5 pages load, including a direct reload on `/research`, `/briefing`, `/clients`, `/reports`, `/data`.
4. Research questions answer with their cards: concentration (portfolio), NVDA vs AMD (finance), Amazon 2024 segments (RAG, cited), example.com screenshot (browser).
5. An approval: generate Robert Hayes' report → Approve → Download works.
6. Tokens stream progressively (not all at once at the end), proving Caddy does not buffer SSE.
7. `docker compose down && docker compose up -d` keeps the conversation history and the generated report.
8. Voice: the microphone permission prompt appears and a session connects (HTTPS origin accepted).

## Risks

- **Memory:** the backend was killed for low memory on the dev PC while idle alongside other apps; on a dedicated 4 GB server it runs alone. Measure its footprint during the local test; if it is tight, add a 2 GB swap file in `setup.sh`.
- **Let's Encrypt limits on sslip.io:** sslip.io is a shared domain; if certificate issuance is rate-limited, fall back to DuckDNS (`market-desk.duckdns.org`) — one `DOMAIN` change.
- **Untested image:** the full `Dockerfile` has not been built since the multi-agent, RAG and frontend changes (CI only builds `Dockerfile.agentcore`); the local Docker build is the first check.
- **Image size (~2–3 GB, Chromium):** first build on the server takes several minutes; acceptable for a 30-minute procedure.
