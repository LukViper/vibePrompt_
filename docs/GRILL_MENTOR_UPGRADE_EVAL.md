# Grill Mentor Intelligence Upgrade — Evaluation

**Generated:** 2026-11-11T10:26:22.069165+00:00

## Summary

- Pharmacy cases A–I: upgraded hit **9/9** (recall 1.0) vs baseline **0/9** (recall 0.0)
- Recommendation + alternatives coverage: 1.0
- High/critical false positives on clean SQLite MVP: 0
- Decision-state correct (propose → confirm with history): True
- Acknowledged reasonable clean idea: True

**Improvement claim:** **Yes** — upgraded mentor exceeds baseline on identical pharmacy cases with decision-state correctness and no high false positives on a clean project.

## Per-case

| Case | Expected | Upgraded | Baseline | Alts | Rec | Extra fields |
|---|---|---|---|---|---|---|
| A | pricing | HIT | MISS | 3 | Y | — |
| B | inventory_sync | HIT | MISS | 3 | Y | — |
| C | ux_honesty | HIT | MISS | 3 | Y | — |
| D | scope_budget | HIT | MISS | 3 | Y | — |
| E | update_cadence | HIT | MISS | 3 | Y | — |
| F | bulk_upload | HIT | MISS | 3 | Y | — |
| G | ops_ownership | HIT | MISS | 3 | Y | — |
| H | cms_commerce | HIT | MISS | 3 | Y | — |
| I | regulatory | HIT | MISS | 3 | Y | — |

## Method

- Upgraded: `run_mentor_reasoning` (10-stage deterministic pipeline).
- Baseline: legacy `detect_contradictions` on empty `StatePatch` (cannot see requirement-level pharmacy conflicts).
- False positives: clean notes/SQLite MVP explored with a reasonable plan.

## Reproduction

```bash
cd backend && .venv/bin/python scripts/grill_mentor_evaluation.py
.venv/bin/python -m pytest tests/test_pharmacy_mentor_regression.py tests/test_mentor_reasoning.py -q
```
