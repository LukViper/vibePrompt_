# Phase 2 — Commercial differentiation

## ROI outcomes

- Events: `finding_blocked_from_impl`, `readiness_pass` / `readiness_fail` (on export), `agent_runs_reported`
- Dashboard: `GET /api/v1/orgs/{org_id}/roi`
- Self-report: `POST /api/v1/orgs/{org_id}/roi/agent-runs`
- SPA shows an ROI strip for signed-in users (estimated tokens saved, blocked findings, gate pass rate)

Estimates are **heuristic for pricing conversations**, not Stripe metering.

## Team collaboration

- Finding comment threads + @mention notifications
- Org-level rejected-approaches library (promoted from project rejects)
- In-app notifications: `GET /api/v1/notifications`

## Integrations

### CLI

```bash
# Offline local readiness (pre-commit friendly)
cd backend && python -m app.cli review --project ../my-app --fail-on-block

# Live Grill via API
python -m app.cli review --project ../my-app --api-base http://127.0.0.1:8000/api/v1 --token "$TOKEN"

python -m app.cli github-app-info
python -m app.cli agent-plugin-info
```

### GitHub App webhook

- Endpoint: `POST /api/v1/integrations/github/webhook`
- Events: `pull_request` opened / edited / reopened / synchronize (+ `ping`)
- Auth: `X-Hub-Signature-256` with `GITHUB_WEBHOOK_SECRET`
- Behavior: creates a Grill project from the PR body, runs a review, returns a check-style `conclusion` (`success`|`failure`) for the App to post on the PR
- Optional: set `GITHUB_INTEGRATION_USER_ID` so PR projects land in that user's org

### Agent readiness gate (Cursor / Codex / Antigravity)

- Manifest: `GET /api/v1/integrations/agent-gate/manifest`
- Status: `GET /api/v1/integrations/agent-gate/{project_id}` → `allow_implementation`
- Plugins must abort implementation when `allow_implementation` is false
- Export: `POST /api/v1/projects/{id}/agent-prompt` when allowed

### Email notifications

Set `SMTP_*` + `NOTIFY_FROM_EMAIL` to email org members when a GitHub PR Grill creates blocking findings. Without SMTP, notifications stay in-app only.

## Knowledge moat

- Vertical skill packs (seeded): healthtech, fintech, SaaS — `GET /api/v1/skills/verticals`
- Org playbook → draft skill: `POST /api/v1/orgs/{org_id}/playbooks`
