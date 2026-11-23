# API versioning

## Current

- Canonical prefix: `/api/v1/...`
- Compatibility alias: `/api/...` mounts the same handlers during transition.

Guest bootstrap (`POST /api/auth/guest` and `POST /api/v1/auth/guest`), BYOK `429`/`402` codes, and agent export payloads remain stable.

## Breaking-change policy

1. Announce deprecations in release notes and this doc.
2. Keep deprecated fields/routes for **at least 30 days**.
3. Ship additive changes under `/api/v1` without removing the `/api` alias until clients migrate.
4. A future `/api/v2` is required for incompatible contract changes.

## Client guidance

Frontend defaults to `/api` (Vite proxy / `VITE_API_BASE_URL`). Either prefix is accepted until `/api` is retired.
