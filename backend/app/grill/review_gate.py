"""Deterministic pre-critic REVIEW gate — fail closed on go-live contradictions.

Runs before (and independently of) LLM critic output. Detects stack conflicts,
rejected-option regressions, and artifact/manifest mismatches from the user
brief + persisted project state. Does not require pre-seeded assumption rows.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from app.grill.reasoning import ContradictionFinding, ContradictionKind
from app.grill.tech import TechnologySelection
from app.projects.models import ProjectState, Severity

_NORM = re.compile(r"[^a-z0-9]+")

# Competing persistence / infra families (same category → conflict without migration)
_DB_FAMILY = {
    "sqlite": "database",
    "postgresql": "database",
    "postgres": "database",
    "mysql": "database",
    "mongodb": "database",
    "mongo": "database",
    "dynamodb": "database",
}

_HOSTING_API_CUES = (
    "vercel for api",
    "vercel api",
    "api on vercel",
    "host the api on vercel",
    "hosting fastapi on vercel",
    "entire stack on vercel",
    "whole product on vercel",
    "all on vercel",
    "vercel serverless",
    "run long llm",
    "llm reviews entirely on vercel",
)

_BOOK_CLAIM_RE = re.compile(
    r"\b("
    r"all\s+(?:eight|8)\b|"
    r"(?:eight|8)\s+(?:books?|titles?)\b|"
    r"(?:books?|titles?)\s+(?:all\s+)?(?:eight|8)\b|"
    r"8\s*/\s*8|"
    r"eight\s+of\s+eight|"
    r"all\s+target\s+books?\s+(?:live|active|complete)"
    r")\b",
    re.I,
)

_MIGRATION_CUES = (
    "migration",
    "migrate",
    "dual write",
    "dual-write",
    "read replica",
    "replace sqlite",
    "move off sqlite",
    "phase out sqlite",
)

# Negation / exclusion markers in a short window before an entity match
_NEGATION_PHRASES = (
    "ruled out",
    "instead of",
    "rather than",
    "as opposed to",
    "will not",
    "do not",
    "does not",
    "did not",
    "won t",
    "wont",
    "don t",
    "dont",
    "locking out",
    "lock out",
    "steer clear",
    "staying away",
)
_NEGATION_TOKENS = frozenset(
    {
        "not",
        "no",
        "never",
        "without",
        "avoid",
        "avoiding",
        "avoids",
        "dropped",
        "drop",
        "rejecting",
        "rejected",
        "reject",
        "excluding",
        "exclude",
        "excluded",
        "neither",
        "nor",
        "against",
        "skip",
        "skipping",
        "omit",
        "omitting",
    }
)


def _norm(text: str) -> str:
    return _NORM.sub(" ", (text or "").lower()).strip()


def _window_before(text: str, match_start: int, *, words: int = 8) -> str:
    before = (text or "")[: max(match_start, 0)]
    tokens = before.split()
    return " ".join(tokens[-words:])


def _is_negated_at(text: str, match_start: int, *, words: int = 8) -> bool:
    """True when the entity at match_start is under an explicit exclusion/negation."""
    window = _norm(_window_before(text, match_start, words=words))
    if not window:
        return False
    for phrase in _NEGATION_PHRASES:
        if phrase in window:
            return True
    tokens = window.split()
    return any(tok in _NEGATION_TOKENS for tok in tokens)


def _affirmative_matches(text: str, pattern: str) -> list[re.Match[str]]:
    n = _norm(text)
    out: list[re.Match[str]] = []
    for m in re.finditer(pattern, n, flags=re.I):
        if _is_negated_at(n, m.start()):
            continue
        out.append(m)
    return out


def _entity_affirmatively_present(text: str, entity: str) -> bool:
    token = _norm(entity)
    if not token:
        return False
    return bool(_affirmative_matches(text, rf"\b{re.escape(token)}\b"))


def _blob(project: ProjectState, user_message: str) -> str:
    parts = [
        user_message or "",
        project.objective or "",
        project.problem_statement or "",
        project.architecture_notes or "",
        project.implementation_status or "",
        " ".join(project.success_criteria or []),
        " ".join(r.text for r in project.functional_requirements or []),
        " ".join(f"{d.title} {d.choice}" for d in project.decisions or []),
        " ".join(t for t in project.tech_stack or []),
        " ".join(
            f"{getattr(t, 'category', '')} {getattr(t, 'selected', '')}"
            for t in getattr(project, "technology_selections", []) or []
        ),
    ]
    return _norm(" ".join(parts))


def _message_mentions(msg: str, *phrases: str) -> bool:
    n = _norm(msg)
    return any(_norm(p) in n for p in phrases if p)


def _locked_db_primaries(project: ProjectState) -> set[str]:
    locked: set[str] = set()
    for sel in getattr(project, "technology_selections", []) or []:
        if not isinstance(sel, TechnologySelection) and not hasattr(sel, "selected"):
            continue
        status = (getattr(sel, "status", "") or "").lower()
        category = (getattr(sel, "category", "") or "").lower()
        selected = (getattr(sel, "selected", "") or "").strip().lower()
        if category == "database" and status in {"accepted", "confirmed", "provisional"}:
            if selected:
                locked.add(selected.split()[0])
    for tech in project.tech_stack or []:
        key = (tech or "").strip().lower()
        if key in _DB_FAMILY:
            locked.add(key)
    for d in project.decisions or []:
        blob = _norm(f"{d.title} {d.choice}")
        if "sqlite" in blob and (d.status or "").lower() in {
            "confirmed",
            "accepted",
            "provisionally_accepted",
        }:
            locked.add("sqlite")
        if ("postgres" in blob or "postgresql" in blob) and (d.status or "").lower() in {
            "confirmed",
            "accepted",
            "provisionally_accepted",
        }:
            locked.add("postgresql")
    return locked


def _extract_db_mentions(text: str, *, affirmative_only: bool = True) -> set[str]:
    n = _norm(text)
    found: set[str] = set()
    for token, _family in _DB_FAMILY.items():
        matches = (
            _affirmative_matches(n, rf"\b{re.escape(token)}\b")
            if affirmative_only
            else list(re.finditer(rf"\b{re.escape(token)}\b", n, flags=re.I))
        )
        if not matches:
            continue
        if token in {"postgres", "postgresql"}:
            found.add("postgresql")
        elif token in {"mongo", "mongodb"}:
            found.add("mongodb")
        else:
            found.add(token)
    return found


def _rejected_approaches(project: ProjectState) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for r in getattr(project, "rejected_approaches", []) or []:
        approach = (getattr(r, "approach", None) or "").strip()
        reason = (getattr(r, "reason", None) or "").strip()
        if approach:
            out.append((approach, reason))
    return out


def _looks_like_vercel_api_hosting(text: str) -> bool:
    """True only for affirmative Vercel-for-API proposals (negations ignored)."""
    n = _norm(text)
    vercel_hits = _affirmative_matches(n, r"\bvercel\b")
    if not vercel_hits:
        return False

    for cue in _HOSTING_API_CUES:
        cue_n = _norm(cue)
        if cue_n not in n:
            continue
        # Require the cue itself not to sit under negation
        idx = n.find(cue_n)
        if idx >= 0 and not _is_negated_at(n, idx):
            return True

    # Affirmative "vercel" near api/backend/fastapi in the same normalized text
    if any(k in n for k in ("api", "backend", "fastapi", "serverless", "llm", "uvicorn")):
        return True
    return False


def _rejected_vercel_api(project: ProjectState) -> bool:
    for approach, reason in _rejected_approaches(project):
        blob = _norm(f"{approach} {reason}")
        if "vercel" in blob and any(
            k in blob for k in ("api", "fastapi", "backend", "volume", "llm", "serverless")
        ):
            return True
        if _norm(approach) in {
            "hosting fastapi on vercel",
            "vercel for api",
            "api on vercel",
        }:
            return True
    return False


def load_books_manifest_counts(manifest_path: Path | None = None) -> dict[str, int]:
    """Return acquired / metadata_only / planned counts from books/RESOURCE_MANIFEST.json."""
    path = manifest_path or _default_manifest_path()
    if not path.is_file():
        return {"acquired": 0, "metadata_only": 0, "active": 0, "total_resources": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"acquired": 0, "metadata_only": 0, "active": 0, "total_resources": 0}

    resources = data.get("resources") or []
    acquired = sum(1 for r in resources if (r.get("status") or "") == "acquired")
    metadata_only = sum(1 for r in resources if (r.get("status") or "") == "metadata_only")
    baseline = data.get("release_baseline") or {}
    active = int(baseline.get("active_acquired") or acquired)
    return {
        "acquired": acquired,
        "metadata_only": metadata_only,
        "active": active,
        "total_resources": len(resources),
    }


def _default_manifest_path() -> Path:
    # backend/app/grill/review_gate.py → repo root books/
    return Path(__file__).resolve().parents[3] / "books" / "RESOURCE_MANIFEST.json"


def detect_review_blocking_contradictions(
    project: ProjectState,
    user_message: str,
    *,
    manifest_path: Path | None = None,
) -> list[ContradictionFinding]:
    """
    Fail-closed REVIEW checks. Empty assumptions list is fine — claims in the
    brief itself are treated as unvalidated until state/artifacts agree.
    """
    findings: list[ContradictionFinding] = []
    msg = user_message or ""
    blob = _blob(project, msg)
    msg_n = _norm(msg)

    # --- 1) Stack / dual-DB conflicts ---
    # Affirmative mentions only: "no Postgres" / "ruled out Mongo" do not compete.
    msg_dbs = _extract_db_mentions(msg, affirmative_only=True)
    state_dbs = _extract_db_mentions(
        " ".join(
            [
                " ".join(project.tech_stack or []),
                " ".join(
                    f"{getattr(t, 'selected', '')}"
                    for t in getattr(project, "technology_selections", []) or []
                ),
                " ".join(f"{d.choice}" for d in project.decisions or []),
            ]
        ),
        affirmative_only=False,
    )
    mentioned = msg_dbs | state_dbs
    locked = _locked_db_primaries(project)
    has_migration = any(_norm(c) in blob for c in _MIGRATION_CUES)

    competing = set()
    # Dual-DB from the brief itself (both affirmative)
    if "sqlite" in msg_dbs and "postgresql" in msg_dbs:
        competing.add(("sqlite", "postgresql"))
    if "sqlite" in msg_dbs and "mongodb" in msg_dbs:
        competing.add(("sqlite", "mongodb"))
    # Locked primary + affirmative competing DB in the brief
    if locked and msg_dbs - locked and not has_migration:
        for other in msg_dbs - locked:
            if other in _DB_FAMILY and any(
                _DB_FAMILY.get(l) == _DB_FAMILY.get(other) for l in locked
            ):
                competing.add((sorted(locked)[0], other))

    if competing and not has_migration:
        pair = next(iter(competing))
        findings.append(
            ContradictionFinding(
                kind=ContradictionKind.BLOCKING,
                statements=[
                    f"Production setup claims both {pair[0]} and {pair[1]}",
                    "No migration / dual-write plan recorded in project state",
                ],
                why=(
                    "Competing persistence engines in the same category without an "
                    "explicit migration requirement is a blocking architecture contradiction."
                ),
                severity=Severity.HIGH.value,
                consequence=(
                    "Split-brain data, undefined source of truth, and failed single-node beta ops."
                ),
                resolution=(
                    "Pick one primary database for beta, or add an explicit migration "
                    "requirement and supersede the prior selection."
                ),
                field="tech_stack",
            )
        )

    # --- 2) Rejected option regressions (e.g. Vercel for API) ---
    # Only the user brief can reintroduce a rejection; negated restatements are fine.
    if _rejected_vercel_api(project) and _looks_like_vercel_api_hosting(msg):
        findings.append(
            ContradictionFinding(
                kind=ContradictionKind.BLOCKING,
                statements=[
                    "Brief proposes Vercel for API / long LLM hosting",
                    "Project rejected_approaches already records Vercel API hosting as rejected",
                ],
                why=(
                    "Reintroducing a rejected hosting approach without superseding the "
                    "rejection is a blocking regression."
                ),
                severity=Severity.HIGH.value,
                consequence=(
                    "Deploy will fail persistence / long-request constraints that motivated the rejection."
                ),
                resolution=(
                    "Keep API on an external FastAPI node (compose/Docker), or explicitly "
                    "replace the rejection with counterevidence and a new decision."
                ),
                field="rejected_approaches",
            )
        )

    # Generic: any rejected approach phrase reappears as a positive proposal in the brief
    for approach, reason in _rejected_approaches(project):
        a_n = _norm(approach)
        if len(a_n) < 5 or "vercel" in a_n:
            continue
        # Require affirmative reintroduction (not "we still reject X")
        hits = _affirmative_matches(msg_n, rf"\b{re.escape(a_n)}\b")
        if not hits and a_n in msg_n:
            # Multi-word approach: check first distinctive token affirmatively
            key = a_n.split()[0]
            if len(key) >= 5 and _entity_affirmatively_present(msg_n, key):
                hits = _affirmative_matches(msg_n, rf"\b{re.escape(key)}\b")
        if hits:
            findings.append(
                ContradictionFinding(
                    kind=ContradictionKind.BLOCKING,
                    statements=[
                        f"Brief reintroduces rejected approach: {approach}",
                        f"Prior rejection reason: {reason or 'recorded in project state'}",
                    ],
                    why="Rejected approaches must not return without an explicit state update.",
                    severity=Severity.HIGH.value,
                    consequence="Wasted build cycles and contradictory architecture.",
                    resolution=(
                        "Remove the proposal, or supersede the rejection with rationale in project context."
                    ),
                    field="rejected_approaches",
                )
            )
            break

    # --- 3) Manifest / books completion mismatch ---
    counts = load_books_manifest_counts(manifest_path)
    active = counts.get("active") or counts.get("acquired") or 0
    book_match = _BOOK_CLAIM_RE.search(msg_n)
    if book_match and not _is_negated_at(msg_n, book_match.start()):
        claimed_eight = True
    else:
        eight_m = re.search(r"\b(?:eight|8)\b", msg_n)
        claimed_eight = bool(
            eight_m
            and not _is_negated_at(msg_n, eight_m.start())
            and re.search(r"\b(?:books?|titles?|skills?)\b", msg_n)
            and re.search(r"\b(?:live|active|complete|all|ready)\b", msg_n)
        )

    if claimed_eight and active < 8:
        findings.append(
            ContradictionFinding(
                kind=ContradictionKind.BLOCKING,
                statements=[
                    "Brief claims eight Books-to-Skill titles are live/complete",
                    f"Verified active acquired titles on disk/manifest: {active}",
                ],
                why=(
                    "Quantitative completion claims that exceed verified artifacts are "
                    "blocking evidence failures for go-live REVIEW."
                ),
                severity=Severity.HIGH.value,
                consequence="Overstated product capability and broken Knowledge Library expectations.",
                resolution=(
                    f"Claim only the {active} verified active titles, or acquire/approve "
                    "remaining titles and update the manifest before go-live."
                ),
                field="books_manifest",
            )
        )

    # --- 4) Unverified multi-tenant / public SaaS scale claims on SQLite beta ---
    scale_phrases = (
        "multi tenant",
        "multi user saas",
        "public saas",
        "horizontal scale",
        "production multi user",
        "public multi user",
    )
    scale_claim = False
    for p in scale_phrases:
        idx = msg_n.find(p)
        if idx >= 0 and not _is_negated_at(msg_n, idx):
            scale_claim = True
            break
    sqlite_locked = "sqlite" in locked or "sqlite" in state_dbs or "sqlite" in _norm(
        " ".join(project.tech_stack or [])
    )
    if scale_claim and sqlite_locked:
        findings.append(
            ContradictionFinding(
                kind=ContradictionKind.BLOCKING,
                statements=[
                    "Brief claims public multi-user / multi-tenant SaaS scale",
                    "Persistence remains single-node SQLite without a multi-writer plan",
                ],
                why=(
                    "Single-node SQLite beta capacity does not evidence public multi-tenant SaaS claims."
                ),
                severity=Severity.HIGH.value,
                consequence="Data corruption risk under concurrent writers; misleading launch positioning.",
                resolution=(
                    "Scope launch as single-node beta (WAL, single-writer), or introduce a "
                    "multi-writer datastore decision with evidence."
                ),
                field="scale",
            )
        )

    return _dedupe(findings)


def _dedupe(items: Iterable[ContradictionFinding]) -> list[ContradictionFinding]:
    seen: set[str] = set()
    out: list[ContradictionFinding] = []
    for c in items:
        key = f"{c.kind}|{c.field}|{c.why}"
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out
