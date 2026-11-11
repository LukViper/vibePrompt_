"""Book-to-Skill draft generator — abstractions only; drafts until approved."""

from __future__ import annotations

import re
from typing import Any

from app.knowledge.models import KnowledgeConcept, KnowledgeKind
from app.knowledge.store import KnowledgeStore
from app.skills.models import (
    SkillModeBinding,
    SkillPackage,
    SkillPrinciple,
    SkillStatus,
    new_id,
    utcnow,
)
from app.skills.registry import SkillRegistry

KIND_PRIORITY = {
    KnowledgeKind.PRINCIPLE: 0,
    KnowledgeKind.FRAMEWORK: 1,
    KnowledgeKind.DECISION_RULE: 2,
    KnowledgeKind.QUESTION_PATTERN: 3,
    KnowledgeKind.TECHNIQUE: 4,
    KnowledgeKind.METHODOLOGY: 5,
    KnowledgeKind.CONCEPT: 6,
    KnowledgeKind.LIMITATION: 7,
    KnowledgeKind.EXAMPLE: 8,
    KnowledgeKind.APPLICATION: 9,
}

SLUG_MODE: dict[str, SkillModeBinding] = {
    "conversational_discovery": SkillModeBinding.CONVERSATIONAL,
    "customer_discovery": SkillModeBinding.CONVERSATIONAL,
    "product_discovery": SkillModeBinding.CONVERSATIONAL,
    "brainstorm": SkillModeBinding.BRAINSTORMING,
    "grill": SkillModeBinding.GRILL_REVIEW,
    "technical_architecture": SkillModeBinding.ARCHITECTURE,
    "prompt_engineering": SkillModeBinding.PROMPT_ENGINEERING,
    "project_planning": SkillModeBinding.PROJECT_PLANNING,
}


def generate_skill_draft(
    store: KnowledgeStore,
    registry: SkillRegistry,
    *,
    book_ids: list[str],
    target_skill_id: str | None = None,
    target_slug: str | None = None,
    name: str | None = None,
    mode_binding: SkillModeBinding | None = None,
    actor: str | None = None,
) -> SkillPackage:
    if not book_ids:
        raise ValueError("At least one book_id is required")

    concepts: list[KnowledgeConcept] = []
    for bid in book_ids:
        book = store.get_book(bid)
        if book is None:
            raise ValueError(f"Book not found: {bid}")
        if book.status.value != "ready":
            raise ValueError(f"Book {bid} is not processed (status={book.status.value})")
        concepts.extend(store.list_concepts(bid))

    concepts = _dedupe_concepts(concepts)
    parent: SkillPackage | None = None
    if target_skill_id:
        parent = registry.get(target_skill_id)
    elif target_slug:
        parent = registry.get_by_slug(target_slug)

    slug = target_slug or (parent.slug if parent else None)
    if not slug:
        # Derive from first book's target skill or title
        first = store.get_book(book_ids[0])
        slug = (first.target_skill if first and first.target_skill else None) or _slugify(
            name or (first.title if first else "generated_skill")
        )

    mode = mode_binding or (parent.mode_binding if parent else None) or SLUG_MODE.get(slug)
    draft_name = name or (parent.name if parent else None) or slug.replace("_", " ").title()

    principles = _concepts_to_principles(concepts)
    if parent:
        # Preserve working behaviour: keep parent principles not superseded by title
        existing_titles = {p.title.lower() for p in principles}
        for p in parent.principles:
            if p.title.lower() not in existing_titles:
                principles.append(p.model_copy(deep=True))

    frameworks = sorted(
        {
            c.title
            for c in concepts
            if c.kind in {KnowledgeKind.FRAMEWORK, KnowledgeKind.METHODOLOGY}
        }
    )
    if parent:
        frameworks = list(dict.fromkeys([*parent.frameworks, *frameworks]))

    questions = [
        c.summary.replace("Abstracted takeaway: ", "")
        for c in concepts
        if c.kind == KnowledgeKind.QUESTION_PATTERN
    ][:20]
    if parent:
        questions = list(dict.fromkeys([*parent.question_patterns, *questions]))

    decision_rules = [
        c.summary.replace("Abstracted takeaway: ", "")
        for c in concepts
        if c.kind == KnowledgeKind.DECISION_RULE
    ][:20]
    if parent:
        decision_rules = list(dict.fromkeys([*parent.decision_rules, *decision_rules]))

    examples = _build_examples(principles, questions)
    evaluation_cases = _build_eval_cases(slug, principles)

    draft = SkillPackage(
        id=new_id("draft_"),
        slug=slug,
        name=draft_name,
        description=(
            parent.description
            if parent
            else f"Draft skill generated from {len(book_ids)} knowledge source(s)."
        ),
        status=SkillStatus.DRAFT,
        mode_binding=mode,
        version=(parent.version + 1) if parent else 1,
        principles=principles[:40],
        frameworks=frameworks[:30],
        question_patterns=questions,
        decision_rules=decision_rules,
        examples=examples,
        evaluation_cases=evaluation_cases,
        source_book_ids=list(dict.fromkeys([*(parent.source_book_ids if parent else []), *book_ids])),
        parent_skill_id=parent.id if parent else None,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    registry.save(draft)
    store.audit(
        "generate_skill_draft",
        actor=actor,
        entity_type="skill",
        entity_id=draft.id,
        detail={"slug": slug, "book_ids": book_ids, "parent": parent.id if parent else None},
    )

    # Link books → draft skill
    for bid in book_ids:
        book = store.get_book(bid)
        if book and draft.id not in book.associated_skill_ids:
            book.associated_skill_ids = [*book.associated_skill_ids, draft.id]
            store.update_book(book)
    return draft


def approve_skill(
    store: KnowledgeStore,
    registry: SkillRegistry,
    skill_id: str,
    *,
    actor: str | None = None,
    note: str | None = None,
) -> SkillPackage:
    skill = registry.get(skill_id)
    if skill is None:
        raise ValueError("Skill not found")
    if skill.status not in {SkillStatus.DRAFT, SkillStatus.DISABLED}:
        raise ValueError(f"Cannot approve skill in status {skill.status.value}")

    # If improving an existing slug, disable previous active non-builtin
    previous = registry.get_by_slug(skill.slug)
    if previous and previous.id != skill.id and previous.status == SkillStatus.ACTIVE:
        previous.status = SkillStatus.DISABLED
        registry.save(previous)

    skill.status = SkillStatus.ACTIVE
    skill.approved_at = utcnow()
    skill.approved_by = actor
    registry.save(skill)
    store.audit(
        "approve_skill",
        actor=actor,
        entity_type="skill",
        entity_id=skill.id,
        detail={"note": note, "version": skill.version},
    )
    return skill


def reject_skill(
    store: KnowledgeStore,
    registry: SkillRegistry,
    skill_id: str,
    *,
    actor: str | None = None,
    note: str | None = None,
) -> SkillPackage:
    skill = registry.get(skill_id)
    if skill is None:
        raise ValueError("Skill not found")
    skill.status = SkillStatus.ARCHIVED
    registry.save(skill)
    store.audit(
        "reject_skill",
        actor=actor,
        entity_type="skill",
        entity_id=skill.id,
        detail={"note": note},
    )
    return skill


def rollback_skill(
    store: KnowledgeStore,
    registry: SkillRegistry,
    skill_id: str,
    version: int,
    *,
    actor: str | None = None,
    note: str | None = None,
) -> SkillPackage:
    pkg = store.get_skill_version(skill_id, version)
    if pkg is None:
        raise ValueError("Version not found")
    # Create a new active version from historical package (never silent overwrite)
    current = registry.get(skill_id) or registry.get_by_slug(pkg.slug)
    restored = pkg.model_copy(deep=True)
    restored.id = new_id("skl_")
    restored.status = SkillStatus.ACTIVE
    restored.version = (current.version + 1) if current else pkg.version + 1
    restored.parent_skill_id = current.id if current else pkg.id
    restored.approved_at = utcnow()
    restored.approved_by = actor
    if current and current.status == SkillStatus.ACTIVE:
        current.status = SkillStatus.DISABLED
        registry.save(current)
    registry.save(restored)
    store.audit(
        "rollback_skill",
        actor=actor,
        entity_type="skill",
        entity_id=restored.id,
        detail={"from_version": version, "note": note, "slug": restored.slug},
    )
    return restored


def _concepts_to_principles(concepts: list[KnowledgeConcept]) -> list[SkillPrinciple]:
    ordered = sorted(concepts, key=lambda c: (KIND_PRIORITY.get(c.kind, 99), -c.confidence))
    out: list[SkillPrinciple] = []
    for c in ordered:
        if c.kind in {KnowledgeKind.EXAMPLE}:
            continue
        out.append(
            SkillPrinciple(
                title=c.title,
                summary=c.summary.replace("Abstracted takeaway: ", ""),
                application=c.application or c.summary,
                when_to_use=f"When working in skill context ({c.target_skill or 'general'})",
                when_not_to_use="When the user request is outside this skill's domain",
                source_book_id=c.book_id,
                chapter_ref=c.chapter_ref,
                original_concept=c.title,
                confidence=c.confidence,
            )
        )
    return out


def _dedupe_concepts(concepts: list[KnowledgeConcept]) -> list[KnowledgeConcept]:
    seen: set[str] = set()
    out: list[KnowledgeConcept] = []
    for c in concepts:
        key = re.sub(r"\W+", "", c.title.lower())[:48]
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:60] or "generated_skill"


def _build_examples(principles: list[SkillPrinciple], questions: list[str]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    if principles:
        examples.append(
            {
                "type": "positive",
                "input": "User shares a vague project idea",
                "behaviour": principles[0].summary,
            }
        )
        examples.append(
            {
                "type": "negative",
                "input": "User already provided the answer",
                "behaviour": "Do not repeat the same question or principle lecturing.",
            }
        )
    if questions:
        examples.append(
            {
                "type": "positive",
                "input": "Discovery turn",
                "behaviour": f"Prefer a behaviour-based question such as: {questions[0][:160]}",
            }
        )
    return examples


def _build_eval_cases(slug: str, principles: list[SkillPrinciple]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{slug}_relevance",
            "metric": "principle_relevance",
            "prompt": "Does the skill apply domain-appropriate principles?",
            "expect": "principles_used_when_relevant",
            "principle_count": len(principles),
        },
        {
            "id": f"{slug}_no_regression_tone",
            "metric": "behaviour_regression",
            "prompt": "Skill must not become longer/more verbose as a proxy for quality.",
            "expect": "no_verbosity_as_quality",
        },
        {
            "id": f"{slug}_attribution",
            "metric": "source_attribution",
            "prompt": "Retrieved principles should retain source book ids when present.",
            "expect": "source_book_id_present",
        },
    ]
