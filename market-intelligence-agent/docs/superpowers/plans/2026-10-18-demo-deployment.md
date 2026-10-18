# Interview Demo Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the whole product (React console + FastAPI + multi-agent graph + MCP + Chromium) behind Caddy (HTTPS + Basic Auth) with Docker Compose, tested locally, ready to run on a Lightsail VM at `market-desk-<ip>.sslip.io`.

**Architecture:** Two containers. `api` = the existing `Dockerfile`, unchanged app code, one uvicorn process, data in a `./data` volume plus `customers.db` bind-mounted to `/app/customers.db`. `caddy` = an image holding the built frontend (`dist/`) that serves it same-origin and reverse-proxies the API path prefixes to `api:8000`.

**Tech Stack:** Docker Compose v2, Caddy 2, Node 20 (build stage only), Python 3.12 (existing image), Bash, Python `httpx` for the smoke check.

**Spec:** `docs/superpowers/specs/2026-10-18-demo-deployment-design.md`

## Global Constraints

- No application code change (`app/`, `frontend/src/` untouched). Only `deploy/demo/`, `.dockerignore`, docs.
- `prod/` and `.github/workflows/` untouched.
- Secrets never in git or an image: `deploy/demo/.env` is git-ignored; only `.env.example` is committed.
- One uvicorn process (no `--workers`).
- Email stays simulated: `EMAIL_SENDER=` empty.
- `PINECONE_INDEX_NAME=market-intel`, `COPILOT_ENABLED=true`, `OPENAI_MODEL=gpt-4o-mini`, `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`.
- Domain: `market-desk-<ip-with-dashes>.sslip.io` on the server, `localhost` locally.
- Only ports 80 and 443 are published; `8000` is not.
- All commands run from `market-intelligence-agent/` unless stated.

## Review Focus

1. **`/data` page vs `/data/*` API:** reloading `https://<domain>/data` must return the SPA, while `/data/clients` must reach the API. Same for `/clients/7`, `/reports/3` (SPA) — no API prefix may swallow a page route. Covered by smoke check `spa_routes` + `api_routes` (Task 1).
2. **SSE buffering:** a `/stream` answer must arrive as several chunks over time, not one block at the end. Covered by smoke check `stream_is_incremental` (Task 1).
3. **`$` in the bcrypt hash:** Compose interpolates `$` in `.env`; an unescaped hash silently becomes a wrong password. The hash is stored base64-encoded (no `$`). Covered by `auth_required` + `auth_accepted` (Task 1).
4. **Data survives rebuilds:** conversation history, generated reports and `customers.db` imports must survive `docker compose down && up --build`. Covered by Task 3 Step 4.
5. **Voice origin:** `VOICE_ALLOWED_ORIGINS` must equal `https://<DOMAIN>` exactly, or `/gptlive/session` returns 403. Covered by smoke check `voice_origin_allowed` (Task 1).

---

## File Structure

| File | Responsibility |
|---|---|
| `deploy/demo/smoke.py` | Black-box check of a running deployment (local or public). The "test" for every task. |
| `deploy/demo/Caddyfile` | HTTPS, Basic Auth, API routing, SPA fallback. |
| `deploy/demo/Dockerfile.web` | Builds the frontend, ships it inside a Caddy image. |
| `deploy/demo/docker-compose.yml` | `api` + `caddy` services, volumes, healthcheck. |
| `deploy/demo/.env.example` | Every variable, no secret values. |
| `deploy/demo/setup.sh` | Fresh Ubuntu server → running stack. |
| `deploy/demo/README.md` | Local test, demo-day, snapshot/delete procedures. |
| `.dockerignore` (modify) | Keep `frontend/node_modules`, `frontend/dist`, `data/` out of the build context. |
| `.gitignore` (modify) | Ignore `deploy/demo/.env` and `deploy/demo/data/`. |

---

### Task 1: Smoke check script

**Files:**
- Create: `deploy/demo/smoke.py`

**Interfaces:**
- Produces: CLI `uv run python deploy/demo/smoke.py --base-url URL --user USER --password PASSWORD [--insecure]`. Prints one line per check `PASS <name>` / `FAIL <name>: <reason>`, exits 0 only if all pass. Used by Tasks 2, 3, 4.

- [ ] **Step 1: Write the script with these checks** (`httpx`, `verify=not insecure`, timeout 120 s; a fresh `thread_id` `smoke_<unix time>` per run):

| Check name | Request | Pass when |
|---|---|---|
| `auth_required` | `GET /health` without auth | status 401 |
| `auth_accepted` | `GET /health` with auth | status 200 and JSON `status == "ok"` |
| `spa_routes` | `GET` `/research`, `/briefing`, `/clients`, `/reports`, `/data`, `/clients/1`, `/reports/1` with auth | each 200, `content-type` starts with `text/html`, body contains `<div id="root">` |
| `api_routes` | `GET /data/clients`, `GET /conversations` with auth | each 200 and `content-type` starts with `application/json` |
| `stream_is_incremental` | `POST /stream` `{"query": "What is the current price of MSFT?", "thread_id": <fresh>}` streamed | ends with an `event: done` line, and at least 3 chunks were received at distinct times ≥ 50 ms apart before `done` |
| `voice_origin_allowed` | `POST /gptlive/session` with header `Origin: <base-url>` and body `{"sdp": "v=0 invalid", "thread_id": "desk_smoke_<time>", "surface": "research"}` | status is **not** 403 (400 from OpenAI rejecting the fake SDP is the expected pass) |

- [ ] **Step 2: Run it against nothing to verify it fails**

Run: `uv run python deploy/demo/smoke.py --base-url https://localhost --user demo --password x --insecure`
Expected: every check `FAIL` (connection refused), exit code 1.

- [ ] **Step 3: Commit**

```bash
git add deploy/demo/smoke.py
git commit -m "feat(demo): smoke check for the demo deployment"
```

---

### Task 2: Caddy image and Compose stack, running locally

**Files:**
- Create: `deploy/demo/Caddyfile`, `deploy/demo/Dockerfile.web`, `deploy/demo/docker-compose.yml`, `deploy/demo/.env.example`
- Modify: `.dockerignore`, `.gitignore`

**Interfaces:**
- Consumes: `smoke.py` (Task 1).
- Produces: `docker compose -f deploy/demo/docker-compose.yml --env-file deploy/demo/.env up -d --build` brings the stack up; data lives in `deploy/demo/data/`. Used by Tasks 3, 4.

- [ ] **Step 1: `.dockerignore`** — add `frontend/node_modules/`, `frontend/dist/`, `data/`, `deploy/demo/data/`, `deploy/demo/.env`. **`.gitignore`** — add `deploy/demo/.env` and `deploy/demo/data/`.

- [ ] **Step 2: `Caddyfile`**

```
{$DOMAIN} {
	basic_auth {
		{$DEMO_USER} {$DEMO_PASSWORD_HASH}
	}
	@api path /stream* /approve* /copilot* /data/* /conversations* /workspace* /gptlive* /voice/* /health
	handle @api {
		reverse_proxy api:8000 {
			flush_interval -1
		}
	}
	handle {
		root * /srv
		try_files {path} /index.html
		file_server
	}
}
```

`DEMO_PASSWORD_HASH` is the base64 of the bcrypt hash (Review Focus 3). With `DOMAIN=localhost`, Caddy issues its internal certificate.

- [ ] **Step 3: `Dockerfile.web`** — build context is `market-intelligence-agent/`. Stage `node:20-slim AS build`: `WORKDIR /web`, copy `frontend/package.json` + `frontend/package-lock.json`, `npm ci`, copy `frontend/`, `npm run build`. Stage `caddy:2`: copy `/web/dist` → `/srv`, copy `deploy/demo/Caddyfile` → `/etc/caddy/Caddyfile`.

- [ ] **Step 4: `docker-compose.yml`**

| Service | Settings |
|---|---|
| `api` | `build: {context: .., dockerfile: Dockerfile}`; `env_file: .env`; volumes `./data:/app/data` and `./data/customers.db:/app/customers.db`; healthcheck = the one in the existing root `docker-compose.yml`; `restart: unless-stopped`; **no `ports`** |
| `caddy` | `build: {context: .., dockerfile: deploy/demo/Dockerfile.web}`; `env_file: .env`; ports `80:80`, `443:443`; volumes `caddy_data:/data`, `caddy_config:/config`; `depends_on: {api: {condition: service_healthy}}`; `restart: unless-stopped` |

Named volumes `caddy_data`, `caddy_config` (they keep the certificate across restarts).

- [ ] **Step 5: `.env.example`** — exactly the variables of the spec's Configuration table, values for the non-secret ones, empty for keys, each with a one-line comment. Include the hash recipe as a comment:
`docker run --rm caddy:2 caddy hash-password --plaintext 'YOUR_PASSWORD' | base64 -w0`

- [ ] **Step 6: Prepare a local run** — create `deploy/demo/.env` from the example (`DOMAIN=localhost`, `VOICE_ALLOWED_ORIGINS=https://localhost`, keys copied from the dev `.env`); `mkdir deploy/demo/data && cp customers.db deploy/demo/data/`.

- [ ] **Step 7: Build and start**

Run: `docker compose -f deploy/demo/docker-compose.yml --env-file deploy/demo/.env up -d --build`
Expected: both services `healthy`/`running` in `docker compose ps` (first build takes several minutes).

- [ ] **Step 8: Run the smoke check**

Run: `uv run python deploy/demo/smoke.py --base-url https://localhost --user <DEMO_USER> --password <password> --insecure`
Expected: 6 × `PASS`, exit 0. On `FAIL`, fix the Caddyfile/compose, rebuild, rerun.

- [ ] **Step 9: Commit**

```bash
git add .dockerignore .gitignore deploy/demo/Caddyfile deploy/demo/Dockerfile.web deploy/demo/docker-compose.yml deploy/demo/.env.example
git commit -m "feat(demo): Caddy front door + compose stack for the full product"
```

---

### Task 3: Full local QA in the browser

**Files:** none created (fixes, if any, go into Task 2's files).

**Interfaces:**
- Consumes: the running stack (Task 2).

- [ ] **Step 1: Browser pass on `https://localhost`** (accept the local certificate, log in): the 5 pages render; Research answers *Which clients have more than 30% in a single stock?*, *Compare NVDA vs AMD*, *What were Amazon's main revenue segments in 2024 according to the annual report?* (cited), *Open https://example.com and take a screenshot* (image shown) — each with its card.
- [ ] **Step 2: Approval** — *Generate a portfolio report for Robert Hayes* → Approve → reply has no `[blocked]`, Download returns an `.xlsx`.
- [ ] **Step 3: Voice** — click 🎤: the browser asks for the microphone and the session reaches Listening.
- [ ] **Step 4: Persistence** — note the conversation, then `docker compose -f deploy/demo/docker-compose.yml down` and `up -d --build`: the conversation is in the history panel and the report is still listed in Reports.
- [ ] **Step 5: Memory footprint** — `docker stats --no-stream` after Steps 1–3; record the `api` memory. If above 3 GB, Task 4's `setup.sh` must create a 2 GB swap file (it does by default; note the figure in the README).
- [ ] **Step 6: Commit any fixes** with a message naming the defect.

---

### Task 4: Server setup script and runbook

**Files:**
- Create: `deploy/demo/setup.sh`, `deploy/demo/README.md`

**Interfaces:**
- Consumes: compose stack (Task 2), `smoke.py` (Task 1).
- Produces: `sudo bash setup.sh` on a fresh Ubuntu 22.04/24.04 server.

- [ ] **Step 1: `setup.sh`** (`set -euo pipefail`, idempotent — safe to rerun):
  1. If no swap: create a 2 GB `/swapfile` and enable it permanently.
  2. Install Docker Engine + compose plugin from Docker's official apt repository if `docker` is missing.
  3. Clone `https://github.com/YanivBohbot/Autonomous-Market-Intelligence-Agent.git` to `/opt/market-desk` if absent, else `git pull`; branch from `$BRANCH` (default `master`).
  4. In `market-intelligence-agent/deploy/demo/`: `mkdir -p data`; copy `../../customers.db` to `data/` only if absent.
  5. If `.env` is missing: copy `.env.example` to `.env`, `chmod 600`, print "fill .env then rerun" and exit 0.
  6. `docker compose up -d --build`, then print the URL `https://$DOMAIN`.

- [ ] **Step 2: Verify the script syntax**

Run: `bash -n deploy/demo/setup.sh`
Expected: no output, exit 0.

- [ ] **Step 3: `README.md`** (English, short sections): *Local test* (Task 2 Steps 6–8 commands); *Demo day* — Lightsail: Ubuntu 24.04, 4 GB plan, attach a static IP, firewall: open 443 (80 is open by default), SSH in, `curl -fsSL <raw setup.sh URL> | sudo bash`, fill `.env` (`DOMAIN=market-desk-<ip-with-dashes>.sslip.io`, `VOICE_ALLOWED_ORIGINS=https://<DOMAIN>`), rerun, run `smoke.py` against the public URL; *After the interview* — create snapshot, delete instance, release the static IP; *Next time* — create from snapshot, update `DOMAIN` and `VOICE_ALLOWED_ORIGINS` for the new IP, `docker compose up -d`; *Troubleshooting* — certificate not issued (port 80/443 closed, or sslip.io rate limit → use `market-desk.duckdns.org`), 401 with the right password (hash not base64), 403 on voice (origin mismatch), OOM (check swap). Also: set an OpenAI monthly usage limit (e.g. $10).

- [ ] **Step 4: Link from the main README** — one line under "Run in Docker" in `README.md` (project) pointing to `deploy/demo/README.md`; mirror it in the repo-root `../README.md` with the `market-intelligence-agent/` prefix.

- [ ] **Step 5: Commit**

```bash
git add deploy/demo/setup.sh deploy/demo/README.md README.md ../README.md
git commit -m "docs(demo): server setup script and demo-day runbook"
```

---

Demo day itself (creating the Lightsail instance, filling the server `.env`, running `smoke.py` on the public URL) is an owner-run procedure from the README, outside this plan: it creates billable resources.
