"""Dynamic skill orchestration — select relevant skills without loading entire books."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.grill.modes import BehaviouralMode
from app.knowledge.store import KnowledgeStore
from app.skills.models import SkillPackage, SkillStatus
from app.skills.registry import SkillRegistry
from app.skills.retrieval import format_retrieval_block, retrieve_for_mode
from app.skills.builtin import MODE_SKILL_SLUGS

# Keyword cues → skill slugs (additive to mode defaults)
SKILL_CUES: list[tuple[str, re.Pattern[str]]] = [
    (
        "conversational_discovery",
        re.compile(
            r"\b(discover|requirements?|what (do|should) i build|help me figure|"
            r"interview|user need|clarify)\b",
            re.I,
        ),
    ),
    (
        "customer_discovery",
        re.compile(r"\b(customer|user interview|mom test|validation interview)\b", re.I),
    ),
    (
        "product_discovery",
        re.compile(r"\b(opportunity|product discovery|outcome|problem space)\b", re.I),
    ),
    (
        "brainstorm",
        re.compile(r"\b(brainstorm|ideas?|alternatives|reframe|creative)\b", re.I),
    ),
    (
        "grill",
        re.compile(
            r"\b(grill|critique|challenge|risk|assumption|weak|stress[- ]test|"
            r"is this (a )?good (idea|plan|architecture))\b",
            re.I,
        ),
    ),
    (
        "prompt_engineering",
        re.compile(
            r"\b(prompt|system prompt|write (a |the )?prompt|coding agent prompt|"
            r"agent instructions)\b",
            re.I,
        ),
    ),
    (
        "prompt_evaluator",
        re.compile(
            r"\b(evaluat(e|ion)|review (this |my )?prompt|acceptance criteria|"
            r"ambiguous prompt|test the prompt)\b",
            re.I,
        ),
    ),
    (
        "technical_architecture",
        re.compile(
            r"\b(architect(ure)?|tech stack|scalability|microservices?|"
            r"system design|trade-?offs?)\b",
            re.I,
        ),
    ),
    (
        "agent_engineering",
        re.compile(
            r"\b(agent loop|tool(s)?|mcp|permissions|coding agent|agentic|"
            r"verification (loop|strateg))\b",
            re.I,
        ),
    ),
    (
        "project_planning",
        re.compile(
            r"\b(plan|roadmap|milestone|mvp|backlog|user stor(y|ies)|"
            r"feature breakdown|implementation (plan|tasks))\b",
            re.I,
        ),
    ),
    (
        "grill",
        re.compile(
            r"\b(security|threat|auth(entication|orization)?|cyber|"
            r"risk assessment|secure by design)\b",
            re.I,
        ),
    ),
    (
        "technical_architecture",
        re.compile(
            r"\b(nlp|llm|embedding|pipeline|data model|microservice|"
            r"event[- ]driven|fastapi|sqlite)\b",
            re.I,
        ),
    ),
    (
        "prompt_evaluator",
        re.compile(
            r"\b(test(ing)?|validation|acceptance criteria|qa|"
            r"quality check|regression)\b",
            re.I,
        ),
    ),
]


# Soft dependencies: if a skill is selected, prefer prerequisites when room remains.
# Not hardcoded domain combos — only direct prerequisite edges.
SKILL_DEPENDENCIES: dict[str, list[str]] = {
    "prompt_evaluator": ["prompt_engineering"],
    "agent_engineering": ["prompt_engineering"],
}


@dataclass
class OrchestrationPlan:
    mode: str
    selected_slugs: list[str]
    reasons: dict[str, str] = field(default_factory=dict)
    prompt_block: str = ""
    principles: list[dict[str, Any]] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


def _expand_skill_dependencies(
    ordered: list[str],
    reasons: dict[str, str],
    *,
    max_skills: int,
) -> tuple[list[str], dict[str, str]]:
    """
    Ensure prerequisites appear before dependents without displacing
    user_selected / message_cue skills when trimming to max_skills.
    """
    out_reasons = dict(reasons)
    expanded: list[str] = []

    for slug in ordered:
        for dep in SKILL_DEPENDENCIES.get(slug, []):
            if dep not in expanded:
                # Insert immediately before dependent when possible
                expanded.append(dep)
                out_reasons.setdefault(dep, f"dependency_of:{slug}")
        if slug not in expanded:
            expanded.append(slug)

    if len(expanded) <= max_skills:
        return expanded, {k: out_reasons[k] for k in expanded}

    # Trim: never drop user_selected / message_cue; drop mode_default then deps last
    def _priority(slug: str) -> int:
        r = out_reasons.get(slug, "")
        if r == "user_selected":
            return 0
        if r == "message_cue":
            return 1
        if r.startswith("dependency_of:"):
            return 3
        if r.startswith("mode_default"):
            return 2
        return 2

    # Stable sort by priority, then original order
    indexed = list(enumerate(expanded))
    indexed.sort(key=lambda pair: (_priority(pair[1]), pair[0]))
    keep: list[str] = []
    for _i, slug in indexed:
        if len(keep) >= max_skills:
            break
        keep.append(slug)
    # Restore relative order from expanded
    keep_set = set(keep)
    trimmed = [s for s in expanded if s in keep_set][:max_skills]
    # If a kept dependent lost its prerequisite, try to swap in the dep
    for slug in list(trimmed):
        for dep in SKILL_DEPENDENCIES.get(slug, []):
            if dep in trimmed:
                continue
            # Replace a mode_default slot if present
            for i, cand in enumerate(trimmed):
                if out_reasons.get(cand, "").startswith("mode_default"):
                    trimmed[i] = dep
                    out_reasons.setdefault(dep, f"dependency_of:{slug}")
                    break
    # Final order: prerequisites before dependents among trimmed
    final: list[str] = []
    for slug in trimmed:
        for dep in SKILL_DEPENDENCIES.get(slug, []):
            if dep in trimmed and dep not in final:
                final.append(dep)
        if slug not in final:
            final.append(slug)
    return final[:max_skills], {k: out_reasons[k] for k in final[:max_skills]}


def select_skill_slugs(
    *,
    mode: BehaviouralMode | str,
    user_message: str,
    user_selected: list[str] | None = None,
    max_skills: int = 4,
) -> OrchestrationPlan:
    mode_value = mode.value if isinstance(mode, BehaviouralMode) else str(mode)
    reasons: dict[str, str] = {}
    ordered: list[str] = []

    def _add(slug: str, reason: str) -> None:
        if slug in reasons:
            return
        reasons[slug] = reason
        ordered.append(slug)

    for slug in user_selected or []:
        if slug.strip():
            _add(slug.strip(), "user_selected")

    for slug in MODE_SKILL_SLUGS.get(mode_value, []):
        _add(slug, f"mode_default:{mode_value}")

    for slug, pattern in SKILL_CUES:
        if pattern.search(user_message or ""):
            _add(slug, "message_cue")

    # Soft de-prioritize: in explore/chat, don't force grill unless cued
    explore_like = mode_value in {
        BehaviouralMode.CONVERSATIONAL.value,
        BehaviouralMode.EXPLORE.value,
        "explore",
        "conversational",
    }
    if explore_like and "grill" in ordered:
        if reasons.get("grill") == "message_cue":
            pass
        elif reasons.get("grill", "").startswith("mode_default"):
            ordered = [s for s in ordered if s != "grill"]
            reasons.pop("grill", None)

    ordered, reasons = _expand_skill_dependencies(
        ordered, reasons, max_skills=max_skills
    )

    return OrchestrationPlan(
        mode=mode_value,
        selected_slugs=ordered,
        reasons=reasons,
    )


def build_orchestration_context(
    registry: SkillRegistry,
    store: KnowledgeStore,
    *,
    mode: BehaviouralMode | str,
    user_message: str,
    user_selected: list[str] | None = None,
    max_principles: int = 8,
) -> OrchestrationPlan:
    plan = select_skill_slugs(
        mode=mode, user_message=user_message, user_selected=user_selected
    )

    # Prefer multi-skill ranked retrieval when we have an explicit selection set
    packages: list[SkillPackage] = []
    for slug in plan.selected_slugs:
        skill = registry.get_by_slug(slug)
        if skill and skill.status in {SkillStatus.ACTIVE, SkillStatus.BUILTIN, SkillStatus.DRAFT}:
            # drafts are not injected into production chat
            if skill.status == SkillStatus.DRAFT:
                continue
            packages.append(skill)

    if not packages:
        # Fall back to mode retrieval
        result = retrieve_for_mode(
            registry, store, mode=plan.mode, user_message=user_message
        )
        plan.prompt_block = result.get("prompt_block") or ""
        plan.principles = result.get("principles") or []
        plan.skills = result.get("skills") or []
        return plan

    # Rank principles across selected skills only
    from app.skills.retrieval import _score  # local helper

    tokens = set(re.findall(r"[a-z0-9]{3,}", (user_message or "").lower()))
    ranked: list[tuple[float, Any, str]] = []
    for skill in packages:
        for principle in skill.principles:
            ranked.append((_score(principle, tokens, skill), principle, skill.slug))
        for concept in store.list_concepts(
            target_skill=skill.slug, enabled_books_only=True
        )[:12]:
            from app.skills.models import SkillPrinciple

            faux = SkillPrinciple(
                title=concept.title,
                summary=concept.summary.replace("Abstracted takeaway: ", ""),
                application=concept.application,
                source_book_id=concept.book_id,
                chapter_ref=concept.chapter_ref,
                confidence=concept.confidence,
            )
            ranked.append((_score(faux, tokens, skill) * 0.9, faux, skill.slug))

    ranked.sort(key=lambda x: x[0], reverse=True)
    selected: list[tuple[Any, str]] = []
    seen: set[str] = set()
    for _sc, principle, slug in ranked:
        key = re.sub(r"\W+", "", principle.title.lower())[:40]
        if key in seen:
            continue
        seen.add(key)
        selected.append((principle, slug))
        if len(selected) >= max_principles:
            break

    header_bits = [
        f"{slug} ({plan.reasons.get(slug, 'selected')})" for slug in plan.selected_slugs
    ]
    activation = (
        "SKILL_ORCHESTRATION (trusted): active skills = "
        + ", ".join(header_bits)
        + ". Follow higher-priority skill rules when instructions conflict; "
        "prefer discovery before critique unless Grill is explicitly active."
    )
    block = format_retrieval_block(selected)
    plan.prompt_block = (activation + ("\n" + block if block else "")).strip()
    plan.principles = [
        {
            "title": p.title,
            "summary": p.summary,
            "skill": slug,
            "source_book_id": p.source_book_id,
            "chapter_ref": p.chapter_ref,
            "confidence": p.confidence,
        }
        for p, slug in selected
    ]
    plan.skills = [s.slug for s in packages]

    # Best-effort activation log
    try:
        store.audit(
            "skill_activation",
            actor=None,
            entity_type="orchestration",
            entity_id=plan.mode,
            detail={
                "slugs": plan.selected_slugs,
                "reasons": plan.reasons,
                "principle_count": len(plan.principles),
            },
        )
    except Exception:
        pass

    return plan
