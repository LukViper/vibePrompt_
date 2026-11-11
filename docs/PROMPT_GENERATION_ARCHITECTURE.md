# Book-Informed Multi-Agent Prompt Generation

## Goal

Generate **context-aware, knowledge-informed, agent-specific** implementation prompts from Grill’s structured project state — without rebuilding Grill, Books-to-Skill, or the existing compiler facade.

## Phase 1 — Reused components

| Component | Location | Role |
|---|---|---|
| GrillEngine | `app/orchestration/engine.py` | Owns chat; readiness on every turn; skill blocks in chat |
| ProjectState / context | `app/projects/models.py`, `app/grill/context.py` | Authoritative product memory |
| Conversation memory | `app/grill/memory.py` | Summaries for chat (agent prompts use structured fields) |
| Books-to-Skill | `app/knowledge/*`, `app/skills/*` | Ingest → concepts → skills → retrieval |
| Skill orchestrator | `app/skills/orchestrator.py` | Dynamic selection, deps, ranking |
| Agent prompt facade | `app/compilation/agent_prompt.py` | Public API → pipeline |
| Readiness | `app/compilation/readiness.py` | Checklist + conflicts + `implementation_ready` |
| BYOK / providers | `app/byok/*`, `app/providers/*` | Used for Grill chat — **not** required for prompt compilation |

## Architecture

```
ProjectState (Grill)
    → assess_readiness (checklist + conflicts + score)
    → classify_prompt_task
    → select_skills_for_prompt → build_orchestration_context (Books-to-Skill)
    → Agent adapter (Cursor | Antigravity | Codex)
    → validate_agent_prompt (quality gate)
    → AgentPromptResult
```

Pipeline: `app/compilation/prompt_pipeline.py`. **No second orchestration engine.**

## Readiness gate (Phase 2)

Returns:

- `ready` — discovery/chat-friendly gate
- `checklist[]` — mandatory/conditional pass/fail
- `score_pct` — derived **from** checklist (**never** trusted alone)
- `conflicts[]` — stack vs rejected, scope in/out, conflicting decisions
- `implementation_ready` — full mandatory + applicable conditionals, no conflicts/blockers

Agent prompts gate on **`implementation_ready`**.

Mandatory: problem/objective, users, functional + non-functional requirements, tech stack, architecture, scope-in, dependencies, acceptance criteria, constraints.  
Conditional: data models (persistence/API cues), security notes (auth/security cues).

Below 100% → blocked prompt listing checklist gaps (not a fake complete brief).

## Skill selection (Phase 3–4)

Book-derived builtins (abstracted, not verbatim):

| Source theme | Skill slug(s) |
|---|---|
| The Mom Test | `customer_discovery` |
| Conversational Design | `conversational_discovery` |
| User Story Mapping / discovery | `product_discovery`, `project_planning` |
| The Scout Mindset | `grill` |
| Prompt Engineering for LLMs | `prompt_engineering`, `prompt_evaluator` |
| AI Engineering | `agent_engineering`, `technical_architecture` |

Logic:

1. Classify task (`security_platform`, `nlp_application`, …) from project + task text.
2. Seed **domain hints** (examples, not hardcoded final sets).
3. `build_orchestration_context` in BUILD mode — cues + user selections.
4. Soft **dependencies** (`prompt_evaluator` → `prompt_engineering`, etc.) without displacing user/cue skills.
5. Rank principles + enabled book concepts; dedupe; cap; keep `[src:book_id/chapter]`.
6. Never inject entire books/libraries.

## Agent adapters (Phase 5)

| Agent | Module | Emphasis |
|---|---|---|
| Cursor | `agents/cursor.py` | Repo inspection, module boundaries, scoped diffs, tests |
| Antigravity | `agents/antigravity.py` | Understanding, decomposition, sequence, verification, deliverables |
| Codex | `agents/codex.py` | Goal / constraints / done-when; AGENTS.md-aware |

Separate compilers — not a renamed generic heading. Shapes checked against public Cursor / Antigravity / Codex docs.

## Quality validation (Phase 6)

`app/compilation/quality.py` — completeness, consistency, context accuracy, requirement coverage, clarity, testability, scope, agent compatibility, invented details, redundancy.  
Fail → blocked unless `force=true`. Length alone never implies ready.

## UX (Phase 7)

- Header **Agent prompt** emphasized when `implementation_ready`.
- Modal: agent picker, checklist/conflicts, skill reasons, preview, generate/regenerate/refine, copy.
- APIs: `POST /projects/{id}/agent-prompt`, `POST …/agent-prompt/preview-skills`.

## Test results (Phase 8)

Executed 2026-11-11:

```bash
cd backend && .venv/bin/python -m pytest \
  tests/test_prompt_pipeline.py \
  tests/test_skill_orchestrator.py \
  tests/test_mentor_engines.py -q
# 38 passed
```

Full suite: **160+ passed** (includes conversation memory, knowledge, free tier).

Coverage highlights:

| Case | Result |
|---|---|
| Incomplete context | Blocked + checklist gaps |
| Conflicting requirements (rejected tech on stack) | `implementation_ready=False` |
| Cursor / Antigravity / Codex | Distinct prompts |
| Security vs NLP task class | Different domain skill hints |
| Missing books | Builtins still compile |
| Long specs | Still agent-compatible |
| Book-informed vs without skills | Skills add principles; quality ≥ baseline; rejected tech not promoted |
| Skill dependencies | `prompt_evaluator` pulls `prompt_engineering` first |
| BYOK independence | Compilation needs no provider keys |

### Book-informed vs baseline (measured)

On a ready WinLog fixture with builtins:

- Book-informed prompts include skill reasons + principle block; baseline does not.
- Quality score of book-informed ≥ baseline.
- Prompt length increases with retrieved principles (not empty padding).
- Elasticsearch remains in rejected/prohibited text and **not** on the tech-stack line.

## Reproduction

```bash
cd backend
.venv/bin/python -m pytest tests/test_prompt_pipeline.py -q
```
