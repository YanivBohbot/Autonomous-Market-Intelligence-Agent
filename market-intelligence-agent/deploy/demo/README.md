# Interview demo deployment

The **whole product** — React console, FastAPI backend, multi-agent graph, MCP tools, Chromium, voice — on one small server, behind Caddy (HTTPS + one login).

```
Browser ──HTTPS──► caddy (80/443): login, React build, API routing
                     └──► api:8000 (internal): FastAPI + multi-agent graph + MCP + Chromium
                           data/ volume: conversations, history, memory, reports, customers.db
```

Design: [`docs/superpowers/specs/2026-10-18-demo-deployment-design.md`](../../docs/superpowers/specs/2026-10-18-demo-deployment-design.md). The AWS AgentCore production (`prod/`) is separate and unaffected.

Measured locally: the `api` container uses ~0.6 GB of RAM after a full QA pass; a 4 GB server (plus the 2 GB swap `setup.sh` creates) leaves ample headroom.

## Local test (free)

From `market-intelligence-agent/`, with Docker Desktop running:

```bash
cp deploy/demo/.env.example deploy/demo/.env      # fill the API keys
# password hash (base64, so Compose leaves the "$" alone):
docker run --rm caddy:2 caddy hash-password --plaintext 'YOUR_PASSWORD' | base64 -w0
mkdir -p deploy/demo/data && cp customers.db deploy/demo/data/

docker compose -f deploy/demo/docker-compose.yml --env-file deploy/demo/.env up -d --build
uv run python deploy/demo/smoke.py --base-url https://127.0.0.1 --user demo --password 'YOUR_PASSWORD' --insecure
```

Open https://127.0.0.1 (accept Caddy's local certificate). Expect 6 × `PASS`. Use `127.0.0.1`, not `localhost`: on Windows, WSL can hold `[::1]:443`, and the browser then reaches WSL instead of Docker.

## Demo day (~30 min, billable from step 1)

1. **Lightsail** (AWS console → Lightsail → Create instance): Linux/Unix, **Ubuntu 24.04**, **4 GB** plan, any name (e.g. `market-desk`).
2. **Networking** tab of the instance: *Create static IP* and attach it; in *IPv4 Firewall* add **HTTPS (443)** (SSH 22 and HTTP 80 are open by default).
3. **Connect using SSH** (browser button) and run:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/YanivBohbot/Autonomous-Market-Intelligence-Agent/master/market-intelligence-agent/deploy/demo/setup.sh | sudo bash
   ```
   The first run installs Docker, clones the repo to `/opt/market-desk` and creates `.env`.
4. Edit `/opt/market-desk/market-intelligence-agent/deploy/demo/.env` (`sudo nano …`):
   - `DOMAIN=market-desk-<ip-with-dashes>.sslip.io` (static IP `3.85.12.40` → `market-desk-3-85-12-40.sslip.io`)
   - `VOICE_ALLOWED_ORIGINS=https://<same DOMAIN>`
   - `DEMO_PASSWORD_HASH`, the API keys.
5. Rerun the same `curl … | sudo bash`. It builds and starts (several minutes the first time); Caddy obtains the Let's Encrypt certificate on the first request.
6. From your PC: `uv run python deploy/demo/smoke.py --base-url https://<DOMAIN> --user demo --password '…'` → 6 × `PASS`. Then open `https://<DOMAIN>/research`.

Before the first demo, set a **monthly usage limit** in the OpenAI dashboard (e.g. $10): it caps the damage if the password leaks.

## After the interview (stop paying)

A stopped Lightsail instance is still billed. To stop the charge:

1. Instance → **Snapshots** → *Create snapshot* (a few cents/month).
2. **Delete** the instance.
3. **Networking** → delete the static IP (a detached static IP is billed).

## Next time

Create a new instance **from the snapshot** (same plan), attach a static IP, open 443. The IP changed, so update `DOMAIN` and `VOICE_ALLOWED_ORIGINS` in `.env`, then `cd /opt/market-desk/market-intelligence-agent/deploy/demo && sudo docker compose up -d`. To pick up new code, rerun `setup.sh`.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Browser can't reach the site, no certificate | Port 443 (or 80) closed in the Lightsail firewall, or `DOMAIN` doesn't match the static IP. `sudo docker compose logs caddy`. |
| Certificate errors from Let's Encrypt on sslip.io | Shared-domain rate limit: use a free DuckDNS name (`market-desk.duckdns.org` → static IP) as `DOMAIN`. |
| 401 with the right password | `DEMO_PASSWORD_HASH` is not the **base64** of the bcrypt hash. Regenerate with the command above. |
| Voice: "origin not allowed" (403) | `VOICE_ALLOWED_ORIGINS` must be exactly `https://<DOMAIN>`. |
| `api` restarts or is killed | `sudo docker compose logs api`; check memory with `free -h` (swap should show 2 GB). |
| Browser tool says Chromium is not installed | The image must install the Chromium build `@playwright/mcp` expects (`Dockerfile`: `@playwright/mcp@latest install-browser chromium`); rebuild with `docker compose build --no-cache api`. |
