# VibePrompt API — production image
# Secrets must be supplied at runtime (env / compose). Never bake secrets into layers.

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (uid/gid 10001)
RUN groupadd --gid 10001 vibeprompt \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin vibeprompt

WORKDIR /app

# Install production Python deps (exclude test tooling)
COPY requirements.txt /app/requirements.txt
RUN python - <<'PY'
from pathlib import Path
skip = {"pytest", "pytest-asyncio"}
lines = []
for line in Path("requirements.txt").read_text().splitlines():
    raw = line.strip()
    if not raw or raw.startswith("#"):
        continue
    name = raw.split(">=")[0].split("==")[0].split("[")[0].strip().lower()
    if name in skip:
        continue
    lines.append(raw)
Path("/tmp/requirements.prod.txt").write_text("\n".join(lines) + "\n")
PY
RUN pip install --no-cache-dir -r /tmp/requirements.prod.txt

# Application code only (no .env, no local data, no secrets)
COPY app /app/app
COPY scripts/sqlite_backup.py /app/scripts/sqlite_backup.py
COPY scripts/sqlite_restore.py /app/scripts/sqlite_restore.py

RUN mkdir -p /data/knowledge/uploads /data/skills /data/backups \
    && chown -R vibeprompt:vibeprompt /app /data

USER vibeprompt:vibeprompt

ENV APP_ENV=production \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_PATH=/data/vibeprompt.db \
    KNOWLEDGE_UPLOAD_DIR=/data/knowledge/uploads \
    SKILLS_DIR=/data/skills \
    BACKUP_DIR=/data/backups

EXPOSE 8000

# Healthcheck sends X-API-Secret from runtime env (required in production)
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS -H "X-API-Secret: ${API_SECRET}" http://127.0.0.1:8000/api/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
