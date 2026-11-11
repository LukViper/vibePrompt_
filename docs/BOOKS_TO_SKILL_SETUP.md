# Books-to-Skill — Setup & Usage

## Prerequisites

- Backend + frontend running (see README)
- Optional: provider API keys / BYOK for LLM chat (offline heuristics still work)
- Acquired book binaries under `books/originals/` (gitignored)

## Acquire / refresh open resources

Downloads are scripted in Phase 1; re-check `books/RESOURCE_MANIFEST.md`.

## Ingest into Knowledge Library

```bash
cd backend
source .venv-free-tier/bin/activate
python scripts/ingest_acquired_books.py --process
```

Then open the app → **Books-to-Skill / Knowledge Library** → review concepts → **Generate** draft skills → **Approve**.

## Orchestration

Chat turns select skills from:

1. User selection (future UI / API `user_selected`)
2. Behavioural mode defaults
3. Message keyword cues (architecture, prompt, grill, planning, …)

Only a compact ranked principle block is injected — never whole books.

Admin preview:

`POST /api/knowledge/orchestrate/preview`  
`{"message":"…","mode":"conversational"}`

## OSS attribution

See `docs/BOOK_TO_SKILL_OSS_INTEGRATION.md` and `books/licenses/ATTRIBUTION.md`.

## Honest status

| Resource | Status |
|----------|--------|
| Adem Yüce EN volumes (4) | Acquired (official API EPUB) |
| Lee Boonstra Prompt Engineering | Acquired (PDF) |
| QA Field Manual | Acquired (author PDF) |
| Machine Learning Systems | Not fully acquired (CC BY-NC-ND; no usable PDF at fetch time) |
