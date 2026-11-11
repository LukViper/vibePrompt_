# Book-to-Skill Architecture

## Existing (preserved)

- Conversation engine: `GrillEngine` + behavioural modes (Chat / Brainstorm / Grill)
- Provider abstraction + failover + BYOK + free tier
- Auth (JWT), SQLite projects/users
- Prompt assembly in `providers/prompts.py`

## New

| Area | Path | Role |
|------|------|------|
| Catalog | `knowledge/catalog.py` | Eight target books + legal source hints |
| Acquisition | `knowledge/acquisition/` | Discovery, licensing checks, authorized download only |
| Store | `knowledge/store.py` | Books, files, jobs, concepts, audit |
| Pipeline | `knowledge/pipeline/` | Validate → extract → clean → segment → concepts |
| Skills | `skills/` | Registry, package files, draft generator, retrieval |
| API | `api/knowledge_routes.py` | Admin Knowledge Library endpoints |
| UI | `frontend/.../KnowledgeLibrary.tsx` | Admin library screens |

## Flow

1. Discover legal acquisition options (no pirate sources).
2. Admin uploads a rights-confirmed file *or* downloads an authorized open edition.
3. Pipeline extracts text and structured concepts (summaries, not quotations).
4. Skill generator builds a **draft** package under `data/skills/`.
5. Admin reviews, evaluates, approves → active skill.
6. Retrieval injects a short ranked principle block into the active mode prompt.

## Non-goals

- Automatic download of copyrighted books from unauthorized sites
- DRM bypass
- Embedding entire books into every request
- Auto-activating generated skills
