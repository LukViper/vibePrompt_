"""Deterministic project readiness gate — not driven by LLM severity alone.

Chat readiness (`ready`) stays usable for discovery progress.
Agent-prompt generation requires `implementation_ready` (full mandatory checklist,
no conflicts, no critical blockers) — never trust `score_pct` alone.
"""

from __future__ import annotations

import re

from app.projects.models import (
    FindingStatus,
    ProjectState,
    ReadinessChecklistItem,
    ReadinessResult,
    Severity,
)


def _has_text(value: str | None) -> bool:
    return bool((value or "").strip())


def _acceptance_present(project: ProjectState) -> bool:
    if project.success_criteria:
        return True
    return any(r.acceptance_criteria for r in project.functional_requirements)


def _needs_data_model(project: ProjectState) -> bool:
    blob = " ".join(
        [
            " ".join(project.tech_stack or []),
            project.architecture_notes or "",
            " ".join(project.scope_in or []),
            " ".join(r.text for r in project.functional_requirements),
        ]
    ).lower()
    cues = (
        "database",
        "sqlite",
        "postgres",
        "mysql",
        "mongodb",
        "schema",
        "orm",
        "api",
        "persist",
        "storage",
        "crud",
    )
    return any(c in blob for c in cues)


def _needs_security(project: ProjectState) -> bool:
    blob = " ".join(
        [
            project.name or "",
            project.objective or "",
            project.problem_statement or "",
            " ".join(project.scope_in or []),
            " ".join(r.text for r in project.functional_requirements),
            " ".join(project.known_risks or []),
        ]
    ).lower()
    cues = (
        "auth",
        "oauth",
        "sso",
        "security",
        "cyber",
        "encrypt",
        "pii",
        "gdpr",
        "login",
        "permission",
        "rbac",
        "token",
        "credential",
        "siem",
        "malware",
        "threat",
    )
    return any(c in blob for c in cues)


def detect_project_conflicts(project: ProjectState) -> list[str]:
    """Surface contradictory requirements / architecture without applying a patch."""
    conflicts: list[str] = []
    rejected = [
        (r.approach or "").strip().lower()
        for r in getattr(project, "rejected_approaches", []) or []
        if (r.approach or "").strip()
    ]
    for tech in project.tech_stack or []:
        low = tech.lower()
        for approach in rejected:
            if approach and (approach in low or low in approach):
                conflicts.append(
                    f"Tech stack includes '{tech}' which overlaps rejected approach '{approach}'."
                )

    # Scope in vs out overlap
    outs = {(s or "").strip().lower() for s in project.scope_out or []}
    for item in project.scope_in or []:
        key = (item or "").strip().lower()
        if key and key in outs:
            conflicts.append(f"'{item}' is both in-scope and out-of-scope.")

    # Conflicting accepted decisions with same title different choice
    by_title: dict[str, list[str]] = {}
    for d in project.decisions or []:
        if getattr(d, "status", "accepted") == "superseded":
            continue
        by_title.setdefault((d.title or "").strip().lower(), []).append(d.choice or "")
    for title, choices in by_title.items():
        uniq = {c.strip().lower() for c in choices if c.strip()}
        if title and len(uniq) > 1:
            conflicts.append(
                f"Conflicting decisions for '{title}': {', '.join(sorted(set(choices)))}."
            )

    # Requirement text that reintroduces rejected approaches
    req_blob = " ".join(r.text for r in project.functional_requirements).lower()
    for approach in rejected:
        if approach and re.search(rf"\b{re.escape(approach)}\b", req_blob):
            conflicts.append(
                f"Functional requirements mention rejected approach '{approach}'."
            )

    # Deduplicate
    seen: set[str] = set()
    out: list[str] = []
    for c in conflicts:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def build_readiness_checklist(project: ProjectState) -> list[ReadinessChecklistItem]:
    """Explicit mandatory/conditional checks — score is derived from these, not vice versa."""
    problem_ok = _has_text(project.problem_statement) or _has_text(project.objective)
    users_ok = bool(project.intended_users)
    func_ok = bool(project.functional_requirements) or bool(project.success_criteria)
    nfr_ok = bool(project.non_functional_requirements)
    stack_ok = bool(project.tech_stack) or any(
        getattr(d, "status", "accepted") != "superseded" for d in project.decisions
    )
    arch_ok = _has_text(project.architecture_notes) or any(
        getattr(d, "status", "accepted") != "superseded"
        and re.search(r"architect|design|stack|backend|frontend", (d.title or ""), re.I)
        for d in project.decisions
    )
    scope_ok = bool(project.scope_in)
    constraints_ok = bool(project.constraints)
    acceptance_ok = _acceptance_present(project)
    deps_ok = bool(project.tech_stack) or bool(project.constraints)

    needs_dm = _needs_data_model(project)
    dm_ok = _has_text(project.data_model_notes) if needs_dm else True
    needs_sec = _needs_security(project)
    sec_ok = _has_text(project.security_notes) if needs_sec else True

    items = [
        ReadinessChecklistItem(
            id="problem_statement",
            label="Problem statement / objective",
            category="mandatory",
            present=problem_ok,
            detail=project.problem_statement or project.objective or "missing",
        ),
        ReadinessChecklistItem(
            id="target_users",
            label="Target users",
            category="mandatory",
            present=users_ok,
            detail=", ".join(project.intended_users) if users_ok else "missing",
        ),
        ReadinessChecklistItem(
            id="functional_requirements",
            label="Functional requirements",
            category="mandatory",
            present=func_ok,
            detail=f"{len(project.functional_requirements)} requirements"
            if project.functional_requirements
            else ("success criteria only" if project.success_criteria else "missing"),
        ),
        ReadinessChecklistItem(
            id="non_functional_requirements",
            label="Non-functional requirements",
            category="mandatory",
            present=nfr_ok,
            detail=f"{len(project.non_functional_requirements)} NFRs"
            if nfr_ok
            else "missing",
        ),
        ReadinessChecklistItem(
            id="technology_stack",
            label="Technology stack",
            category="mandatory",
            present=stack_ok,
            detail=", ".join(project.tech_stack) if project.tech_stack else "missing",
        ),
        ReadinessChecklistItem(
            id="system_architecture",
            label="System architecture",
            category="mandatory",
            present=arch_ok,
            detail=(project.architecture_notes or "")[:120] or "missing",
        ),
        ReadinessChecklistItem(
            id="implementation_scope",
            label="Implementation scope (in-scope)",
            category="mandatory",
            present=scope_ok,
            detail=", ".join(project.scope_in[:4]) if scope_ok else "missing",
        ),
        ReadinessChecklistItem(
            id="dependencies",
            label="Dependencies / stack constraints",
            category="mandatory",
            present=deps_ok,
            detail="tech stack and/or constraints recorded"
            if deps_ok
            else "missing",
        ),
        ReadinessChecklistItem(
            id="acceptance_criteria",
            label="Acceptance criteria",
            category="mandatory",
            present=acceptance_ok,
            detail="present" if acceptance_ok else "missing",
        ),
        ReadinessChecklistItem(
            id="known_constraints",
            label="Known constraints",
            category="mandatory",
            present=constraints_ok,
            detail=f"{len(project.constraints)} constraints"
            if constraints_ok
            else "missing",
        ),
        ReadinessChecklistItem(
            id="data_models",
            label="Data models",
            category="conditional",
            present=dm_ok,
            detail=(
                (project.data_model_notes or "")[:120]
                if needs_dm
                else "not applicable for this project"
            )
            if dm_ok
            else "required for persistence/API projects",
        ),
        ReadinessChecklistItem(
            id="security_requirements",
            label="Security requirements",
            category="conditional",
            present=sec_ok,
            detail=(
                (project.security_notes or "")[:120]
                if needs_sec
                else "not applicable for this project"
            )
            if sec_ok
            else "required for auth/security-sensitive projects",
        ),
    ]
    return items


def assess_readiness(project: ProjectState) -> ReadinessResult:
    blockers: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    unblock: list[str] = []
    accepted: list[str] = []

    # --- Chat-progress essentials (existing gate) ---
    if not (project.objective or "").strip() and not (project.problem_statement or "").strip():
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

    for q in project.open_questions:
        if not q.answered and q.priority in {"high", "critical"}:
            missing.append(f"Open question: {q.text}")
            unblock.append(f"Answer: {q.text}")

    checklist = build_readiness_checklist(project)
    conflicts = detect_project_conflicts(project)

    # Surface incomplete mandatory items for implementation (warnings + missing)
    for item in checklist:
        if item.present:
            continue
        if item.category == "mandatory":
            msg = f"Missing for implementation: {item.label}"
            if msg not in missing:
                missing.append(msg)
            unblock.append(f"Record {item.label.lower()}")
        elif item.category == "conditional":
            warnings.append(f"Conditional gap: {item.label} — {item.detail}")

    for c in conflicts:
        blockers.append(f"[conflict] {c}")
        unblock.append(f"Resolve conflict: {c}")

    # Score from checklist only (informational — never sole gate)
    if checklist:
        score_pct = int(round(100 * sum(1 for i in checklist if i.present) / len(checklist)))
    else:
        score_pct = 0

    mandatory_ok = all(i.present for i in checklist if i.category == "mandatory")
    conditional_ok = all(i.present for i in checklist if i.category == "conditional")
    no_findings_block = not any(
        f.status == FindingStatus.OPEN
        and f.severity in {Severity.CRITICAL, Severity.HIGH}
        and (f.severity == Severity.CRITICAL or f.confidence >= 0.35)
        for f in project.findings
    )
    implementation_ready = (
        mandatory_ok
        and conditional_ok
        and not conflicts
        and no_findings_block
        and not any(q for q in project.open_questions if not q.answered and q.priority in {"high", "critical"})
    )

    # Chat `ready`: keep discovery-friendly gate (essentials + no finding blockers)
    chat_blockers = [b for b in blockers if not b.startswith("[conflict]")]
    # Conflicts still block chat readiness — contradictory state is unsafe
    if blockers or [
        m
        for m in missing
        if not m.startswith("Missing for implementation:")
    ]:
        # Only classic essentials + finding blockers fail chat ready
        classic_missing = [
            m
            for m in missing
            if not m.startswith("Missing for implementation:")
        ]
        if chat_blockers or classic_missing:
            status = "not_ready"
            ready = False
        elif accepted:
            status = "ready_with_accepted_risks"
            ready = True
        else:
            status = "ready"
            ready = True
    elif accepted:
        status = "ready_with_accepted_risks"
        ready = True
    else:
        status = "ready"
        ready = True

    # If conflicts exist, never ready
    if conflicts:
        status = "not_ready"
        ready = False
        implementation_ready = False

    def uniq(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for i in items:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out

    if implementation_ready and ready and accepted:
        status = "ready_with_accepted_risks"
    elif implementation_ready and ready:
        status = "ready"

    return ReadinessResult(
        ready=ready,
        status=status,
        blockers=uniq(blockers),
        warnings=uniq(warnings),
        missing_essentials=uniq(missing),
        accepted_risk_summaries=uniq(accepted),
        unblock_actions=uniq(unblock),
        checklist=checklist,
        score_pct=score_pct,
        conflicts=uniq(conflicts),
        implementation_ready=implementation_ready,
    )
