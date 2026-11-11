# Phase 2 — Open-Source book-to-skill Integration

**Upstream:** https://github.com/virgiliojr94/book-to-skill  
**License:** MIT  
**Local study copy:** `vendor/book-to-skill/` (not used as a runtime dependency)

## What the upstream project does

CLI / agent workflow that converts PDF/EPUB/… into an Agent Skills package under `~/.agents/skills/<slug>/` with `SKILL.md`, chapter files, glossary, patterns, cheatsheets, and on-demand chapter retrieval for coding agents.

## Decision: Option B — Adapt into VibePrompt

| Option | Choice |
|--------|--------|
| A. Depend on upstream as a library | Rejected — agent-oriented install paths and host conventions do not match FastAPI |
| **B. Adapt extractors + package ideas** | **Selected** |
| C. Fork as a parallel product | Rejected — would duplicate VibePrompt skill registry / BYOK / modes |

### Map into VibePrompt

| Upstream idea | VibePrompt home |
|---------------|-----------------|
| Multi-format parsers | Strengthen `knowledge/pipeline/extract_text.py` |
| Chapter segmentation | `knowledge/pipeline/segment.py` |
| Distilled principles / decision rules | `skills/generator.py` + package writer |
| Supporting files (glossary, cheatsheet, patterns) | Extended `_write_skill_files` |
| On-demand chapter load | Orchestrator retrieval (ranked, capped) — never full book |
| Agent skill activation | `skills/orchestrator.py` + behavioural modes |

### Preserve

- MIT copyright / LICENSE attribution (this doc + `books/licenses/ATTRIBUTION.md`)
- Existing skill registry, approve/rollback, SQLite store
- Provider abstraction and BYOK
- Copyright policy: abstractions + provenance, not verbatim chapters

### Do not take as-is

- `~/.claude/skills` / Copilot install symlinks
- Dumping chapter bodies into every chat turn
- Replacing GrillEngine or mode prompts
