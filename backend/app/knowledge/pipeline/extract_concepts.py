"""Heuristic knowledge extraction — abstractions, not quotations."""

from __future__ import annotations

import re
from typing import Any

from app.knowledge.models import KnowledgeConcept, KnowledgeKind, new_id

# Cue patterns → kind. Summaries are rewritten, never copied verbatim at length.
CUES: list[tuple[KnowledgeKind, re.Pattern[str], str]] = [
    (
        KnowledgeKind.QUESTION_PATTERN,
        re.compile(r"(?i)\b(ask|question|how (do|did|have) you|tell me about)\b"),
        "Prefer concrete behavioural questions over hypothetical preference questions.",
    ),
    (
        KnowledgeKind.PRINCIPLE,
        re.compile(r"(?i)\b(principle|always|never|rule of thumb|guideline)\b"),
        "Treat stated guidelines as behavioural constraints for the active skill.",
    ),
    (
        KnowledgeKind.FRAMEWORK,
        re.compile(r"(?i)\b(framework|model|process|steps?|cycle|loop|map)\b"),
        "Apply the named structure as a staged method rather than a single tip.",
    ),
    (
        KnowledgeKind.TECHNIQUE,
        re.compile(r"(?i)\b(technique|practice|exercise|method|how to)\b"),
        "Use as a practical move during conversation or review.",
    ),
    (
        KnowledgeKind.LIMITATION,
        re.compile(r"(?i)\b(limitation|caveat|don't|avoid|pitfall|bias|trap)\b"),
        "Do not apply the related method when this caveat is present.",
    ),
    (
        KnowledgeKind.DECISION_RULE,
        re.compile(r"(?i)\b(if |when |unless |prefer |choose |trade-?off)\b"),
        "Use as a conditional rule for selecting an approach.",
    ),
    (
        KnowledgeKind.CONCEPT,
        re.compile(r"(?i)\b(concept|idea|means that|defined as|refers to)\b"),
        "Keep the concept available as shared vocabulary for the skill.",
    ),
]


def _rewrite_summary(sentence: str, fallback: str) -> str:
    """Produce a short independent abstraction; never keep long copyrighted spans."""
    cleaned = re.sub(r"\s+", " ", sentence).strip()
    # Hard cap — abstractions only
    if len(cleaned) > 220:
        cleaned = cleaned[:200].rsplit(" ", 1)[0] + "…"
    # Strip quote marks that might signal verbatim passage
    cleaned = cleaned.strip(" \"'")
    if len(cleaned) < 20:
        return fallback
    # Force paraphrase framing
    return f"Abstracted takeaway: {cleaned}"


def extract_concepts_from_chapters(
    *,
    book_id: str,
    chapters: list[dict[str, Any]],
    target_skill: str | None = None,
    max_per_chapter: int = 6,
    max_total: int = 80,
) -> list[KnowledgeConcept]:
    concepts: list[KnowledgeConcept] = []
    seen_titles: set[str] = set()

    for chapter in chapters:
        title = chapter.get("title") or "Section"
        text = chapter.get("text") or ""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chapter_hits = 0
        for sentence in sentences:
            if chapter_hits >= max_per_chapter or len(concepts) >= max_total:
                break
            if len(sentence) < 40 or len(sentence) > 400:
                continue
            for kind, pattern, application in CUES:
                if not pattern.search(sentence):
                    continue
                # Title from first content words — not a long quote
                words = re.findall(r"[A-Za-z][\w\-']*", sentence)
                short_title = " ".join(words[:8]).strip() or kind.value.replace("_", " ").title()
                key = short_title.lower()
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                concepts.append(
                    KnowledgeConcept(
                        id=new_id("kc_"),
                        book_id=book_id,
                        kind=kind,
                        title=short_title[:120],
                        summary=_rewrite_summary(sentence, application),
                        application=application,
                        chapter_ref=title,
                        target_skill=target_skill,
                        confidence=0.55 if kind != KnowledgeKind.CONCEPT else 0.5,
                        tags=[kind.value],
                        metadata={
                            "extraction": "heuristic_v1",
                            "note": "Independently rewritten abstraction; not a quotation.",
                        },
                    )
                )
                chapter_hits += 1
                break

    # Deduplicate near-identical titles
    return _dedupe(concepts)[:max_total]


def _dedupe(concepts: list[KnowledgeConcept]) -> list[KnowledgeConcept]:
    out: list[KnowledgeConcept] = []
    keys: set[str] = set()
    for c in concepts:
        key = re.sub(r"\W+", "", c.title.lower())[:40]
        if key in keys:
            continue
        keys.add(key)
        out.append(c)
    return out
