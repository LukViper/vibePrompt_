#!/usr/bin/env python3
"""
Staging deployment verification against compose (podman/docker).

Creates ephemeral secrets, builds/starts the stack, exercises auth, isolation,
Grill, memory, skills, agent prompts, restart persistence, and SQLite backup/restore.

Does not bake secrets into images. Writes docs/DEPLOYMENT_VERIFICATION_RESULTS.md.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
DOCS = REPO / "docs"


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


CHECKS: list[Check] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append(Check(name=name, passed=passed, detail=detail[:800]))
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail[:160]}" if detail else ""))


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(cwd or REPO),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def detect_compose() -> list[str]:
    # Prefer podman compose on this host; fall back to docker compose
    for candidate in (
        ["podman", "compose"],
        ["docker", "compose"],
        ["podman-compose"],
    ):
        try:
            proc = run([*candidate, "version"], timeout=30)
        except FileNotFoundError:
            continue
        if proc.returncode == 0 or "compose" in (proc.stdout + proc.stderr).lower():
            return candidate
    raise RuntimeError("Neither podman compose nor docker compose is available")


def write_env(path: Path, *, api_port: int, web_port: int) -> dict[str, str]:
    vals = {
        "APP_ENV": "production",
        "JWT_SECRET": secrets.token_urlsafe(48),
        "CREDENTIALS_ENCRYPTION_KEY": secrets.token_urlsafe(48),
        "API_SECRET": secrets.token_urlsafe(32),
        "DATABASE_PATH": "/data/vibeprompt.db",
        "KNOWLEDGE_UPLOAD_DIR": "/data/knowledge/uploads",
        "SKILLS_DIR": "/data/skills",
        "CORS_ORIGINS": f"http://127.0.0.1:{web_port},http://localhost:{web_port}",
        "API_PUBLISH_PORT": str(api_port),
        "WEB_PUBLISH_PORT": str(web_port),
        "FREE_TIER_ENABLED": "false",
        "CRITIC_ENABLED": "false",
        "GEMINI_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "GROQ_API_KEY": "",
        "QWEN_API_KEY": "",
        "ADMIN_EMAILS": "",
        "AUTH_MODE": "legacy",
    }
    lines = [f"{k}={v}" for k, v in vals.items()]
    path.write_text("\n".join(lines) + "\n")
    return vals


def wait_healthy(base: str, api_secret: str, timeout: float = 180.0) -> bool:
    deadline = time.time() + timeout
    headers = {"X-API-Secret": api_secret}
    last = ""
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base}/api/health", headers=headers, timeout=5.0)
            last = f"{r.status_code} {r.text[:120]}"
            if r.status_code == 200 and r.json().get("status") == "ok":
                return True
        except Exception as exc:
            last = str(exc)
        time.sleep(2)
    print("health last:", last)
    return False


def main() -> int:
    print("=== VibePrompt deployment verification ===")
    compose = detect_compose()
    api_port = int(os.environ.get("VP_API_PORT", "18080"))
    web_port = int(os.environ.get("VP_WEB_PORT", "18081"))
    env_path = REPO / ".env.production.verification"
    project = "vpverify"

    vals = write_env(env_path, api_port=api_port, web_port=web_port)
    api_secret = vals["API_SECRET"]
    base = f"http://127.0.0.1:{api_port}"
    env = os.environ.copy()
    env["COMPOSE_PROJECT_NAME"] = project
    # Point compose services at the ephemeral env file (never commit)
    env["COMPOSE_ENV_FILE"] = str(env_path)
    # Podman: docker image format so Dockerfile HEALTHCHECK is honored
    env["BUILDAH_FORMAT"] = "docker"

    compose_base = [
        *compose,
        "--project-name",
        project,
        "--env-file",
        str(env_path),
        "-f",
        str(REPO / "compose.yaml"),
    ]

    # Clean any previous verification stack
    run([*compose_base, "down", "-v"], env=env, timeout=180)

    build = run([*compose_base, "up", "-d", "--build"], env=env, timeout=900)
    record(
        "Clean container startup (compose up --build)",
        build.returncode == 0,
        (build.stderr or build.stdout)[-400:],
    )
    if build.returncode != 0:
        _write_report(vals, skipped=True)
        run([*compose_base, "down", "-v"], env=env, timeout=180)
        env_path.unlink(missing_ok=True)
        return 1

    healthy = wait_healthy(base, api_secret)
    record("Application health endpoint", healthy, base + "/api/health")
    if not healthy:
        logs = run([*compose_base, "logs", "api"], env=env, timeout=60)
        record("API logs on health failure", False, (logs.stdout or "")[-600:])
        run([*compose_base, "down", "-v"], env=env, timeout=180)
        env_path.unlink(missing_ok=True)
        _write_report(vals)
        return 1

    headers = {"X-API-Secret": api_secret}
    client = httpx.Client(base_url=base, headers=headers, timeout=60.0)

    # Unauthenticated production request rejected without user token for projects
    unauth = client.get("/api/projects")
    record(
        "Unauthenticated project list rejected in production",
        unauth.status_code == 401,
        str(unauth.status_code),
    )

    # Missing API secret
    bare = httpx.get(f"{base}/api/health", timeout=10.0)
    record(
        "Request without X-API-Secret rejected",
        bare.status_code == 401,
        str(bare.status_code),
    )

    # Auth — two users
    def register(email: str) -> str:
        r = client.post(
            "/api/auth/register",
            json={"email": email, "password": "password12345"},
        )
        r.raise_for_status()
        return r.json()["access_token"]

    try:
        token_a = register(f"a-{secrets.token_hex(4)}@example.com")
        token_b = register(f"b-{secrets.token_hex(4)}@example.com")
        record("Authentication (register two users)", True)
    except Exception as exc:
        record("Authentication (register two users)", False, str(exc))
        client.close()
        run([*compose_base, "down", "-v"], env=env, timeout=180)
        env_path.unlink(missing_ok=True)
        _write_report(vals)
        return 1

    ha = {**headers, "Authorization": f"Bearer {token_a}"}
    hb = {**headers, "Authorization": f"Bearer {token_b}"}

    pa = client.post(
        "/api/projects",
        headers=ha,
        json={
            "name": "Deploy-Cyber",
            "objective": "Cybersecurity log investigation assistant",
            "initial_message": "Windows Event Log investigation MVP with SQLite.",
        },
    )
    record("Create project + Grill conversation (user A)", pa.status_code == 200, pa.text[:200])
    pid = pa.json()["id"] if pa.status_code == 200 else None

    if pid:
        stolen = client.get(f"/api/projects/{pid}", headers=hb)
        record(
            "Two-user project isolation (B cannot read A)",
            stolen.status_code == 404,
            str(stolen.status_code),
        )
        msg = client.post(
            f"/api/projects/{pid}/messages",
            headers=ha,
            json={"content": "Confirm SQLite remains our database decision."},
        )
        record("Grill follow-up message", msg.status_code == 200, msg.text[:160])

        # Seed enough context for agent prompts via context patch if needed
        ctx = client.get(f"/api/projects/{pid}/context", headers=ha)
        record("Project context readable by owner", ctx.status_code == 200)

        # Memory persistence markers: message count
        got = client.get(f"/api/projects/{pid}", headers=ha)
        msgs = len(got.json().get("messages") or []) if got.status_code == 200 else 0
        record("Conversation messages persisted", msgs >= 2, f"messages={msgs}")

        # Books-to-Skill / orchestration path via agent prompt (builtins)
        # Force to avoid readiness gate if Grill hasn't filled all fields yet
        for agent in ("cursor", "antigravity", "codex"):
            prompt = client.post(
                f"/api/projects/{pid}/agent-prompt",
                headers=ha,
                json={"agent": agent, "force": True, "include_skills": True},
            )
            ok = prompt.status_code == 200 and bool(prompt.json().get("prompt"))
            record(f"Agent prompt export ({agent})", ok, prompt.text[:160])

        # BYOK endpoint reachable for authenticated user (no key required to list)
        byok = client.get("/api/byok", headers=ha)
        record(
            "BYOK endpoint accessible when authenticated",
            byok.status_code == 200,
            str(byok.status_code),
        )

    # Backup while API running (online backup API)
    backup = run(
        [
            *compose_base,
            "--profile",
            "backup",
            "run",
            "--rm",
            "backup",
        ],
        env=env,
        timeout=180,
    )
    record(
        "SQLite online backup (compose profile)",
        backup.returncode == 0 and "BACKUP_OK" in (backup.stdout or ""),
        (backup.stdout or backup.stderr)[-300:],
    )

    # Restart with persistent volume
    rest = run([*compose_base, "restart", "api"], env=env, timeout=180)
    time.sleep(5)
    healthy2 = wait_healthy(base, api_secret, timeout=120)
    record("Container restart", rest.returncode == 0 and healthy2)

    if pid:
        after = client.get(f"/api/projects/{pid}", headers=ha)
        record(
            "Project memory persists after restart",
            after.status_code == 200
            and len(after.json().get("messages") or []) >= msgs,
            f"status={after.status_code} messages={len(after.json().get('messages') or []) if after.status_code==200 else 'n/a'}",
        )

    # Restore drill: stop api, restore latest backup to a copy path check via exec
    # List backups inside volume by running a one-off container
    list_b = run(
        [
            *compose_base,
            "run",
            "--rm",
            "--entrypoint",
            "sh",
            "api",
            "-c",
            "ls -1 /data/backups/vibeprompt-*.db 2>/dev/null | tail -1",
        ],
        env=env,
        timeout=120,
    )
    latest = (list_b.stdout or "").strip().splitlines()
    latest_path = latest[-1].strip() if latest else ""
    if latest_path:
        run([*compose_base, "stop", "api"], env=env, timeout=120)
        restore = run(
            [
                *compose_base,
                "run",
                "--rm",
                "--entrypoint",
                "python",
                "api",
                "/app/scripts/sqlite_restore.py",
                "--backup",
                latest_path,
                "--database",
                "/data/vibeprompt.db",
            ],
            env=env,
            timeout=180,
        )
        record(
            "Database restoration from backup",
            restore.returncode == 0 and "RESTORE_OK" in (restore.stdout or ""),
            (restore.stdout or restore.stderr)[-300:],
        )
        run([*compose_base, "start", "api"], env=env, timeout=120)
        healthy3 = wait_healthy(base, api_secret, timeout=120)
        record("API healthy after restore", healthy3)
        if pid and healthy3:
            again = client.get(f"/api/projects/{pid}", headers=ha)
            record(
                "Data integrity after restore (project still readable)",
                again.status_code == 200,
                str(again.status_code),
            )
    else:
        record("Database restoration from backup", False, "No backup file found in volume")

    client.close()

    # Tear down but keep results; remove verification env file (contains secrets)
    down = run([*compose_base, "down", "-v"], env=env, timeout=180)
    record("Compose teardown", down.returncode == 0)
    env_path.unlink(missing_ok=True)

    _write_report(vals)
    failed = sum(1 for c in CHECKS if not c.passed)
    print(f"Passed={sum(1 for c in CHECKS if c.passed)} Failed={failed} Total={len(CHECKS)}")
    return 1 if failed else 0


def _write_report(vals: dict[str, str], *, skipped: bool = False) -> None:
    passed = sum(1 for c in CHECKS if c.passed)
    failed = sum(1 for c in CHECKS if not c.passed)
    # Never write real secrets into the report
    safe_cfg = {
        "APP_ENV": vals.get("APP_ENV"),
        "DATABASE_PATH": vals.get("DATABASE_PATH"),
        "CORS_ORIGINS": vals.get("CORS_ORIGINS"),
        "API_PUBLISH_PORT": vals.get("API_PUBLISH_PORT"),
        "WEB_PUBLISH_PORT": vals.get("WEB_PUBLISH_PORT"),
        "secrets_present": all(
            bool(vals.get(k)) for k in ("JWT_SECRET", "CREDENTIALS_ENCRYPTION_KEY", "API_SECRET")
        ),
        "secrets_are_placeholders": False,
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "failed": failed,
        "total": len(CHECKS),
        "production_ready_claim": failed == 0 and not skipped,
        "config_sanitized": safe_cfg,
        "checks": [asdict(c) for c in CHECKS],
    }
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "DEPLOYMENT_VERIFICATION_RESULTS.json").write_text(json.dumps(payload, indent=2))

    lines = [
        "# VibePrompt Deployment Verification Results",
        "",
        f"**Generated:** {payload['generated_at']}",
        f"**Result:** {passed} passed / {failed} failed / {len(CHECKS)} total",
        "",
        (
            "**Production-ready claim:** **Yes** — clean compose startup, health, auth, "
            "isolation, Grill, prompts, restart persistence, and backup/restore succeeded."
            if failed == 0 and not skipped
            else "**Production-ready claim:** **No** — one or more deployment checks failed."
        ),
        "",
        "## Configuration exercised (sanitized)",
        "",
        f"- `APP_ENV={safe_cfg['APP_ENV']}`",
        f"- `DATABASE_PATH={safe_cfg['DATABASE_PATH']}`",
        f"- CORS origins set for local published web port",
        f"- JWT / CREDENTIALS / API secrets: generated ephemeral values (not recorded)",
        "",
        "## Checks",
        "",
    ]
    for c in CHECKS:
        mark = "PASS" if c.passed else "FAIL"
        lines.append(f"- **{mark}** {c.name}")
        if c.detail:
            lines.append(f"  - {c.detail[:300]}")
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "```bash",
            "python backend/scripts/deployment_verification.py",
            "```",
            "",
            "Artifacts: `docs/DEPLOYMENT_VERIFICATION_RESULTS.json`",
        ]
    )
    (DOCS / "DEPLOYMENT_VERIFICATION_RESULTS.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
