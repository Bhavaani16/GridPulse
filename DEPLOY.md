# Deploying GridPulse to a Vultr instance

Backend (FastAPI) + built frontend served by Caddy, one host, Docker
Compose. HTTPS is automatic when a domain is set; plain HTTP on the
instance IP otherwise. All production `.env` values are typed on the
server — secrets never live in the repo or in chat.

## 0. What you need

- A Vultr instance: smallest Ubuntu 22.04/24.04 plan is enough
  (1 vCPU / 1 GB builds the frontend fine; use 2 GB if npm OOMs).
- Your SSH public key added to the instance at creation
  (`root@<ip>` access).
- Optional: a DNS A record pointing a domain at the instance IP.
- The repo locally (rsync pushes it to the server — see step 2).

## 1. Provision (once, idempotent — safe to re-run)

```bash
ssh root@<IP>
# copy provision.sh up first (or paste it):
#   scp deploy/provision.sh root@<IP>:/root/
bash /root/provision.sh
```

This installs `docker.io` + `docker-compose-v2`, enables the firewall
(ufw: incoming SSH/80/443 only, everything else denied), and creates
`/opt/gridpulse`.

## 2. Push the code

```bash
# from the repo root on your machine
rsync -az --delete \
  --exclude .git --exclude .env --exclude '*/node_modules' \
  --exclude 'backend/.local' --exclude 'frontend/dist' \
  --exclude '**/__pycache__' \
  ./ root@<IP>:/opt/gridpulse/
```

## 3. Server environment

```bash
ssh root@<IP>
cd /opt/gridpulse/deploy
cp .env.example .env
nano .env    # type values on the server; do not paste into chat
```

Minimum to edit:

| Key | Value |
|---|---|
| `SITE_ADDRESS` | `:80` for IP-only, or `demo.example.com` for auto-HTTPS |
| `PUBLIC_URL` | `http://<IP>` or `https://<domain>` — same origin the dashboard is opened on |
| `CORS_ORIGINS` | same as `PUBLIC_URL` |
| `OPERATOR_PHONE` | phone that approves SMS (Photon mock still works empty) |
| `GEMINI_API_KEY`, `SOLANA_KEYPAIR_PATH`, Photon/ElevenLabs vars | fill if going live; leave modes on `mock`/`local` otherwise |

Keep `MODE=cached`, `HARDWARE_MODE=simulated`, `HORIZON_MODE=today`
(SPEC section 4). If `SOLANA_MODE=live`, copy the devnet keypair file to
`/opt/gridpulse/deploy/secrets/solana-keypair.json` (the folder is
gitignored and mounted read-only at `/run/secrets` in the backend
container) and set `SOLANA_KEYPAIR_PATH=/run/secrets/solana-keypair.json`.
For `GEMINI_MODE=live` set `GEMINI_MODEL=gemini-flash-lite-latest` and
`GEMINI_API_KEY`; see `docs/gemini.txt` for why that model.

## 4. Up

```bash
cd /opt/gridpulse/deploy
docker compose up -d --build
docker compose ps
docker compose logs -f        # backend + web, Ctrl-C to detach
```

## 5. Verify

```bash
bash /opt/gridpulse/deploy/healthcheck.sh http://<IP>
# or, with a domain:
bash /opt/gridpulse/deploy/healthcheck.sh https://<domain>
```

Expected: `PASS: <url>/api/health` plus the JSON
(`mode cached`, `hardware_mode simulated`, `solana_mode mock` …).
Open the same URL in a browser — the dashboard should load with real
data (no "Backend unreachable" banner).

## 6. Photon webhook

In the Photon/SMS console, set the inbound webhook URL to:

```
https://<domain>/api/webhooks/photon       # with a domain
http://<IP>/api/webhooks/photon            # IP-only
```

(SPEC section 10; the router is mounted at `/api/webhooks`.)

Verified reachable: a mock-mode POST returns
`{"status":"ignored","reason":"not_pending"}` and logs `sms_reply`.
For REAL Photon replies the server `.env` needs
`PHOTON_MODE=live` plus `PHOTON_API_KEY`, `PHOTON_PROJECT_ID`,
`PHOTON_WEBHOOK_SECRET`, `PHOTON_PLATFORM`, `OPERATOR_PHONE`
(type them on the server), then `docker compose up -d` to re-create the
backend. In mock mode a real Photon envelope gets `422
invalid webhook body` — signature verification only runs in live mode.

## 7. Rollback

The repo on the server is the deploy artifact, so:

```bash
cd /opt/gridpulse/deploy && docker compose down
rsync -az --delete ./ root@<IP>:/opt/gridpulse/   # the previous ref
cd /opt/gridpulse/deploy && docker compose up -d --build
```

For a fast local safety net before each push, keep a tar of the last
known-good tree on the server:

```bash
tar -C /opt -czf /root/gridpulse-good.tgz gridpulse
# rollback:
docker compose -f /opt/gridpulse/deploy/docker-compose.yml down
tar -C /opt -xzf /root/gridpulse-good.tgz
docker compose -f /opt/gridpulse/deploy/docker-compose.yml up -d --build
```

## 8. Localhost fallback (demo if the server is down)

```bash
cd backend && .local/venv/bin/python -m uvicorn main:app --port 8000
cd frontend && VITE_API_URL=http://localhost:8000 npm run dev   # :5173
```

Or the same containers locally: `cd deploy && cp .env.example .env`
(leave `SITE_ADDRESS=:80`, `PUBLIC_URL=http://localhost`) then
`docker compose up -d --build` and open `http://localhost`.

## 9. Daily demo note (SPEC section 4)

With `HORIZON_MODE=today` the horizon re-anchors to local midnight at
startup and on POST /api/demo/reset. After local midnight the displayed
day is stale until the lead presses **Reset** in the dashboard (or hits
`/api/demo/reset`), which reloads and re-anchors the data — the server
does not need a restart or cron job.

## Firewall

ufw on the instance: `deny incoming` default, allow `22/tcp`, `80/tcp`,
`443/tcp` only (set by `provision.sh`). Nothing else listens publicly —
Postgres is not used (`DATABASE_URL` empty → SQLite file inside the
backend container), Caddy proxies `/api` so port 8000 stays internal to
the compose network.

## Not tested live

Deployed and verified on Vultr at `https://45-32-137-12.sslip.io`
(Ubuntu 24.04, IP 45.32.137.12): provision.sh ran clean,
`docker compose up -d --build` built both images, Caddy issued a Let's
Encrypt cert automatically once `SITE_ADDRESS` was set to the sslip.io
domain, `healthcheck.sh https://45-32-137-12.sslip.io` → PASS, HTTP on
both the domain and the bare IP 308-redirects to HTTPS, `/api/signals`
returns 24 items with `horizon_start 2026-10-18T07:00:00Z` (today
rebase). Remaining untested: the Photon webhook hitting the public
address (PHOTON_MODE=mock).
