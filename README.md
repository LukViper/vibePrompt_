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
| `frontend/` | React + TypeScript + Vite UI |

**Cost-conscious orchestration:** greetings and trivial clarifications skip model debate; material decisions may run primary → critic; insistence without evidence does not withdraw findings; resolved findings are not regenerated without new material evidence.

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

Chat responses include `provider_status` (e.g. `Gemini rate-limited; OpenRouter responding`) and `offline_review`. Keys never appear in those fields.

Model identifiers change over time; override via env. Free-tier quotas are **not** hardcoded — treat provider availability as ephemeral.

## API (selected)

- `POST /api/projects` — create project (optional `initial_message`)
- `GET /api/projects` — list
- `GET /api/projects/{id}` — full state
- `POST /api/projects/{id}/messages` — chat with Grill
- `PATCH /api/projects/{id}/findings/{fid}` — `resolved` / `accepted_risk` / `rejected` / `open`
- `GET /api/projects/{id}/readiness` — deterministic gate
- `POST /api/projects/{id}/specification` — Markdown + structured spec

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
- No multi-user auth beyond optional `API_SECRET`; add real auth before exposing publicly.
- Live Gemini/Groq integrations are implemented against current REST APIs but not exercised in CI without keys.

## License

Use and modify freely for your own projects.
