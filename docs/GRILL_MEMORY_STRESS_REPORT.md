# Grill Long-Term Memory Stress Test Report

**Generated:** 2026-11-10T22:09:27.336842+00:00
**Totals:** 40 passed / 1 failed / 41 checks

## Coverage

1. Long conversation retention (≥100 messages + engine 50-user-turn run)
2. Decision preservation (confirmed/superseded/rejected/brainstorm/corrections)
3. Retrieval relevance & multi-project isolation
4. Summary quality (losses/distortions vs authoritative state)
5. Token/char budget survival of critical fields
6. Failure recovery (summary fail, malformed, DB fail, concurrency, provider fail)

## Results by suite

### 1. Long conversation retention
- 10/10 passed
- **PASS** Conversation has >= 100 messages
- **PASS** Summary retains objective/investigation
- **PASS** Summary retains SQLite decision
- **PASS** Summary retains FastAPI/Python
- **PASS** Summary retains Elasticsearch rejected
- **PASS** Summary retains Kafka or K8s rejected
- **PASS** Summary retains open Sysmon question or outstanding ingest
- **PASS** Summary retains architecture batch
- **PASS** Assembled context retains SQLite + Elastic rejection after summary
- **PASS** Active window much smaller than full history

### 1b. Engine 100-turn retention
- 2/2 passed
- **PASS** After 50 user turns (>=100 total msgs), summary exists
- **PASS** Final assembled snapshot still has SQLite and Elastic rejection

### 2. Decision preservation
- 5/5 passed
- **PASS** Summary apply does not mutate authoritative ProjectState
- **PASS** Confirmed React decision present; HTMX superseded historically
- **PASS** Summary lists superseded history without promoting brainstorm MongoDB
- **PASS** Conflicting message cannot erase rejected Elasticsearch from summary authority block
- **PASS** User correction captured in working memory

### 3. Retrieval relevance
- 4/4 passed
- **PASS** Log project question retrieves SQLite / Elastic rejection — not shop Node stack
- **PASS** Shop question does not leak WinLog Elasticsearch rejection as selected tech
- **PASS** Project summaries/ids remain isolated in repository
- **PASS** Shop context does not inject NotesApp Kubernetes rejection

### 4. Summary quality
- 3/3 passed
- **PASS** No critical decision/rejection losses in summary
- **PASS** No terminology distortion (Elastic not selected; Mongo not confirmed)
- **PASS** Retrieved context includes rejected approaches with reasons

### 5. Token budget
- 8/8 passed
- **PASS** Tight budget keeps SQLite decision/stack
- **PASS** Tight budget keeps Elasticsearch rejection when relevant
- **PASS** Tight budget reduces message window and/or summary
- **PASS** Wide budget still prioritizes recent messages (<= max_recent)
- **PASS** Char budget acts as provider-context limiter (no silent critical drop)
- **PASS** Provider envelope gemini-like (3000 chars) keeps stack+rejections
- **PASS** Provider envelope openrouter-like (6000 chars) keeps stack+rejections
- **PASS** Provider envelope groq-like (4000 chars) keeps stack+rejections

### 6. Failure recovery
- 4/5 passed
- **PASS** Summarization failure keeps previous valid summary text
- **PASS** Malformed/empty summary does not clear tech_stack
- **FAIL** Malformed/empty summary does not wipe previous valid summary text
  - Expected: Prior non-empty summary retained (reject empty overwrite)
  - Actual: {'prior_len': 2027, 'after_len': 0, 'source': 'llm'}
  - Severity: high
  - Root cause: apply_summary_update accepts empty ConversationSummary and overwrites prior text
  - Repro: apply_summary_update(project, ConversationSummary(text='')) after a valid summary
- **PASS** Interrupted maybe_refresh_summary keeps previous valid summary
- **PASS** Interrupted/failed refresh leaves prior summary intact

### 6b. Persistence / concurrency
- 4/4 passed
- **PASS** SQLite round-trip preserves summary + structured memory
- **PASS** Failed DB persist leaves caller's ProjectState object intact
- **PASS** Concurrent updates do not cross-contaminate project memory
- **PASS** Chat provider failure does not wipe prior summary/structured memory

## Failed cases

- **[high]** 6. Failure recovery :: Malformed/empty summary does not wipe previous valid summary text — apply_summary_update accepts empty ConversationSummary and overwrites prior text

## Recommended fixes

### [high] Malformed/empty summary does not wipe previous valid summary text
- **Suite:** 6. Failure recovery
- **Root cause:** apply_summary_update accepts empty ConversationSummary and overwrites prior text
- **Repro:** `apply_summary_update(project, ConversationSummary(text='')) after a valid summary`
- **Observed:** {'prior_len': 2027, 'after_len': 0, 'source': 'llm'}
- **Fix:** In `apply_summary_update`, reject `new_summary` when `not (new_summary.text or '').strip()` if a previous non-empty summary exists; treat as `failed=True` (keep previous, set `source=failed_keep_previous`) instead of overwriting.

### Residual risks (non-failing)
1. Char budgets approximate tokens; provider-native tokenizers not used.
2. Lexical relevance may miss paraphrased retrieval needs.
3. Functional requirement prose may be abbreviated in digests when nouns differ.

## Reproduction

```bash
cd backend
.venv/bin/python scripts/memory_stress_validation.py
```

Artifacts:
- `docs/GRILL_MEMORY_STRESS_RESULTS.json`
- `docs/GRILL_MEMORY_STRESS_REPORT.md`

**Production code modified:** No
