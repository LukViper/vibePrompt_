# Phase 0 — Repository Architecture Report

**Date:** 2026-11-11  
**Scope:** Books-to-Skill Intelligence System for existing VibePrompt

## Existing stack (do not replace)

| Layer | Technology | Notes |
|-------|------------|--------|
| Frontend | React 19, TypeScript, Vite 6, react-router-dom | Custom CSS (`app.css`), not Tailwind |
| Backend | FastAPI modular monolith | `app/main.py` mounts `/api` + `/api/knowledge` |
| Data | SQLite | `data/vibeprompt.db`; projects JSON + knowledge/skills tables |
| Auth | Supabase Auth (when configured) + legacy JWT | BYOK keys encrypted per user |
| AI | Provider-agnostic BYOK | Gemini → OpenRouter → Groq failover; Qwen free tier optional |
| Modes | Conversational / Brainstorm / Grill | Sticky mode + critic only in Grill |

## Book-to-Skill already present

- `backend/app/knowledge/` — catalog, legal acquisition, upload, pipeline, store
- `backend/app/skills/` — builtins, draft generator, registry, retrieval, evaluate
- `frontend/src/components/KnowledgeLibrary.tsx` — admin modal
- Engine injects compact mode-scoped principles via `GrillEngine._skill_knowledge_block`
- Docs: `docs/BOOK_TO_SKILL_ARCHITECTURE.md`, `docs/ACQUISITION_REPORT.md`

## Gaps vs this brief

1. Open-resource acquisition tree (`books/…`) + manifest for new titles  
2. OSS [book-to-skill](https://github.com/virgiliojr94/book-to-skill) not studied/adapted  
3. Richer skill package (glossary, cheatsheet, chapters/, anti_patterns)  
4. Dynamic multi-skill orchestration (not only mode→skills map)  
5. Chapter-based LLM synthesis (today: heuristic concept extraction)  
6. Per-user ownership for books/skills; activation logs  
7. A/B conversation evaluation harness  

## Integration decision (Phase 2 preview)

**Adapt OSS extractors into existing `knowledge/` + `skills/` (option B).**  
Do not ship a parallel CLI/agent product. Preserve MIT attribution. Keep VibePrompt registry, BYOK, approve/rollback, and compact retrieval.

## Implementation plan (incremental)

1. Create `books/` layout + acquire open-licensed / author-hosted PDFs; write manifest  
2. Document OSS study + map parsers into pipeline  
3. Extend package writer + seed the seven named skills  
4. Add `SkillOrchestrator` selecting skills from message + mode + project context  
5. Harden Knowledge Library UX (progress, multi-upload hints) without redesigning the app  
6. Tests + benchmark harness recording real scores only  

## Non-goals

- Rewriting the conversation engine  
- Auto-downloading commercial/copyrighted books  
- Loading entire books into every prompt  
- Committing book binaries to git  
