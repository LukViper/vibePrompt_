# VibePrompt Deployment Verification Results

**Generated:** 2026-11-18T01:23:07.712827+00:00
**Result:** Container compose verify blocked on this host; static security deploy checks **9/9**.

## Container compose
- **FAIL / blocked:** FAIL — rootless podman cannot re-exec (no writable /run/user, clone not permitted) on this CI/agent host

## Static checks
All 9/9 passed.

## Manual VPS steps
- Copy deploy/env.production.example → .env.production; set unique JWT_SECRET, CREDENTIALS_ENCRYPTION_KEY, API_SECRET (≥32 chars each, JWT≠creds)
- Set CORS_ORIGINS to the public HTTPS SPA origin(s); leave TRUSTED_PROXY_CIDRS empty or set to reverse-proxy CIDRs only
- Terminate TLS at nginx/Caddy/Traefik; proxy to 127.0.0.1:8000 only — do not publish API on 0.0.0.0
- Firewall: allow 80/443 public; deny direct access to host :8000 from WAN
- On the VPS: python backend/scripts/deployment_verification.py (expects working podman/docker compose)
- Rebuild images after requirements.txt bumps (pypdf≥6.21.4, cryptography≥50)
- Schedule SQLite backups (compose profile backup / sqlite_backup.py)

## Reproduction
```bash
python backend/scripts/deployment_verification.py
```
