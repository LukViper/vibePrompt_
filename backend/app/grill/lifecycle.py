"""Finding lifecycle operations and deduplication."""

from __future__ import annotations

import re

from app.projects.models import (
    CriticOutcome,
    Finding,
    FindingStatus,
    ReviewProvenance,
    Severity,
    utcnow,
)
from app.providers.base import CandidateFinding, CriticReview


_SEVERITY_MAP = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
}


def parse_severity(value: str) -> Severity:
    return _SEVERITY_MAP.get((value or "medium").lower().strip(), Severity.MEDIUM)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def similar_finding(existing: Finding, candidate: CandidateFinding) -> bool:
    a = _normalize(existing.challenged_claim)
    b = _normalize(candidate.challenged_claim)
    if not a or not b:
        return _normalize(existing.title) == _normalize(candidate.title)
    if a == b:
        return True
    # Token overlap heuristic
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / max(len(ta | tb), 1)
    return overlap >= 0.6


def candidate_to_finding(
    candidate: CandidateFinding,
    *,
    provenance: ReviewProvenance,
    critic_outcome: CriticOutcome | None = None,
    critic_notes: str | None = None,
) -> Finding:
    return Finding(
        title=candidate.title.strip() or "Untitled concern",
        challenged_claim=candidate.challenged_claim.strip(),
        reasoning=candidate.reasoning.strip(),
        evidence=list(candidate.evidence),
        assumptions_to_verify=list(candidate.assumptions_to_verify),
        severity=parse_severity(candidate.severity),
        confidence=max(0.0, min(1.0, float(candidate.confidence))),
        potential_impact=candidate.potential_impact,
        recommended_next_step=candidate.recommended_next_step,
        invalidation_criteria=candidate.invalidation_criteria,
        provenance=provenance,
        critic_outcome=critic_outcome,
        critic_notes=critic_notes,
    )


def merge_candidates_into_project(
    existing: list[Finding],
    candidates: list[CandidateFinding],
    *,
    provenance: ReviewProvenance,
    critic_outcome: CriticOutcome | None = None,
    critic_notes: str | None = None,
) -> list[Finding]:
    """Add or revise findings. Never reopen resolved/rejected without material change."""
    result = list(existing)
    for cand in candidates:
        match = next((f for f in result if similar_finding(f, cand)), None)
        if match is None:
            result.append(
                candidate_to_finding(
                    cand,
                    provenance=provenance,
                    critic_outcome=critic_outcome,
                    critic_notes=critic_notes,
                )
            )
            continue

        if match.status in (FindingStatus.RESOLVED, FindingStatus.REJECTED):
            # Only reopen with stronger/new material evidence
            new_sev = parse_severity(cand.severity)
            if new_sev in (Severity.CRITICAL, Severity.HIGH) and cand.evidence:
                match.status = FindingStatus.OPEN
                match.revise(
                    title=cand.title,
                    reasoning=cand.reasoning,
                    severity=new_sev,
                    confidence=cand.confidence,
                    note="Reopened due to new material evidence",
                )
                match.evidence = list(dict.fromkeys([*match.evidence, *cand.evidence]))
                match.provenance = provenance
                match.critic_outcome = critic_outcome
                match.critic_notes = critic_notes
                match.resolved_at = None
            continue

        if match.status == FindingStatus.ACCEPTED_RISK:
            continue

        # Update open finding if revised
        match.revise(
            title=cand.title,
            reasoning=cand.reasoning,
            severity=parse_severity(cand.severity),
            confidence=cand.confidence,
            note="Updated from new review",
        )
        match.evidence = list(dict.fromkeys([*match.evidence, *cand.evidence]))
        match.recommended_next_step = cand.recommended_next_step or match.recommended_next_step
        match.provenance = provenance
        if critic_outcome is not None:
            match.critic_outcome = critic_outcome
            match.critic_notes = critic_notes

    return result


def apply_critic_review(
    candidates: list[CandidateFinding],
    review: CriticReview,
) -> tuple[list[CandidateFinding], CriticOutcome, str]:
    """Reconcile critic feedback conservatively."""
    if review.insufficient_context and not review.actions:
        return candidates, CriticOutcome.INSUFFICIENT_EVIDENCE, review.overall_notes

    kept: list[CandidateFinding] = list(candidates)
    outcome = CriticOutcome.AGREE
    notes_parts: list[str] = []

    # Track which indices the critic disagreed with
    disagreed: set[int] = set()
    for action in review.actions:
        act = action.action.lower().strip()
        notes_parts.append(action.notes)

        if act == "disagree" and action.finding_index is not None:
            disagreed.add(action.finding_index)
            outcome = CriticOutcome.DISAGREE
            # Do NOT auto-delete high-impact findings
            if 0 <= action.finding_index < len(kept):
                f = kept[action.finding_index]
                if f.severity.lower() in {"critical", "high"}:
                    # Lower confidence instead of dropping
                    kept[action.finding_index] = f.model_copy(
                        update={"confidence": max(0.2, f.confidence * 0.6)}
                    )
                else:
                    # Drop weak low/medium findings the critic rejects
                    kept[action.finding_index] = f.model_copy(
                        update={"confidence": max(0.1, f.confidence * 0.4), "severity": "low"}
                    )

        elif act == "revise" and action.revised is not None:
            outcome = CriticOutcome.REVISE
            if action.finding_index is not None and 0 <= action.finding_index < len(kept):
                kept[action.finding_index] = action.revised
            else:
                kept.append(action.revised)

        elif act == "add_risk" and action.revised is not None:
            outcome = CriticOutcome.ADD_RISK
            kept.append(action.revised)

        elif act == "insufficient_evidence":
            outcome = CriticOutcome.INSUFFICIENT_EVIDENCE
            if action.finding_index is not None and 0 <= action.finding_index < len(kept):
                f = kept[action.finding_index]
                kept[action.finding_index] = f.model_copy(
                    update={"confidence": max(0.15, f.confidence * 0.5)}
                )

        elif act == "agree":
            outcome = CriticOutcome.AGREE if outcome == CriticOutcome.AGREE else outcome

    if review.overall_notes:
        notes_parts.append(review.overall_notes)

    return kept, outcome, "; ".join(n for n in notes_parts if n)


def update_finding_status(
    finding: Finding,
    status: FindingStatus,
    note: str | None = None,
) -> Finding:
    finding.status = status
    finding.updated_at = utcnow()
    finding.resolution_note = note
    if status in (
        FindingStatus.RESOLVED,
        FindingStatus.REJECTED,
        FindingStatus.ACCEPTED_RISK,
    ):
        finding.resolved_at = utcnow()
    else:
        finding.resolved_at = None
    return finding
