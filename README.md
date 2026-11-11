# VibePrompt — Invisible Grill

Evidence-driven adversarial project reviewer. Grill challenges weak assumptions, unrealistic scope, contradictory requirements, and unjustified tech choices **before** you spend coding-agent tokens implementing them.

**Product principle:** Be difficult to convince with unsupported claims, but easy to convince with good evidence.

## Architecture

Modular monolith:

| Package | Role |
|---|---|
| `backend/app/providers/` | Gemini → OpenRouter → Groq failover + Groq critic behind a shared interface |
| `backend/app/orchestration/` | Selective model invocation and failure handling |
| `backend/app/grill/` | Review policy, finding lifecycle, critic reconciliation |
| `backend/app/projects/` | Structured project state |
| `backend/app/compilation/` | Deterministic readiness gate + Markdown specification compiler |
| `backend/app/persistence/` | SQLite repository (swappable) |
| `backend/app/api/` | FastAPI HTTP API |
| `backend/app/knowledge/` | Book discovery, legal acquisition, processing pipeline |
| `backend/app/skills/` | Skill registry, Book-to-Skill drafts, mode-scoped retrieval |
| `frontend/` | React + TypeScript + Vite UI |

**Behavioural modes:** Chat (conversational), Brainstorm, and Grill review — selected automatically from intent (sticky across follow-ups) or set explicitly in the UI. Critic runs only in Grill review and never rewrites the conversational reply.

**Cost-conscious orchestration:** greetings and trivial clarifications skip model debate; Grill review may run primary → critic; insistence without evidence does not withdraw findings; resolved findings are not regenerated without new material evidence.

**Provider failover (primary analysis):** Gemini → OpenRouter → Groq → offline heuristics. Only the next eligible provider is tried after a retryable failure (429, 5xx, timeout, connection). Auth/invalid-request errors skip that provider without infinite retries. Independent critic remains Groq when configured.

## Prerequisites

- Python 3.11+ (tested on 3.14)
- Node.js 20+
- Optional: `GEMINI_API_KEY`, `GROQ_API_KEY` for live model calls

Without API keys the backend runs an **offline heuristic primary** so local demos and tests still work.

## Quick start

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill keys when ready
mkdir -p data
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Vite proxies `/api` to the backend.

### Vercel (UI)

The SPA deploys from the repo root via `vercel.json`. Host the FastAPI API separately (compose), set `VITE_API_BASE_URL` / `VITE_API_SECRET` / optional Supabase `VITE_*` in Vercel, and put the Vercel origin in API `CORS_ORIGINS`. Details: `docs/DEPLOYMENT_AND_RECOVERY.md`.

## Configuration

See `backend/.env.example`.

| Variable | Purpose | Default |
|---|---|---|
| `GEMINI_API_KEY` | First primary provider | empty → skip Gemini |
| `GEMINI_MODEL` | Gemini model id | `gemini-3.8-flash` |
| `OPENROUTER_API_KEY` | First failover | empty → skip |
| `OPENROUTER_MODEL` | OpenRouter model id | `openai/gpt-4o-mini` |
| `OPENROUTER_BASE_URL` | OpenRouter API base | `https://openrouter.ai/api/v1` |
| `OPENROUTER_SITE_URL` | Optional HTTP-Referer | empty |
| `OPENROUTER_APP_NAME` | Optional X-Title | `VibePrompt` |
| `GROQ_API_KEY` | Second failover + critic | empty → skip / critic off |
| `GROQ_MODEL` | Groq model id | `openai/gpt-oss-20b` |
| `GROQ_BASE_URL` | Groq API base | `https://api.groq.com/openai/v1` |
| `PRIMARY_PROVIDER_ORDER` | Comma-separated failover order | `gemini,openrouter,groq` |
| `CRITIC_ENABLED` | Allow two-model reviews | `true` |
| `REVIEW_INTENSITY` | `low` / `normal` / `high` | `normal` |
| `PROVIDER_TIMEOUT_SECONDS` | Per-provider timeout | `30` |
| `FAILOVER_TOTAL_BUDGET_SECONDS` | Cap total failover wait | `45` |
| `MAX_OUTPUT_TOKENS` | Cap model output | `2048` |
| `DATABASE_PATH` | SQLite file | `./data/vibeprompt.db` |
| `API_SECRET` | Optional shared secret (`X-API-Secret`) | empty |
| `CORS_ORIGINS` | Allowed browser origins | localhost Vite |
| `FREE_TIER_ENABLED` | Platform-funded Qwen free tier + BYOK hybrid | `false` |
| `FREE_TIER_PROVIDER` | Free-tier provider (must be `qwen`) | `qwen` |
| `FREE_TIER_MODEL` | Free-tier model id (MuleRouter) | `qwen3.5-flash` |
| `FREE_TIER_GENERATIONS` | One-time generations per new user | `20` |
| `FREE_TIER_MAX_INPUT_TOKENS` | Cap input tokens (config) | `8000` |
| `FREE_TIER_MAX_OUTPUT_TOKENS` | Cap free-tier output tokens | `2048` |
| `FREE_TIER_RATE_LIMIT_PER_MINUTE` | Per-user generation rate limit | `10` |
| `QWEN_API_KEY` | Shared platform Qwen/DashScope key | empty |
| `QWEN_BASE_URL` | MuleRouter OpenAI-compatible base URL | `https://api.mulerouter.ai/vendors/openai/v1` |
| `JWT_SECRET` | JWT signing secret (change in production) | dev default |
| `CREDENTIALS_ENCRYPTION_KEY` | Fernet key material for BYOK encryption | dev default |
| `ADMIN_EMAILS` | Comma-separated Knowledge Library admins | empty (any auth user when free tier off) |
| `KNOWLEDGE_UPLOAD_DIR` | Uploaded book storage | `./data/knowledge/uploads` |
| `SKILLS_DIR` | Skill package files on disk | `./data/skills` |

### Knowledge Library (Book-to-Skill)

Administrators can discover the eight target books, register legal acquisition options, upload rights-confirmed PDF/EPUB/TXT/DOCX, process them into abstracted concepts (not quotations), generate **draft** skills, evaluate, approve, and roll back. Approved skills inject a short ranked principle block into Chat / Brainstorm / Grill — never entire books.

- Architecture: `docs/BOOK_TO_SKILL_ARCHITECTURE.md`
- Acquisition report: `docs/ACQUISITION_REPORT.md` (all eight titles currently require purchase/library/manual upload — no fabricated downloads)
- UI: sign in → **Knowledge Library** in the sidebar

The system refuses pirate sources and will not auto-download commercial titles without an authorized open-access URL.

### Free tier + BYOK (hybrid inference)

When `FREE_TIER_ENABLED=true`:

1. New users receive a **one-time** free generation allowance (default 20) funded by the platform’s shared `QWEN_API_KEY`.
2. Successful AI reviews consume one generation; failures and conversation-only turns do not.
3. After exhaustion, users must configure **BYOK** (Gemini / OpenRouter / Groq / Qwen). Stored keys are encrypted; raw keys are never returned by the API.
4. BYOK users keep using their selected provider/model; the platform never silently switches an exhausted user to another platform-funded provider.

Legacy mode (`FREE_TIER_ENABLED=false`) keeps the previous Gemini → OpenRouter → Groq → offline chain.

Chat responses include `provider_status` (e.g. `Gemini rate-limited; OpenRouter responding`) and `offline_review`. Keys never appear in those fields.

Model identifiers change over time; override via env. Free-tier quotas are **not** hardcoded — treat provider availability as ephemeral.

## API (selected)

- `POST /api/auth/register` / `POST /api/auth/login` / `GET /api/auth/me` — JWT auth
- `GET /api/free-tier/status` — remaining/allocated generations + funding source
- `GET|PUT /api/byok` — list / validate+save encrypted user API keys (never returned)
- `GET /api/admin/free-tier-config` — admin-safe free-tier settings (no platform key)
- `POST /api/projects` — create project (optional `initial_message`)
- `GET /api/projects` — list
- `GET /api/projects/{id}` — full state
- `POST /api/projects/{id}/messages` — chat with Grill
- `PATCH /api/projects/{id}/findings/{fid}` — `resolved` / `accepted_risk` / `rejected` / `open`
- `GET /api/projects/{id}/readiness` — deterministic gate
- `POST /api/projects/{id}/specification` — Markdown + structured spec
- `GET /api/knowledge/acquisition-report` — legal acquisition options for target books
- `GET|POST /api/knowledge/books…` — library CRUD, upload, process
- `POST /api/knowledge/skills/generate|…/approve|…/evaluate` — draft → review → activate

API keys never leave the server. Do not put secrets in the frontend.

## Tests

All automated tests mock providers — **no API credentials or quota consumption required**.

```bash
cd backend
source .venv/bin/activate
pytest -v
```

Coverage includes unrealistic scope, heavyweight infra, contradictions, sound decisions, counterevidence, insistence, resolved findings, critic reject/add-risk, malformed output, timeouts/rate limits, missing keys, compilation gates, prompt injection, secret non-exposure, multi-project isolation, and end-to-end create→review→spec.

Evaluation fixtures comparing primary-only vs two-model call counts live in `backend/tests/evaluation/`. Results are written to `backend/tests/evaluation/results/` (gitignored). **Do not claim multi-model superiority beyond what those metrics show.**

## Privacy & provider data handling

- Project text and messages are sent to configured providers (Gemini / Groq) only when a review runs.
- Treat third-party provider policies as applying to that content; VibePrompt does not claim zero data retention unless your provider contract does.
- Prompt-injection attempts in project content are sanitized and treated as data, never as instructions.
- Logs avoid printing API keys, auth headers, or full sensitive prompts.

## Finding lifecycle

`open` → `resolved` | `accepted_risk` | `rejected`

Resolved/rejected findings are not reopened without material new evidence. User disagreement ≠ counterevidence. Critic agreement ≠ proof.

## Readiness gate

Deterministic. Critical/high open findings and missing essentials block compilation. Accepted risks can yield `ready_with_accepted_risks`. LLM severity alone does not invent blockers outside validated state.

## Known limitations

- Offline heuristic primary is a thin stand-in for Gemini — useful for demos/tests, not a substitute for a live model.
- Critic reconciliation is conservative (high-impact findings are demoted, not silently deleted, on critic disagreement).
- Free-tier mode adds JWT auth + BYOK; keep `FREE_TIER_ENABLED=false` for the legacy single-tenant demo. Change `JWT_SECRET` and `CREDENTIALS_ENCRYPTION_KEY` before any public deploy.
- Live Gemini/Groq integrations are implemented against current REST APIs but not exercised in CI without keys.

## License

Use and modify freely for your own projects.
