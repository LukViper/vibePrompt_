# Datastore & scale posture

VibePrompt v1 is an **evidence-backed single-node beta**.

## Current: SQLite WAL

- Persistence lives under `backend/app/persistence/` (project + user stores).
- Prefer **SQLite WAL** and treat the process as a **single-writer** boundary.
- This is appropriate for local demos, single-tenant beta, and one API node behind the Vercel SPA.

## Not supported today

- Multi-writer horizontal scale
- Multi-tenant public SaaS with shared DB writers across many API replicas

## Migration path (when needed)

1. Keep the repository interfaces in `ProjectRepository` / `UserStore` stable.
2. Replace SQLite SQL with PostgreSQL (connection pool, migrations, WAL-equivalent isolation).
3. Re-run authorization, guest/BYOK, and knowledge-library tests against the new store.
4. Update product copy only after multi-writer is proven — until then, keep “single-node beta” language.

Do not market VibePrompt as horizontally scaled multi-tenant until that path is implemented and tested.
