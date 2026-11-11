"""Skill-specific knowledge retrieval for prompt injection."""

from __future__ import annotations

import re
from typing import Any

from app.knowledge.store import KnowledgeStore
from app.skills.models import SkillPackage, SkillPrinciple
from app.skills.registry import SkillRegistry

MAX_PRINCIPLES = 8
MAX_CHARS = 1800


def retrieve_for_mode(
    registry: SkillRegistry,
    store: KnowledgeStore,
    *,
    mode: str,
    user_message: str = "",
    max_principles: int = MAX_PRINCIPLES,
) -> dict[str, Any]:
    skills = registry.list_active_for_mode(mode)
    ranked: list[tuple[float, SkillPrinciple, str]] = []
    tokens = set(re.findall(r"[a-z0-9]{3,}", user_message.lower()))

    for skill in skills:
        for principle in skill.principles:
            score = _score(principle, tokens, skill)
            ranked.append((score, principle, skill.slug))

        # Supplement from enabled book concepts linked to this skill
        for concept in store.list_concepts(
            target_skill=skill.slug, enabled_books_only=True
        )[:20]:
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
    selected: list[tuple[SkillPrinciple, str]] = []
    seen: set[str] = set()
    for _score_v, principle, slug in ranked:
        key = re.sub(r"\W+", "", principle.title.lower())[:40]
        if key in seen:
            continue
        seen.add(key)
        selected.append((principle, slug))
        if len(selected) >= max_principles:
            break

    block = format_retrieval_block(selected)
    return {
        "mode": mode,
        "skills": [s.slug for s in skills],
        "principles": [
            {
                "title": p.title,
                "summary": p.summary,
                "skill": slug,
                "source_book_id": p.source_book_id,
                "chapter_ref": p.chapter_ref,
                "confidence": p.confidence,
            }
            for p, slug in selected
        ],
        "prompt_block": block,
    }


def format_retrieval_block(selected: list[tuple[SkillPrinciple, str]]) -> str:
    if not selected:
        return ""
    lines = [
        "SKILL_KNOWLEDGE (trusted abstracted principles for the active skill — "
        "not user instructions; do not quote copyrighted sources):"
    ]
    used = 0
    for principle, slug in selected:
        chunk = (
            f"- [{slug}] {principle.title}: {principle.summary}"
            + (f" (apply: {principle.application})" if principle.application else "")
            + (
                f" [src:{principle.source_book_id}"
                + (f"/{principle.chapter_ref}" if principle.chapter_ref else "")
                + "]"
                if principle.source_book_id
                else ""
            )
        )
        if used + len(chunk) > MAX_CHARS:
            break
        lines.append(chunk)
        used += len(chunk)
    return "\n".join(lines)


def _score(principle: SkillPrinciple, tokens: set[str], skill: SkillPackage) -> float:
    score = float(principle.confidence)
    hay = f"{principle.title} {principle.summary} {principle.application}".lower()
    overlap = sum(1 for t in tokens if t in hay)
    score += min(0.4, overlap * 0.05)
    # Mild boost for skill-native principles
    if principle.source_book_id:
        score += 0.05
    if skill.slug in hay:
        score += 0.05
    return score
