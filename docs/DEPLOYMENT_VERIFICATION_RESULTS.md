# VibePrompt Deployment Verification Results

**Generated:** 2026-11-10T23:51:01.951325+00:00
**Result:** 21 passed / 0 failed / 21 total

**Production-ready claim:** **Yes** — clean compose startup, health, auth, isolation, Grill, prompts, restart persistence, and backup/restore succeeded.

## Configuration exercised (sanitized)

- `APP_ENV=production`
- `DATABASE_PATH=/data/vibeprompt.db`
- CORS origins set for local published web port
- JWT / CREDENTIALS / API secrets: generated ephemeral values (not recorded)

## Checks

- **PASS** Clean container startup (compose up --build)
  - behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.
Copying config sha256:676
- **PASS** Application health endpoint
  - http://127.0.0.1:18080/api/health
- **PASS** Unauthenticated project list rejected in production
  - 401
- **PASS** Request without X-API-Secret rejected
  - 401
- **PASS** Authentication (register two users)
- **PASS** Create project + Grill conversation (user A)
  - {"id":"prj_d1455ae65c7e","name":"Deploy-Cyber","description":"","objective":"Cybersecurity log investigation assistant","problem_statement":"","intended_users":[],"success_criteria":[],"functional_req
- **PASS** Two-user project isolation (B cannot read A)
  - 404
- **PASS** Grill follow-up message
  - {"message":{"id":"msg_aed2ffcdff76","role":"assistant","content":"That makes sense. I can help you shape the idea, plan options, or run a Review when you want p
- **PASS** Project context readable by owner
- **PASS** Conversation messages persisted
  - messages=4
- **PASS** Agent prompt export (cursor)
  - {"readiness":{"ready":false,"status":"not_ready","blockers":[],"warnings":["No technology or architecture decisions recorded yet","Conditional gap: Security req
- **PASS** Agent prompt export (antigravity)
  - {"readiness":{"ready":false,"status":"not_ready","blockers":[],"warnings":["No technology or architecture decisions recorded yet","Conditional gap: Security req
- **PASS** Agent prompt export (codex)
  - {"readiness":{"ready":false,"status":"not_ready","blockers":[],"warnings":["No technology or architecture decisions recorded yet","Conditional gap: Security req
- **PASS** BYOK endpoint accessible when authenticated
  - 200
- **PASS** SQLite online backup (compose profile)
  - vpverify_api_1
BACKUP_OK: /data/backups/vibeprompt-20261110T235021Z.db

- **PASS** Container restart
- **PASS** Project memory persists after restart
  - status=200 messages=4
- **PASS** Database restoration from backup
  - RESTORE_OK: /data/vibeprompt.db
PREVIOUS_SAVED: /data/vibeprompt.db.pre-restore-20261110T235048Z

- **PASS** API healthy after restore
- **PASS** Data integrity after restore (project still readable)
  - 200
- **PASS** Compose teardown

## Reproduction

```bash
python backend/scripts/deployment_verification.py
```

Artifacts: `docs/DEPLOYMENT_VERIFICATION_RESULTS.json`
