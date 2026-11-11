# Grill Context-Aware Development Mentor

## 1. Existing architecture assessment

VibePrompt was already a modular FastAPI + React app with:

- Sticky behavioural modes (`conversational` / `brainstorming` / `grill_review`)
- Primary + optional critic orchestration in `GrillEngine`
- Structured `ProjectState` persisted as JSON in SQLite
- Skill/knowledge retrieval, readiness gating, and specification compilation
- BYOK + free-tier inference routing

Gaps relative to a mentoring system: persona principles were thin, context was mostly “dump whole state + chat tail”, modes did not cover build/debug, and coding-agent prompts were not first-class.

## 2. New architecture and component responsibilities

| Component | Responsibility | Primary modules |
|-----------|----------------|-----------------|
| **Grill Persona Engine** | Identity + mode behavioural principles | `app/grill/persona.py`, consumed by `app/providers/prompts.py` |
| **Context Management Engine** | Structured memory, retrieval, contradiction detection, user corrections | `app/grill/context.py`, `app/projects/state_apply.py`, `ProjectState` fields |
| **Orchestration Engine** | Intent → context → mode → prompt → LLM → validate → update | `app/grill/modes.py`, `app/grill/validate.py`, `app/orchestration/engine.py` |
| **Output Generation Engine** | Coding-agent prompts + existing specs | `app/compilation/agent_prompt.py`, `app/compilation/spec.py` |

Pipeline (unchanged entrypoints):

`POST /projects/{id}/messages` → `GrillEngine.handle_message` → mode resolve → policy → context snapshot → provider → validate → state_apply → persist.

## 3. Files created / modified / removed

### Created
- `backend/app/grill/persona.py`
- `backend/app/grill/context.py`
- `backend/app/grill/validate.py`
- `backend/app/compilation/agent_prompt.py`
- `backend/tests/test_mentor_engines.py`
- `docs/GRILL_MENTOR_ARCHITECTURE.md`

### Modified
- `backend/app/grill/modes.py` — five mentoring modes + legacy aliases
- `backend/app/providers/prompts.py` — persona-driven system prompts + richer state_patch schema
- `backend/app/providers/base.py` — extended `StatePatch`
- `backend/app/providers/mock.py` — offline heuristics for new modes
- `backend/app/projects/models.py` — context fields, API models
- `backend/app/projects/state_apply.py` — dedupe, contradictions, new fields
- `backend/app/orchestration/engine.py` — context retrieval, validation, critic on REVIEW
- `backend/app/api/routes.py` — `/context`, `/agent-prompt`
- `backend/app/config.py` — mode temperatures
- `backend/app/skills/builtin.py` / `orchestrator.py` — mode skill maps
- `backend/tests/test_behavioural_modes.py`
- Frontend: `types.ts`, `Composer.tsx`, `MessageBubble.tsx`, `App.tsx`, `api/client.ts`, `app.css`

### Removed
- None (legacy modes retained for persistence/API compatibility)

## 4. Context management details

Persisted on `ProjectState` (still SQLite JSON blob — no new DB):

- description, problem_statement
- preferences, rejected_approaches
- implementation_status, completed_milestones, outstanding_tasks, known_risks
- existing requirements, decisions, stack, architecture, findings, messages

Rules implemented:

1. Extract via model `state_patch` + deterministic `apply_state_patch`
2. Update-in-place / dedupe rather than blind append
3. Preserve decisions unless explicitly superseded; contradictions blocked by default
4. Detect tech/decision/scope conflicts against rejected approaches and prior decisions
5. Surface contradictions as high-priority open questions + reply clarifier
6. Demote clearly provisional EXPLORE ideas (`maybe` / `provisional`) to assumptions
7. Mode-specific `retrieve_relevant_context` (not full history dump)
8. User inspect/correct via `GET/PATCH /projects/{id}/context`

## 5. Orchestration decision logic

Modes: **EXPLORE | PLAN | BUILD | REVIEW | DEBUG**

- Explicit client mode wins (including legacy `conversational` / `brainstorming` / `grill_review`)
- Otherwise cue regexes (debug → review → build → plan → explore)
- Short follow-ups stick to the current (canonicalized) mode
- Critic runs only for REVIEW-equivalent modes when policy warrants it
- Post-response validation warns on premature BUILD / ideation restarts
- BUILD agent prompts are readiness-gated (`compile_agent_prompt`)

## 6. Database changes

None destructive. New fields are optional Pydantic defaults on the existing `projects.data` JSON document. Old projects load with empty new lists/strings.

## 7. Tests executed and results

```text
.venv/bin/python -m pytest \
  tests/test_mentor_engines.py \
  tests/test_behavioural_modes.py \
  tests/test_policy_lifecycle.py \
  tests/test_scenarios.py \
  tests/test_skill_orchestrator.py \
  -k "not test_18_no_secret and not test_20_e2e"
→ 66 passed, 2 deselected
```

Deselected client e2e tests require `python-multipart` in the local venv (environment packaging issue unrelated to Grill mentor changes).

## 8. Known limitations

- Context extraction quality still depends on the LLM filling `state_patch` correctly
- Conversation summaries are deterministic digests (not LLM-polished); structured memory remains authoritative — see `docs/GRILL_CONVERSATION_MEMORY.md`
- Contradiction / relevance matching is lexical, not deep semantic
- Agent prompts are provider-agnostic Markdown (not Cursor/Claude-Code-specific schemas)
- Frontend context panel shows readiness/findings; full context editor is API-first

## 9. Mentor intelligence upgrade (reasoning pipeline)

Deterministic 10-stage pipeline in `app/grill/reasoning.py`, wired from `GrillEngine` via `merge_reasoning_into_analysis`:

1. Intent/goals → 2. Context retrieval → 3. Contradiction taxonomy → 4. Assumption classes →
5. Feasibility → 6. Failure scenarios → 7. Alternatives → 8. Trade-offs → 9. Recommendation →
10. Decision proposals (`status=proposed` only)

**Invisible capability:** Critical reasoning is not a user-facing `/grill` command or mode chip.
Modes remain internal orchestration; the UI sends plain messages. Replies are one coherent
conversation turn (no report headings / mode labels). Stale resolved findings and off-topic
asks do not revive old analyses. See `tests/test_invisible_reasoning.py`.

Decision register: `DecisionStatus` + history (`app/grill/decisions.py`); API
`GET/PATCH /projects/{id}/decisions/{id}`. Confirmed decisions are never silently overwritten.

Pharmacy A–I regression: `tests/test_pharmacy_mentor_regression.py`  
Evaluation (upgraded vs baseline): `docs/GRILL_MENTOR_UPGRADE_EVAL.md`

## 10. Remaining work

- Optional UI editor for structured context fields / decision accept-reject
- Optional LLM polish pass for conversation digests (must not write structured fields)
- Stronger BUILD readiness checks before emitting implementation steps in chat
- Optional evidence retrieval for external facts when providers are configured
