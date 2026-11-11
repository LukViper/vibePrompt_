# Conversation Summary Truncation — Investigation Report

**Verdict:** Summary compression is **partially responsible** for stale recommendations — not because char truncation alone invents Marg advice, but because (1) summaries previously **collapsed proposed decisions into “Confirmed”**, (2) older **assistant recommendations** were retained in the digest without a non-decision tag / exclusion scrub, (3) **relevance boost** could revive excluded topics, and (4) the **critic received a different snapshot** than the primary. Truncation warnings are a symptom of budget pressure, not the sole root cause.

Do **not** treat raising `context_max_total_chars` as the permanent fix.

---

## Observed warning

```text
Conversation summary truncated to fit context budget. Excluded N older message(s) from active window.
```

Emitted from `assemble_prompt_context` notes when:

1. Summary text is halved until under `max_total_chars`, and/or  
2. Oldest messages are dropped from the active window (keeping ≥2 turns).

Surfaced to clients via `GrillEngine._run_primary` → `metrics.limitations` when notes contain `budget` / `Excluded`.

---

## Source map (exact files / functions)

| Concern | File | Function(s) |
|---|---|---|
| Summary generation | `backend/app/grill/memory.py` | `build_deterministic_summary`, `_structured_memory_digest`, `_message_digest` |
| Summary apply / reuse | `backend/app/grill/memory.py` | `apply_summary_update`, `maybe_refresh_summary`, `should_summarize` |
| Truncation + window | `backend/app/grill/memory.py` | `assemble_prompt_context`, `select_recent_messages` |
| Working memory / exclusions | `backend/app/grill/memory.py` | `update_working_memory`, `extract_turn_exclusions`, `scrub_summary_for_exclusions` |
| Orchestration wiring | `backend/app/orchestration/engine.py` | `handle_message`, `_run_primary`, `_assemble_context`, `_snapshot` |
| Structured vs summary authority | `docs/GRILL_CONVERSATION_MEMORY.md` | architecture contract |
| Diagnostics | `backend/app/grill/context_diagnostics.py` | `ContextDiagnostics`, `record_diagnostics` |
| Regression | `backend/tests/test_summary_truncation_stale.py` | Marg long-convo cases |

Config knobs (`backend/app/config.py`): `summary_min_messages`, `summary_min_new_messages`, `summary_keep_recent`, `context_max_summary_chars`, `context_max_total_chars`, `history_max_messages`.

---

## Inspection answers

### 1. How summaries are generated
Deterministic (not LLM): structured digest first, then older-message digest (`keep_recent` excluded). Written by `maybe_refresh_summary` **after** the reply is assembled — so the **current** primary call often **reuses** the previous summary version (`summary_reused`).

### 2. Topic boundaries / decision context
Previously weak: message digest was a flat list; assistant recommendations were not labeled. **Fixed:** `[recommendation-not-decision]` tags; structured section keeps topic facts separate from digest.

### 3. Decision statuses
**Bug found:** `_structured_memory_digest` labeled all non-superseded decisions as **“Confirmed decisions”**, so `status=proposed` (e.g. Marg export) looked user-approved after compression.  
**Fixed:** distinct headings — confirmed / provisionally_accepted / proposed / unverified / rejected / resolved / superseded. Snapshot `decisions[]` always include `status` + `source`.

### 4. Explicit user exclusions
**Previously did not survive** compression.  
**Fixed:** `WorkingMemory.turn_exclusions` via `extract_turn_exclusions`; `scrub_summary_for_exclusions` strips matching digest lines; relevance boost skips excluded older turns.

### 5. Primary vs critic context
**Bug found:** Primary used `assemble_prompt_context` snapshot (summary + budget trim). Critic used `_snapshot` → `retrieve_relevant_context` only — **not identical**.  
**Fixed:** critic receives `assembled.snapshot` (same object primary used). Diagnostics record `primary_critic_snapshots_identical`.

### 6. Older recommendations into unrelated requests
**Partially yes:** reused summary digest + mislabeled “confirmed” proposals + relevance boost could reintroduce Marg. Deterministic mentor reply path already tried to avoid off-topic; LLM context was the larger risk. Exclusion scrub + status labels address this without raising the budget.

### 7. Repeated truncation / summary reuse
Yes. Each over-budget request can re-truncate the **same** stored summary text for the prompt (does not rewrite DB). `maybe_refresh_summary` only bumps version when message thresholds fire — so truncated prompt views are ephemeral; the stored summary remains until the next refresh.

---

## Diagnostic logging (per request)

`ContextDiagnostics` records (secrets redacted):

- Current user message  
- Active conversation messages + IDs  
- Summary before/after truncation  
- Excluded message IDs  
- Retrieved project facts + provenance (`status`/`source`)  
- Primary snapshot keys + summary excerpt  
- Critic snapshot keys + summary excerpt + identity flag  
- Reply before/after post-processing  

Logger: `vibeprompt.context_diagnostics`. Ring buffer: `recent_diagnostics()`.

---

## Reproduction results

Harness: `tests/test_summary_truncation_stale.py` + long Marg fixture.

| Variant | Result |
|---|---|
| Truncation **enabled** (`max_total_chars≈2600`) + exclude Marg | Digest Marg **recommendations removed**; proposed Marg decision remains **`proposed`**; marketing reply has **no Marg** |
| Truncation **disabled** (large budget) + exclude Marg | Same exclusion scrub; no Marg recommendation in digest |
| Critic context | Primary and critic now share **assembled.snapshot** (parity) |
| Unrelated Sunday-hours ask after long Marg history | Reply stays on hours/elderly — **no “Scheduled Marg export” recycle** |
| Status integrity | Confirmed `CMS=WordPress` ≠ Proposed `Inventory sync=Scheduled Marg export` |

Pytest: `26 passed` for truncation + conversation memory + invisible reasoning suites (this change set).

---

## Responsibility assessment

| Factor | Role |
|---|---|
| Char truncation of summary | **Contributing** — can drop topic boundaries unevenly; warning is real |
| Mislabeled proposed→confirmed in digest | **Primary defect** for “stale confirmed Marg” |
| Unlabeled assistant recommendations in digest | **Primary defect** for recommendation bleed |
| Critic ≠ primary snapshot | **Contributing** — divergent analysis |
| Relevance boost of excluded older turns | **Contributing** |
| Simply raising token budget | **Not** an adequate permanent fix |

**Overall: partially responsible** — compression pipeline defects amplified stale Marg advice; truncation pressure made the warning visible but was not the only cause.

---

## Fixes shipped (preserve decisions, drop irrelevant history)

1. Status-aware structured digest + snapshot decisions.  
2. `[recommendation-not-decision]` tags in message digest.  
3. Turn exclusions + digest scrub + relevance-boost filter.  
4. Critic uses primary’s assembled snapshot.  
5. Per-request diagnostics without secrets.

---

## How to re-run

```bash
cd backend
.venv/bin/python -m pytest tests/test_summary_truncation_stale.py tests/test_conversation_memory.py -q
```
