# Grill Architecture Adversarial Validation Report

**Date:** 2026-11-11 (updated after remediation)  
**Scope:** Grill mentor validation failures + implemented fixes  
**Production architecture:** Preserved (`GrillEngine`, BYOK, SQLite JSON persistence)

## Executive verdict (post-fix)

All **seven priority failures** from the initial adversarial validation are remediated.

| Suite | Result |
|-------|--------|
| Targeted + mentor/policy/behavioural/scenarios | **83 passed** |
| Broader regression (skills, free-tier, failover, providers) | **123 passed** |
| Adversarial harness `scripts/adversarial_grill_validation.py` | **64 passed / 0 failed** |

---

## Failure → fix matrix

### MT-1 — Low review intensity skipped the LLM

| | |
|--|--|
| **Previously failing** | `review_intensity=low` + substantive question → `CONVERSATION_ONLY` canned “Understood…” |
| **Root cause** | Policy used intensity to decide whether to call the model |
| **Fix** | `decide_review_policy` only skips the LLM for greetings / ultra-short acks. Intensity now gates **critic depth / two-model**, and is injected into prompts via `GenerationSettings.review_intensity` |
| **Tests** | `test_low_intensity_substantive_question_invokes_primary`, `test_engine_low_intensity_calls_provider_for_question`, `test_provider_failure_falls_back_offline` |

### CX-1 / CX-2 — Competing technologies accepted together

| | |
|--|--|
| **Previously failing** | PostgreSQL+MongoDB and FastAPI+Node.js both landed in `tech_stack` |
| **Root cause** | Append-only flat `tech_stack`; contradictions only blocked `decisions` field |
| **Fix** | Structured `TechnologySelection` (`app/grill/tech.py`) with categories, one primary per category, alternatives vs rejected, explicit `replace_technology`, React+FastAPI / PostgreSQL+Redis allowed |
| **Tests** | `test_postgres_to_mongodb_*`, `test_fastapi_vs_nodejs_conflict`, `test_react_plus_fastapi_coexist`, `test_postgres_plus_redis_coexist` |

### CI-1 — Architecture notes silently overwritten

| | |
|--|--|
| **Previously failing** | New notes replaced confirmed architecture text |
| **Root cause** | `architecture_notes = cleaned` unconditional assign |
| **Fix** | `app/grill/notes.py` safe merge: fill / append compatible / hold conflicting as `proposed` + clarification; `architecture_notes_mode=replace` for intentional supersede with history |
| **Tests** | `test_architecture_notes_merge_compatible`, `test_architecture_notes_conflict_preserves_existing`, `test_architecture_notes_explicit_replace_keeps_history` |

### CI-4 — Non-canonical stack tokens persisted

| | |
|--|--|
| **Previously failing** | `"MongoDB or SQLite"` accepted as a stack entry |
| **Root cause** | No validation/canonicalization before persistence |
| **Fix** | `parse_technology_token` normalizes known names, rejects malformed/ambiguous OR-choices as unverified alternatives / open questions |
| **Tests** | `test_invalid_llm_tech_tokens_not_persisted`, `test_mongodb_as_alternative_not_selection` |

### CR-1 / CR-2 — Offline heuristic lost stack/rejections

| | |
|--|--|
| **Previously failing** | Offline path left `tech_stack=[]` and `rejected_approaches=[]` |
| **Root cause** | Heuristic never extracted explicit use/reject statements; PLAN mode always brainstormed |
| **Fix** | `app/grill/offline_extract.py` conservative extractors; merged into `heuristic_primary`; explicit statements handled before brainstorm branch |
| **Tests** | `test_offline_extract_*`, `test_offline_heuristic_retains_stack_and_rejection` |

### Additional hardening (from harness)

| Item | Fix |
|------|-----|
| Manual context `tech_stack` vs DB decision inconsistency | Manual updates are explicit replaces; DB decision superseded/aligned |
| Rejected Elasticsearch reintroduction | `apply_technology_tokens(..., rejected_names=...)` blocks selection |

---

## New / updated modules

| File | Role |
|------|------|
| `app/grill/tech.py` | Categories, canonicalization, conflicts, selections |
| `app/grill/notes.py` | Safe long-form note merge/history |
| `app/grill/offline_extract.py` | Deterministic offline stack/rejection extraction |
| `app/grill/policy.py` | Intensity ≠ LLM suppression |
| `app/projects/state_apply.py` | Wired tech + notes validation |
| `app/providers/prompts.py` | Intensity instruction block |
| `tests/test_validation_fixes.py` | New coverage for all priority fixes |

---

## Remaining limitations

1. **Catalog-bound canonicalization** — unknown tokens become `unverified` proposals, not invented mappings (by design).  
2. **Architecture conflict detection** is keyword/opposition-heuristic, not semantic NLP.  
3. **Multi-primary same category** only via explicit non-primary `role` (not fully exposed in LLM schema yet).  
4. **Live provider availability** still depends on keys/network; offline path is improved but not equal to a strong model.  
5. **Manual context PATCH** note fields use intentional `replace` semantics (user edits are authoritative).

---

## Reproduction

```bash
cd backend
.venv/bin/python -m pytest tests/test_validation_fixes.py \
  tests/test_mentor_engines.py tests/test_behavioural_modes.py \
  tests/test_policy_lifecycle.py tests/test_scenarios.py \
  tests/test_skill_orchestrator.py tests/test_free_tier.py \
  tests/test_failover.py tests/test_providers_failures.py -q

set -a && . ./.env && set +a
.venv/bin/python scripts/adversarial_grill_validation.py
# → 64 passed / 0 failed
```

Raw harness output: [`GRILL_ADVERSARIAL_VALIDATION_RESULTS.json`](./GRILL_ADVERSARIAL_VALIDATION_RESULTS.json)
