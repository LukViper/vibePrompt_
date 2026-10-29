"""Deterministic project readiness gate — not driven by LLM severity alone."""

from __future__ import annotations

from app.projects.models import FindingStatus, ProjectState, ReadinessResult, Severity


def assess_readiness(project: ProjectState) -> ReadinessResult:
    blockers: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    unblock: list[str] = []
    accepted: list[str] = []

    if not (project.objective or "").strip():
        missing.append("Project objective is missing")
        unblock.append("State a clear objective and intended users")

    if not project.intended_users:
        missing.append("Intended users are unspecified")
        unblock.append("Name the primary user persona(s)")

    if not project.success_criteria and not project.functional_requirements:
        missing.append("No success criteria or functional requirements")
        unblock.append("Add at least one success criterion or functional requirement")

    if not project.decisions and not project.tech_stack:
        warnings.append("No technology or architecture decisions recorded yet")

    # Open critical findings are always blockers
    for finding in project.findings:
        if finding.status != FindingStatus.OPEN:
            if finding.status == FindingStatus.ACCEPTED_RISK:
                accepted.append(f"{finding.title} ({finding.severity.value})")
            continue

        if finding.severity == Severity.CRITICAL:
            blockers.append(f"[critical] {finding.title}: {finding.challenged_claim}")
            unblock.append(finding.recommended_next_step or f"Resolve finding {finding.id}")
        elif finding.severity == Severity.HIGH:
            # High open findings block unless confidence is very low after critic disagreement
            if finding.confidence >= 0.35:
                blockers.append(f"[high] {finding.title}: {finding.challenged_claim}")
                unblock.append(finding.recommended_next_step or f"Decide on finding {finding.id}")
            else:
                warnings.append(
                    f"[high, low confidence] {finding.title} — needs stronger evidence or a decision"
                )
        elif finding.severity == Severity.MEDIUM:
            warnings.append(f"[medium] {finding.title}")
        else:
            warnings.append(f"[low] {finding.title}")

    # Unanswered high-priority open questions about essentials
    for q in project.open_questions:
        if not q.answered and q.priority in {"high", "critical"}:
            missing.append(f"Open question: {q.text}")
            unblock.append(f"Answer: {q.text}")

    if blockers or missing:
        status = "not_ready"
        ready = False
    elif accepted:
        status = "ready_with_accepted_risks"
        ready = True
    else:
        status = "ready"
        ready = True

    # Deduplicate while preserving order
    def uniq(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for i in items:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out

    return ReadinessResult(
        ready=ready,
        status=status,
        blockers=uniq(blockers),
        warnings=uniq(warnings),
        missing_essentials=uniq(missing),
        accepted_risk_summaries=uniq(accepted),
        unblock_actions=uniq(unblock),
    )
