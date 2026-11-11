# Phase 9 — Evaluation notes

## Automated (recorded)

| Suite | Result |
|-------|--------|
| `tests/test_skill_orchestrator.py` | Skill cue selection + compact prompt block |
| `tests/test_knowledge_pipeline.py` | Acquisition honesty, upload→process→draft→approve |
| Existing behavioural / failover suites | Must stay green (no mode regression) |

Run:

```bash
cd backend && pytest -q
```

## Structural skill evaluation

`POST /api/knowledge/skills/{id}/evaluate` records metrics in `skill_evaluations`  
(principle counts, duplicate rate, contradiction heuristic, retrieval checks).  
It does **not** invent user-satisfaction scores.

## A/B conversation benchmark

Not yet a full scored human study. When run, record:

- Requirement completeness (rubric 0–N)
- Unnecessary questions count
- Assumption detection hits
- Token usage / latency from provider logs

Do not fabricate those scores. Baseline = builtins only; treatment = approved book-derived drafts.

## Known limits

- Concept extraction is still primarily heuristic; chapter-LLM synthesis is the next upgrade.
- Machine Learning Systems was **not** ingested (ND license + no PDF acquired).
- Drafts are **not** auto-activated — admin must approve after review.
