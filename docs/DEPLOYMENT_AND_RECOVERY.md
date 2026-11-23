# VibePrompt Deployment and Recovery

Staging/production packaging for the API (+ optional web UI) as an **evidence-backed single-node beta**. **Cloud split:** Render hosts the FastAPI API; Vercel hosts the SPA. Local compose remains available for offline/staging. Grill, Books-to-Skill (6 active acquired titles), orchestration, and prompt-generation code paths are unchanged.

## Cloud architecture (Render + Vercel)

| Surface | Host | Config |
|---|---|---|
| API (`/api/*`) | **Render** web service | Root `render.yaml` — Python runtime, `rootDir: backend`, managed Postgres |
| SPA | **Vercel** | Root `vercel.json` — builds `frontend/`, publishes `frontend/dist` |

Existing Render service (if already linked): [vibeprompt.onrender.com](https://vibeprompt.onrender.com) → dashboard `srv-db3kimrncjis73apqnhg`.

### Render (API)

1. Commit and push `render.yaml`, then open the Blueprint deeplink:  
   `https://dashboard.render.com/blueprint/new?repo=https://github.com/LukViper/vibePrompt_`
2. Review services (`vibeprompt-api` + `vibeprompt-db`). Fill Dashboard-only secrets marked `sync: false` (`CORS_ORIGINS`, provider keys, Supabase, etc.). `JWT_SECRET` / `CREDENTIALS_ENCRYPTION_KEY` / `API_SECRET` use `generateValue`.
3. Set `CORS_ORIGINS` to your Vercel HTTPS origin(s), e.g. `https://your-app.vercel.app` (comma-separated; no `*` in production).
4. Health check: `GET /api/health` (public). After deploy, confirm `https://<service>.onrender.com/api/health`.
5. Free plan: `/tmp` for uploads/skills (ephemeral). Attach a paid disk later if Knowledge Library persistence is required on Render.

Optional: `render blueprints validate render.yaml` after installing the [Render CLI](https://render.com/docs/cli).

### Vercel (frontend SPA)

1. Import `LukViper/vibePrompt_` in Vercel (**Root Directory** = repository root `/`, not `frontend`). Root `vercel.json` runs `cd frontend && npm ci` / `npm run build` and publishes `frontend/dist`. If Root Directory is set to `frontend`, drop the custom install/build commands or `npm ci` will look for a missing nested lockfile and fail with EUSAGE.
2. Set Environment Variables (Production / Preview as needed):

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Absolute API base including `/api`, e.g. `https://vibeprompt.onrender.com/api` |
| `VITE_SUPABASE_URL` | Supabase project URL (if using Supabase auth) |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon / publishable key |

Do **not** set a static API secret in the SPA. The browser mints a short-lived guest JWT via `POST /api/auth/guest` (or uses a logged-in user Bearer token). Keep `API_SECRET` server-side for ops/curl only.

3. On Render, set `CORS_ORIGINS` to the exact Vercel HTTPS origin(s). For the Capacitor Android APK (see README), also allow `https://localhost`.
4. Redeploy Vercel after env changes (Vite inlines `VITE_*` at build time).

Local frontend env template: `frontend/.env.example`.

## Architecture (local compose)

| Service | Role |
|---|---|
| `api` | FastAPI / Uvicorn (non-root uid 10001), SQLite + skills + uploads on volume |
| `web` | nginx SPA; proxies `/api/` to `api:8000` |
| `backup` | Optional profile — one-shot SQLite online backup into `/data/backups` |

Persistent volume: compose service mount `vibeprompt_data` → `/data` (project-scoped volume name by default)  
- Database: `/data/vibeprompt.db`  
- Uploads: `/data/knowledge/uploads`  
- Skills: `/data/skills`  
- Backups: `/data/backups`

Secrets are **runtime-only** via `.env.production` (never baked into images). Override the env file path with `COMPOSE_ENV_FILE` when needed.

## Prerequisites

- Podman 5+ with `podman compose` / `podman-compose`, or Docker Compose v2
- Host ports free for `API_PUBLISH_PORT` (default 8000) and `WEB_PUBLISH_PORT` (default 8080)
- Reverse proxy (Caddy/Traefik/nginx) terminating **HTTPS** in front of `web` (and optionally `api`)

## Quick start (staging)

```bash
# 1) Create secrets file (do not commit)
cp deploy/env.production.example .env.production
python - <<'PY'
import secrets, pathlib
p = pathlib.Path(".env.production")
text = p.read_text()
for key in ("JWT_SECRET", "CREDENTIALS_ENCRYPTION_KEY", "API_SECRET"):
    text = text.replace(f"{key}=replace-with-long-random-" + key.split("_")[0].lower() + ("-secret" if key=="API_SECRET" else "-jwt-secret" if "JWT" in key else "-credentials-key"),
                        f"{key}={secrets.token_urlsafe(48)}")
# simpler: overwrite the three lines
import re
for key in ("JWT_SECRET", "CREDENTIALS_ENCRYPTION_KEY", "API_SECRET"):
    text = re.sub(rf"^{key}=.*$", f"{key}={secrets.token_urlsafe(48)}", text, flags=re.M)
p.write_text(text)
print("Wrote random secrets into .env.production")
PY

# 2) Set CORS_ORIGINS to your staging HTTPS origin in .env.production

# 3) Build & start
podman compose --env-file .env.production up -d --build
# docker compose --env-file .env.production up -d --build

# 4) Health (requires API secret header in production)
source .env.production  # or export API_SECRET=...
curl -fsS -H "X-API-Secret: $API_SECRET" http://127.0.0.1:8000/api/health
```

## Production configuration checklist

| Variable | Requirement |
|---|---|
| `APP_ENV` | Must be `production` |
| `JWT_SECRET` | Strong, unique; not `dev-only-*` |
| `CREDENTIALS_ENCRYPTION_KEY` | Strong, unique; not `dev-only-*` |
| `API_SECRET` | Non-empty server-side; SPA uses guest/user JWT (ops may still send `X-API-Secret`) |
| `DATABASE_PATH` | `/data/vibeprompt.db` on the persistent volume |
| `CORS_ORIGINS` | Exact HTTPS frontend origin(s) |
| HTTPS | Terminate TLS at reverse proxy; forward `X-Forwarded-Proto` |
| Logging | API access logs must not print JWT/API keys (providers log latency only) |

Startup **refuses** insecure production defaults (`Settings.assert_secure_for_runtime()`).

## HTTPS reverse proxy (example Caddy)

```caddy
app.example.com {
  encode gzip
  reverse_proxy 127.0.0.1:8080
}
```

Ensure the proxy preserves `Authorization` (and optional ops `X-API-Secret`) headers to the upstream.

## SQLite backup (consistent)

**Do not** `cp` a live database while the API is writing. Use the SQLite Online Backup API:

```bash
# One-shot via compose profile (API should be healthy)
podman compose --env-file .env.production --profile backup run --rm backup

# Or exec into a stopped-writer maintenance window:
podman compose --env-file .env.production stop api
podman compose --env-file .env.production run --rm --entrypoint \
  python api /app/scripts/sqlite_backup.py \
  --database /data/vibeprompt.db --backup-dir /data/backups --retain 14
podman compose --env-file .env.production start api
```

Local / host:

```bash
python backend/scripts/sqlite_backup.py \
  --database /path/to/vibeprompt.db \
  --backup-dir /path/to/backups \
  --retain 14
```

Each backup writes `vibeprompt-<UTC>.db` plus a `.db.json` metadata sidecar and runs `PRAGMA integrity_check` on the backup.

### Retention

- Keep **at least 14 daily** backups for staging; **30+** for production if disk allows.
- Store a copy **off-host** (object storage / another disk). Volume-local backups alone are not disaster recovery.
- Test restore quarterly.

## Database restoration

1. Stop writers: `podman compose --env-file .env.production stop api web`
2. Restore:

```bash
podman compose --env-file .env.production run --rm --entrypoint \
  python api /app/scripts/sqlite_restore.py \
  --backup /data/backups/vibeprompt-YYYYMMDDThhmmssZ.db \
  --database /data/vibeprompt.db
```

3. Start: `podman compose --env-file .env.production start api web`
4. Verify health + login + a known project still loads.

`sqlite_restore.py` integrity-checks the backup, keeps a `.pre-restore-*` copy of the previous live DB, replaces the main file, clears stale `-wal`/`-shm`, and re-checks integrity.

## Application restart

```bash
podman compose --env-file .env.production restart api
# or full recycle:
podman compose --env-file .env.production up -d
```

Data survives restarts via `vibeprompt_data`. Confirm with:

```bash
curl -fsS -H "X-API-Secret: $API_SECRET" http://127.0.0.1:8000/api/health
```

## Data integrity checks

```bash
# Against a backup file
sqlite3 /data/backups/vibeprompt-….db 'PRAGMA integrity_check;'

# Against live DB (prefer during maintenance / low traffic)
sqlite3 /data/vibeprompt.db 'PRAGMA integrity_check; PRAGMA quick_check;'
```

Application-level: register, create a project, send a Grill message, export an agent prompt, restart containers, confirm the same project/messages remain.

## Secure logging notes

- Do not enable debug request body logging in production.
- nginx access log format omits `Authorization` / cookie values.
- Provider log extras include latency/provider name only — not API keys.
- Rotate container logs via the runtime (`podman`/`docker` log drivers) or host journald.

## Rollback

1. `podman compose --env-file .env.production stop api`
2. Restore previous backup (or `.pre-restore-*` file)
3. `podman compose --env-file .env.production start api`
4. Re-run health + auth smoke tests

## Verification

See `docs/DEPLOYMENT_VERIFICATION_RESULTS.md` and:

```bash
python backend/scripts/deployment_verification.py
```

## PostgreSQL (production) — backup & RTO/RPO

**SQLite backup scripts above are local-dev / legacy single-node only.**

For production on Neon (or RDS):

| Item | Target |
|---|---|
| RPO | **24-hour** until Postgres HA is proven (Neon PITR typically better; treat 24h as the contractual floor) |
| RTO | Single API node recovery: restore DB + redeploy API within a maintenance window |
| Backups | Enable Neon **point-in-time recovery** (PITR); keep provider automated daily backups on |
| Drill | **Quarterly restore test** (even if manual): restore a branch/copy, run `GET /api/v1/health/ready`, login smoke |

```bash
# Apply schema once per new database
psql "$DATABASE_URL" -f backend/app/persistence/postgres_schema.sql

# Readiness (DB + provider hints)
curl -fsS "$API/api/v1/health/ready"
```

Document the last successful restore drill date in your runbook when you perform it.
