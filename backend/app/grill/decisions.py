"""Decision register helpers — statuses, history, accept/reject without silent overwrite."""

from __future__ import annotations

from typing import Any

from app.projects.models import (
    Decision,
    DecisionRevision,
    DecisionStatus,
    ProjectState,
    RejectedApproach,
    normalize_decision_status,
    utcnow,
)


def decision_is_locked(status: str | DecisionStatus | None) -> bool:
    """Confirmed decisions must not be silently overwritten."""
    s = normalize_decision_status(status)
    return s in {
        DecisionStatus.CONFIRMED.value,
        DecisionStatus.RESOLVED.value,
        # legacy
        "accepted",
    }


def append_decision_history(
    decision: Decision,
    *,
    note: str,
    actor: str = "system",
) -> None:
    decision.history.append(
        DecisionRevision(
            at=utcnow(),
            title=decision.title,
            choice=decision.choice,
            status=normalize_decision_status(decision.status),
            rationale=decision.rationale or "",
            note=note,
            actor=actor,
        )
    )
    decision.updated_at = utcnow()


def propose_decision(
    project: ProjectState,
    *,
    title: str,
    choice: str,
    rationale: str = "",
    alternatives: list[str] | None = None,
    source: str = "grill_mentor",
) -> Decision:
    """Add a proposed decision — never auto-confirmed."""
    existing = next(
        (
            d
            for d in project.decisions
            if d.title.lower() == title.lower()
            and normalize_decision_status(d.status)
            not in (DecisionStatus.SUPERSEDED.value, DecisionStatus.REJECTED.value)
        ),
        None,
    )
    if existing and decision_is_locked(existing.status):
        # Do not overwrite — surface as separate proposal with distinct title if needed
        title = f"Proposed change: {title}"[:200]
    dec = Decision(
        title=title[:200],
        choice=choice[:500],
        rationale=rationale[:1000],
        alternatives_considered=list(alternatives or [])[:8],
        status=DecisionStatus.PROPOSED.value,
        source=source,
    )
    project.decisions.append(dec)
    project.touch()
    return dec


def update_decision_status(
    project: ProjectState,
    decision_id: str,
    *,
    status: str,
    note: str | None = None,
    actor: str = "user",
) -> Decision:
    """
    Accept / reject / resolve a decision through the decision-management workflow.
    Never silently changes a confirmed choice's text — only status transitions.
    """
    decision = next((d for d in project.decisions if d.id == decision_id), None)
    if decision is None:
        raise KeyError(f"Decision {decision_id} not found")

    new_status = normalize_decision_status(status)
    append_decision_history(
        decision,
        note=note or f"Status → {new_status}",
        actor=actor,
    )
    decision.status = new_status
    decision.updated_at = utcnow()

    if new_status == DecisionStatus.REJECTED.value:
        reason = (note or decision.rationale or "Rejected by user").strip()
        if not any(
            r.approach.lower() == decision.choice.lower() for r in project.rejected_approaches
        ):
            project.rejected_approaches.append(
                RejectedApproach(approach=decision.choice, reason=reason[:1000])
            )
    elif new_status == DecisionStatus.CONFIRMED.value:
        # Supersede other active decisions with the same title
        for other in project.decisions:
            if other.id == decision.id:
                continue
            if other.title.lower() != decision.title.lower():
                continue
            if normalize_decision_status(other.status) in (
                DecisionStatus.SUPERSEDED.value,
                DecisionStatus.REJECTED.value,
            ):
                continue
            append_decision_history(
                other,
                note=f"Superseded by confirmed decision {decision.id}",
                actor=actor,
            )
            other.status = DecisionStatus.SUPERSEDED.value
            other.updated_at = utcnow()

    project.touch()
    return decision


def apply_decision_dict(
    project: ProjectState,
    item: dict[str, Any],
    *,
    allow_replace: bool = False,
) -> tuple[Decision | None, str | None]:
    """
    Apply one decision dict from a state_patch.
    Returns (decision_or_none, contradiction_message_or_none).
    """
    title = str(item.get("title") or "").strip()
    choice = str(item.get("choice") or "").strip()
    if not title or not choice:
        return None, None

    source = str(item.get("source") or "state_patch")[:80]
    default_status = (
        DecisionStatus.PROPOSED.value
        if source == "grill_mentor"
        else DecisionStatus.CONFIRMED.value
    )
    status = normalize_decision_status(item.get("status") or default_status)
    # AI mentor must never land as confirmed unless explicitly replace+user path
    if source == "grill_mentor" and status == DecisionStatus.CONFIRMED.value:
        status = DecisionStatus.PROPOSED.value

    rationale = str(item.get("rationale") or "")[:1000]
    alts = item.get("alternatives_considered") or []
    if not isinstance(alts, list):
        alts = []
    explicit_replace = bool(item.get("replace") or allow_replace)

    existing = next(
        (
            d
            for d in project.decisions
            if d.title.lower() == title.lower()
            and normalize_decision_status(d.status)
            not in (DecisionStatus.SUPERSEDED.value, DecisionStatus.REJECTED.value)
        ),
        None,
    )

    if existing:
        if choice.lower() == existing.choice.lower():
            if rationale and not existing.rationale:
                existing.rationale = rationale
            # Upgrade provisional/proposed if patch asks
            if status in (
                DecisionStatus.PROVISIONALLY_ACCEPTED.value,
                DecisionStatus.PROPOSED.value,
                DecisionStatus.UNVERIFIED.value,
            ):
                pass
            elif (
                status == DecisionStatus.CONFIRMED.value
                and not decision_is_locked(existing.status)
            ):
                append_decision_history(existing, note="Confirmed via state_patch", actor="user")
                existing.status = DecisionStatus.CONFIRMED.value
            return existing, None

        if decision_is_locked(existing.status) and not explicit_replace:
            return None, (
                f"Confirmed decision '{existing.title}' ({existing.choice}) cannot be "
                f"silently replaced with '{choice}'. Set replace=true after user accepts."
            )

        append_decision_history(
            existing,
            note=f"Superseded → {choice}",
            actor="user" if explicit_replace else "system",
        )
        existing.status = DecisionStatus.SUPERSEDED.value
        new = Decision(
            title=title[:200],
            choice=choice[:500],
            rationale=rationale,
            status=status
            if status != DecisionStatus.PROPOSED.value or explicit_replace
            else (
                DecisionStatus.CONFIRMED.value
                if explicit_replace
                else DecisionStatus.PROPOSED.value
            ),
            source=source,
            alternatives_considered=list(
                dict.fromkeys(list(alts) + [existing.choice])
            )[:8],
        )
        project.decisions.append(new)
        return new, None

    new = Decision(
        title=title[:200],
        choice=choice[:500],
        rationale=rationale,
        status=status,
        source=source,
        alternatives_considered=[str(a)[:200] for a in alts][:8],
    )
    project.decisions.append(new)
    return new, None
