"""Lightweight skill evaluation — before/after knowledge integration."""

from __future__ import annotations

from typing import Any

from app.knowledge.store import KnowledgeStore
from app.skills.models import SkillPackage
from app.skills.registry import SkillRegistry
from app.skills.retrieval import retrieve_for_mode


BASELINE_PROMPTS: dict[str, list[dict[str, str]]] = {
    "conversational": [
        {"id": "cd1", "message": "I want to build an app for freelancers to track invoices."},
        {"id": "cd2", "message": "The users are freelancers. What should I ask next?"},
    ],
    "brainstorming": [
        {"id": "br1", "message": "Brainstorm alternative approaches for a meal-planning assistant."},
    ],
    "grill_review": [
        {"id": "gr1", "message": "Grill this: we'll use microservices and blockchain for a todo app."},
    ],
}


def evaluate_skill(
    registry: SkillRegistry,
    store: KnowledgeStore,
    skill: SkillPackage,
    *,
    baseline: SkillPackage | None = None,
) -> dict[str, Any]:
    mode = skill.mode_binding.value if skill.mode_binding else "conversational"
    # Map architecture/etc. to conversational for retrieval test harness
    retrieval_mode = mode if mode in BASELINE_PROMPTS else "conversational"

    metrics: dict[str, Any] = {
        "principle_count": len(skill.principles),
        "framework_count": len(skill.frameworks),
        "question_pattern_count": len(skill.question_patterns),
        "source_book_count": len(skill.source_book_ids),
        "has_evaluation_cases": len(skill.evaluation_cases) > 0,
        "understandable_instructions": _instructions_ok(skill),
        "source_attribution_rate": _attribution_rate(skill),
        "duplicate_principle_rate": _duplicate_rate(skill),
    }

    retrieval_checks = []
    for case in BASELINE_PROMPTS.get(retrieval_mode, []):
        result = retrieve_for_mode(
            registry, store, mode=retrieval_mode, user_message=case["message"]
        )
        retrieval_checks.append(
            {
                "case_id": case["id"],
                "retrieved": len(result["principles"]),
                "includes_skill": skill.slug in result["skills"],
                "block_chars": len(result["prompt_block"]),
            }
        )
    metrics["retrieval_checks"] = retrieval_checks
    metrics["retrieval_selects_knowledge"] = all(
        c["retrieved"] > 0 for c in retrieval_checks
    ) if retrieval_checks else True

    if baseline:
        metrics["delta_principle_count"] = len(skill.principles) - len(baseline.principles)
        metrics["verbosity_proxy_ok"] = len(skill.principles) <= len(baseline.principles) + 25
        metrics["baseline_version"] = baseline.version
    else:
        metrics["verbosity_proxy_ok"] = True

    contradictions = _find_conflicts(skill)
    metrics["contradiction_count"] = len(contradictions)
    metrics["contradictions"] = contradictions[:5]

    passed = (
        metrics["understandable_instructions"]
        and metrics["duplicate_principle_rate"] < 0.25
        and metrics["contradiction_count"] == 0
        and metrics["verbosity_proxy_ok"]
        and metrics["retrieval_selects_knowledge"]
    )

    record = {
        "skill_id": skill.id,
        "version": skill.version,
        "baseline_skill_id": baseline.id if baseline else None,
        "metrics": metrics,
        "passed": passed,
        "notes": "Automated structural evaluation; human review still required.",
    }
    store.save_evaluation(record)
    return record


def _instructions_ok(skill: SkillPackage) -> bool:
    if not skill.name or not skill.description:
        return False
    if not skill.principles:
        return False
    return all(len(p.summary) >= 20 for p in skill.principles[:5])


def _attribution_rate(skill: SkillPackage) -> float:
    if not skill.principles:
        return 1.0
    with_src = sum(1 for p in skill.principles if p.source_book_id)
    # Builtins may have no sources — not a failure
    if not skill.source_book_ids:
        return 1.0
    return with_src / len(skill.principles)


def _duplicate_rate(skill: SkillPackage) -> float:
    titles = [p.title.lower().strip() for p in skill.principles]
    if not titles:
        return 0.0
    return 1.0 - (len(set(titles)) / len(titles))


def _find_conflicts(skill: SkillPackage) -> list[str]:
    conflicts: list[str] = []
    texts = [(p.title, p.summary.lower()) for p in skill.principles]
    for i, (t1, s1) in enumerate(texts):
        for t2, s2 in texts[i + 1 :]:
            if ("always " in s1 and "never " in s2) or ("never " in s1 and "always " in s2):
                if any(w in s1 and w in s2 for w in ("ask", "disagree", "suggest", "challenge")):
                    conflicts.append(f"Possible conflict between '{t1}' and '{t2}'")
    return conflicts
