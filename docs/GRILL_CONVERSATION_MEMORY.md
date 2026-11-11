# Grill Conversation Summarization & Long-Term Memory

## Architecture changes

Extends the existing Grill stack without replacing `GrillEngine`, structured `ProjectState`, BYOK, or SQLite JSON persistence.

| Layer | Module | Role |
|-------|--------|------|
| Working memory | `WorkingMemory` on `ProjectState` | Intent, mode, unresolved questions, current task, last correction |
| Rolling summary | `ConversationSummary` (+ short history) | Digests older turns; **non-authoritative** |
| Structured memory | Existing project fields + tech/notes | **Authoritative** source of truth |
| Assembly | `app/grill/memory.py` | Relevance window + summary + structured snapshot under a char budget |
| Triggers | `maybe_refresh_summary` | After reply persistence — outside the critical LLM call |

## Memory lifecycle

1. **Turn start:** resolve mode → update `working_memory` from intent/mode/open questions/tasks.  
2. **Context assembly:** `retrieve_relevant_context` (structured) + `assemble_prompt_context` (summary + capped recent messages).  
3. **LLM call:** uses assembled snapshot + conversation tail (not full history).  
4. **Turn end:** persist messages → optionally refresh rolling summary if thresholds met → save project.

Summaries **never** write into decisions, tech selections, requirements, or rejections.

## Summarization strategy

- **Deterministic-first:** summary text is built from structured memory (objective, users, stack, **status-distinct** decisions, rejections, constraints, open questions, milestones, architecture notes) plus a compact digest of older messages.  
- Decision statuses stay separate in the digest: confirmed / provisionally_accepted / proposed / unverified / rejected / resolved / superseded — proposed mentor suggestions are never labeled confirmed.  
- Brainstorm cues are labeled `[brainstorm-cue]`; assistant recommendations are labeled `[recommendation-not-decision]`.  
- **Turn exclusions** (`WorkingMemory.turn_exclusions`) scrub matching digest lines and block relevance-boost revival.  
- Primary and critic receive the **same** `assemble_prompt_context` snapshot.  
- Per-request audit: `app/grill/context_diagnostics.py` (no secrets). Investigation: `docs/SUMMARY_TRUNCATION_INVESTIGATION.md`.  
- **Versioning:** each refresh increments `version`; previous summaries kept in `conversation_summary_history` (last 5).  
- **Failure:** `apply_summary_update(..., failed=True)` keeps the prior summary and marks `source=failed_keep_previous`.  
- **Triggers (not every message):**  
  - `summary_min_messages` (default 16)  
  - `summary_min_new_messages` since last coverage (default 8)  
  - Older-message char growth

No vector database. No new external dependencies. Raising the char budget alone is not the permanent fix for stale recommendations.

## Retrieval strategy

For each request:

1. Mode-relevant **structured** project slice (`retrieve_relevant_context`)  
2. **Working memory** overlay  
3. **Conversation summary** (trimmed) with explicit “structured wins” note  
4. **Recent messages** (default history window) with light keyword overlap boost for 1–2 older relevant turns  

Critical keys (`tech_stack`, `rejected_approaches`, active `decisions`) are re-asserted if missing from the mode slice.

## Token / context management

Config:

- `context_max_total_chars` (default 28000)  
- `context_max_summary_chars` (default 4000)  
- `history_max_messages` / `history_max_chars`  

Trim order when over budget:

1. Shrink summary text  
2. Drop oldest messages in the active window (keep ≥2 turns)  
3. **Do not** drop tech stack, rejections, or confirmed decisions to fit the budget  

## Database changes

None destructive. New optional JSON fields on existing `projects.data`:

- `conversation_summary`  
- `conversation_summary_history`  
- `working_memory`  

Older projects load with empty/default values via Pydantic.

## Tests and actual results

```text
.venv/bin/python -m pytest \
  tests/test_conversation_memory.py \
  tests/test_validation_fixes.py \
  tests/test_mentor_engines.py \
  tests/test_behavioural_modes.py \
  tests/test_policy_lifecycle.py \
  tests/test_scenarios.py \
  tests/test_skill_orchestrator.py \
  tests/test_free_tier.py \
  tests/test_failover.py \
  tests/test_providers_failures.py -q
```

**Result: 136 passed** (including new memory suite).

Coverage includes: long conversations, multi-decision retention, contradictory brainstorm vs confirmed structure, user corrections in working memory, summary regeneration/versioning, failed summarization keep-previous, retrieval relevance, token-budget assembly, project isolation, provider failure without memory corruption.

## Remaining limitations

1. Message digests are extractive/heuristic — not LLM-polished prose (by design for integrity/cost).  
2. Relevance boost is lexical overlap, not semantic search.  
3. Summary refresh is synchronous post-reply (fast deterministic); not a background worker.  
4. Very large single messages are still truncated per `history_max_chars`.  
5. Optional future LLM polish of digests can plug into `apply_summary_update` without changing structured memory rules.
