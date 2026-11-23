# Datastore & scale posture

## Local development: SQLite only

- Default: `DATABASE_BACKEND=sqlite` + `DATABASE_PATH=./data/vibeprompt.db`
- Persistence lives under `backend/app/persistence/`
- **SQLite is not for production** — single-writer, no multi-tenant SaaS scale

## Production / staging: PostgreSQL (Neon)

- Set `DATABASE_URL=postgresql://...` (Neon, RDS, Supabase, Railway)
- Optionally `DATABASE_BACKEND=postgres`
- Apply [`backend/app/persistence/postgres_schema.sql`](../backend/app/persistence/postgres_schema.sql)
- `APP_ENV=production` **refuses to start on SQLite**

## Multi-tenancy

- `organizations` + `org_memberships` (roles: `admin` | `member` | `viewer`)
- Projects carry `org_id` + `owner_id`; soft-delete via `deleted_at`
- Queries enforce org isolation (`WHERE org_id = …` / membership checks)
- Personal org auto-created on signup

## Not supported yet

- Multi-writer horizontal scale across many API replicas without managed Postgres
- Marketing claims of “horizontally scaled multi-tenant SaaS” until HA is proven

## Migration path

1. Keep repository interfaces stable (`ProjectRepository` / `UserStore`).
2. Provision Neon; apply `postgres_schema.sql`.
3. Point `DATABASE_URL` at Neon; re-run authz / guest / BYOK tests against Postgres.
4. Enable Stripe + audit for Team plans.
