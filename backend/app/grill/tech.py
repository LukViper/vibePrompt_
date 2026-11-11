"""Structured technology decisions, canonicalization, and category conflicts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _new_id() -> str:
    return f"tech_{uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Categories for primary selections (one active primary per category unless role differs)
TECH_CATEGORIES = (
    "frontend",
    "backend",
    "database",
    "cache",
    "ai_ml",
    "infrastructure",
    "deployment",
    "other",
)

# Known technologies → (canonical name, category). Do not invent beyond this map.
_TECH_CANON: dict[str, tuple[str, str]] = {
    # Frontend
    "react": ("React", "frontend"),
    "react.js": ("React", "frontend"),
    "reactjs": ("React", "frontend"),
    "vue": ("Vue", "frontend"),
    "vue.js": ("Vue", "frontend"),
    "angular": ("Angular", "frontend"),
    "svelte": ("Svelte", "frontend"),
    "next.js": ("Next.js", "frontend"),
    "nextjs": ("Next.js", "frontend"),
    "streamlit": ("Streamlit", "frontend"),
    # Backend
    "python": ("Python", "backend"),
    "fastapi": ("FastAPI", "backend"),
    "flask": ("Flask", "backend"),
    "django": ("Django", "backend"),
    "node": ("Node.js", "backend"),
    "nodejs": ("Node.js", "backend"),
    "node.js": ("Node.js", "backend"),
    "express": ("Express", "backend"),
    "express.js": ("Express", "backend"),
    "nestjs": ("NestJS", "backend"),
    "go": ("Go", "backend"),
    "golang": ("Go", "backend"),
    "rust": ("Rust", "backend"),
    "java": ("Java", "backend"),
    "spring": ("Spring", "backend"),
    "ruby": ("Ruby", "backend"),
    "rails": ("Rails", "backend"),
    # Database
    "postgresql": ("PostgreSQL", "database"),
    "postgres": ("PostgreSQL", "database"),
    "sqlite": ("SQLite", "database"),
    "mysql": ("MySQL", "database"),
    "mongodb": ("MongoDB", "database"),
    "mongo": ("MongoDB", "database"),
    "dynamodb": ("DynamoDB", "database"),
    "cassandra": ("Cassandra", "database"),
    # Cache (coexists with primary DB)
    "redis": ("Redis", "cache"),
    "memcached": ("Memcached", "cache"),
    # AI/ML
    "pytorch": ("PyTorch", "ai_ml"),
    "tensorflow": ("TensorFlow", "ai_ml"),
    "scikit-learn": ("scikit-learn", "ai_ml"),
    "sklearn": ("scikit-learn", "ai_ml"),
    "huggingface": ("Hugging Face", "ai_ml"),
    "openai": ("OpenAI API", "ai_ml"),
    # Infrastructure / search / streaming
    "elasticsearch": ("Elasticsearch", "infrastructure"),
    "elastic": ("Elasticsearch", "infrastructure"),
    "opensearch": ("OpenSearch", "infrastructure"),
    "kafka": ("Kafka", "infrastructure"),
    "rabbitmq": ("RabbitMQ", "infrastructure"),
    "kubernetes": ("Kubernetes", "infrastructure"),
    "k8s": ("Kubernetes", "infrastructure"),
    "docker": ("Docker", "infrastructure"),
    # Deployment
    "aws": ("AWS", "deployment"),
    "gcp": ("GCP", "deployment"),
    "azure": ("Azure", "deployment"),
    "vercel": ("Vercel", "deployment"),
    "heroku": ("Heroku", "deployment"),
    "fly.io": ("Fly.io", "deployment"),
}

# Backend frameworks that are mutually exclusive as the *primary* API framework
_BACKEND_FRAMEWORKS = {
    "FastAPI",
    "Flask",
    "Django",
    "Express",
    "NestJS",
    "Spring",
    "Rails",
}
# Languages that often co-specify with frameworks (Python+FastAPI OK; Node.js+Express OK)
_BACKEND_LANGUAGES = {"Python", "Node.js", "Go", "Rust", "Java", "Ruby"}

_AMBIGUOUS_SPLIT = re.compile(
    r"\s+(?:or|/|,|\||versus|vs\.?)\s+",
    re.I,
)


class TechnologySelection(BaseModel):
    id: str = Field(default_factory=_new_id)
    category: str
    selected: str
    alternatives: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    status: str = "accepted"  # accepted | provisional | superseded | unverified
    reason: str = ""
    role: str = "primary"  # primary | secondary | supporting
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


@dataclass
class TechParseResult:
    canonical: str | None
    category: str | None
    raw: str
    ambiguous: bool = False
    alternatives: list[str] | None = None
    error: str | None = None


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9.+]+", "", (value or "").strip().lower())


def parse_technology_token(raw: str) -> TechParseResult:
    """
    Normalize a single technology token.
    Ambiguous multi-option strings become alternatives proposals, not selections.
    """
    text = (raw or "").strip()
    if not text:
        return TechParseResult(None, None, raw, error="empty")

    # Reject free-form sentences / polluted tokens
    if len(text) > 40 or "\n" in text:
        return TechParseResult(None, None, text, error="malformed")

    # "MongoDB or SQLite" / "MongoDB/SQLite"
    parts = [p.strip() for p in _AMBIGUOUS_SPLIT.split(text) if p.strip()]
    if len(parts) > 1:
        resolved: list[str] = []
        for p in parts:
            key = normalize_key(p)
            if key in _TECH_CANON:
                resolved.append(_TECH_CANON[key][0])
            else:
                resolved.append(p)
        return TechParseResult(
            canonical=None,
            category=None,
            raw=text,
            ambiguous=True,
            alternatives=resolved,
            error="ambiguous_or_choice",
        )

    key = normalize_key(text)
    if key in _TECH_CANON:
        canon, cat = _TECH_CANON[key]
        return TechParseResult(canon, cat, text)

    # Unknown single token — keep as unverified proposal, category other
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9.+_-]{0,39}", text):
        return TechParseResult(text, "other", text, error="unverified")

    return TechParseResult(None, None, text, error="malformed")


def active_selections(selections: list[TechnologySelection]) -> list[TechnologySelection]:
    return [s for s in selections if s.status in {"accepted", "provisional"}]


def stack_from_selections(selections: list[TechnologySelection]) -> list[str]:
    """Derived flat tech_stack for backward-compatible consumers."""
    out: list[str] = []
    for s in active_selections(selections):
        if s.selected and s.selected not in out:
            out.append(s.selected)
    return out


def _framework_conflict(existing: str, incoming: str, category: str) -> bool:
    if category != "backend":
        return existing != incoming and category == "database"
    # Same category backend: languages can coexist with their frameworks
    if existing in _BACKEND_LANGUAGES and incoming in _BACKEND_FRAMEWORKS:
        return False
    if incoming in _BACKEND_LANGUAGES and existing in _BACKEND_FRAMEWORKS:
        return False
    if existing in _BACKEND_LANGUAGES and incoming in _BACKEND_LANGUAGES:
        return existing != incoming
    if existing in _BACKEND_FRAMEWORKS and incoming in _BACKEND_FRAMEWORKS:
        return existing != incoming
    # Node.js language vs Python language
    if {existing, incoming} <= (_BACKEND_LANGUAGES | _BACKEND_FRAMEWORKS):
        # Express conflicts with FastAPI
        if existing in _BACKEND_FRAMEWORKS and incoming in _BACKEND_FRAMEWORKS:
            return existing != incoming
        lang_pair = {existing, incoming}
        if "Python" in lang_pair and "Node.js" in lang_pair:
            return True
        # Node.js + FastAPI conflict (different ecosystems)
        if ("Node.js" in lang_pair or existing == "Express" or incoming == "Express") and (
            "FastAPI" in lang_pair or "Flask" in lang_pair or "Django" in lang_pair
        ):
            return True
        if ("Python" in lang_pair) and (
            incoming in {"Express", "NestJS"} or existing in {"Express", "NestJS"}
        ):
            return True
    return existing != incoming and category not in {"infrastructure", "deployment", "cache", "other"}


def conflicts_with_selection(
    selections: list[TechnologySelection],
    *,
    canonical: str,
    category: str,
    role: str = "primary",
) -> TechnologySelection | None:
    """Return the existing active selection that conflicts, if any."""
    for s in active_selections(selections):
        if s.selected == canonical:
            return None
        if s.category != category:
            continue
        # Same category: allow multiple if roles differ and both non-primary
        if role != "primary" and s.role != "primary":
            continue
        if category == "database" and s.role == "primary" and role == "primary":
            if s.selected != canonical:
                return s
        if category == "frontend" and s.role == "primary" and role == "primary":
            if s.selected != canonical:
                return s
        if category == "backend":
            if _framework_conflict(s.selected, canonical, category):
                return s
        elif category not in {"infrastructure", "deployment", "cache", "ai_ml", "other"}:
            if s.selected != canonical and s.role == "primary" and role == "primary":
                return s
    return None


def apply_technology_tokens(
    selections: list[TechnologySelection],
    tokens: list[str],
    *,
    reason: str = "",
    explicit_replace: bool = False,
    as_alternatives: bool = False,
    rejected_names: list[str] | None = None,
) -> tuple[list[TechnologySelection], list[str], list[str], list[str]]:
    """
    Apply technology tokens to structured selections.

    Returns (selections, applied, contradictions, deferred_alternatives/unverified).
    """
    applied: list[str] = []
    contradictions: list[str] = []
    deferred: list[str] = []
    working = list(selections)
    rejected_norm = {(r or "").strip().lower() for r in (rejected_names or []) if r}

    for token in tokens:
        parsed = parse_technology_token(token)
        if parsed.ambiguous and parsed.alternatives:
            deferred.append(
                f"Ambiguous technology proposal '{parsed.raw}' "
                f"(options: {', '.join(parsed.alternatives)}) — not selected"
            )
            # Record as provisional alternatives on a stub if category known from first option
            first = parse_technology_token(parsed.alternatives[0])
            if first.canonical and first.category:
                working.append(
                    TechnologySelection(
                        category=first.category,
                        selected="",
                        alternatives=list(parsed.alternatives),
                        status="unverified",
                        reason=f"Ambiguous LLM/user proposal: {parsed.raw}",
                        role="primary",
                    )
                )
            continue

        if parsed.error == "malformed" or not parsed.canonical or not parsed.category:
            deferred.append(f"Rejected malformed technology token: {parsed.raw!r}")
            continue

        # Previously rejected approaches cannot become selected without explicit replace
        rejected_hit = next(
            (
                rej
                for rej in rejected_norm
                if rej
                and (
                    rej == parsed.canonical.lower()
                    or rej in parsed.canonical.lower()
                    or parsed.canonical.lower() in rej
                )
            ),
            None,
        )
        if rejected_hit and not explicit_replace:
            contradictions.append(
                f"Proposed tech '{parsed.canonical}' overlaps previously rejected "
                f"approach '{rejected_hit}'."
            )
            continue

        if parsed.error == "unverified" or as_alternatives:
            deferred.append(f"Unverified technology proposal: {parsed.canonical}")
            working.append(
                TechnologySelection(
                    category=parsed.category,
                    selected=parsed.canonical,
                    status="unverified",
                    reason=reason or "Unverified / not in known catalog confirmation",
                    role="primary",
                )
            )
            continue

        conflict = conflicts_with_selection(
            working, canonical=parsed.canonical, category=parsed.category
        )
        if conflict and not explicit_replace:
            contradictions.append(
                f"Proposed {parsed.category} '{parsed.canonical}' conflicts with "
                f"selected '{conflict.selected}'."
            )
            # Keep as alternative on the existing selection
            if parsed.canonical not in conflict.alternatives:
                conflict.alternatives.append(parsed.canonical)
                conflict.updated_at = utcnow()
            continue

        if conflict and explicit_replace:
            conflict.status = "superseded"
            conflict.updated_at = utcnow()
            if conflict.selected and conflict.selected not in conflict.alternatives:
                conflict.alternatives.append(conflict.selected)

        # Upsert same tech
        existing_same = next(
            (
                s
                for s in active_selections(working)
                if s.selected == parsed.canonical and s.category == parsed.category
            ),
            None,
        )
        if existing_same:
            if reason and not existing_same.reason:
                existing_same.reason = reason
                existing_same.updated_at = utcnow()
            applied.append(parsed.canonical)
            continue

        working.append(
            TechnologySelection(
                category=parsed.category,
                selected=parsed.canonical,
                status="accepted",
                reason=reason,
                role="primary",
            )
        )
        applied.append(parsed.canonical)

    return working, applied, contradictions, deferred


def selections_to_public(selections: list[TechnologySelection]) -> list[dict[str, Any]]:
    return [s.model_dump(mode="json") for s in selections]


def hydrate_selections_from_legacy(
    *,
    selections: list[TechnologySelection],
    tech_stack: list[str],
    decisions: list[Any] | None = None,
) -> list[TechnologySelection]:
    """
    Bootstrap structured selections from flat tech_stack / decision choices
    when technology_selections is empty (older projects).
    """
    if selections:
        return list(selections)
    tokens: list[str] = list(tech_stack or [])
    for d in decisions or []:
        choice = getattr(d, "choice", None) or (d.get("choice") if isinstance(d, dict) else None)
        status = getattr(d, "status", None) or (d.get("status") if isinstance(d, dict) else "accepted")
        if not choice or status == "superseded":
            continue
        # Split "Python + FastAPI" style choices
        for part in re.split(r"\s*\+\s*|\s+and\s+", str(choice)):
            part = part.strip()
            if part:
                tokens.append(part)
    if not tokens:
        return []
    sels, _, _, _ = apply_technology_tokens([], tokens, reason="legacy hydrate")
    # Drop unverified empty-selected ambiguous stubs from hydrate
    return [s for s in sels if s.selected and s.status in {"accepted", "provisional", "unverified"}]
