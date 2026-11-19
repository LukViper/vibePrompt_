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

```bash
# Offline local readiness (pre-commit friendly)
cd backend && python -m app.cli review --project ../my-app --fail-on-block

# Live Grill via API
python -m app.cli review --project ../my-app --api-base http://127.0.0.1:8000/api/v1 --token "$TOKEN"

# Stubs
python -m app.cli github-app-info
python -m app.cli agent-plugin-info
```

## Knowledge moat

- Vertical skill packs (seeded): healthtech, fintech, SaaS — `GET /api/v1/skills/verticals`
- Org playbook → draft skill: `POST /api/v1/orgs/{org_id}/playbooks`
