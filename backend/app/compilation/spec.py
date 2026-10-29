"""Generate implementation-ready specifications from persisted project state."""

from __future__ import annotations

from typing import Any

from app.compilation.readiness import assess_readiness
from app.projects.models import FindingStatus, ProjectState, SpecificationResult


def _bullets(items: list[str], empty: str = "_None recorded._") -> str:
    if not items:
        return empty
    return "\n".join(f"- {i}" for i in items)


def compile_specification(project: ProjectState) -> SpecificationResult:
    readiness = assess_readiness(project)

    open_findings = [f for f in project.findings if f.status == FindingStatus.OPEN]
    accepted = [f for f in project.findings if f.status == FindingStatus.ACCEPTED_RISK]
    resolved = [
        f
        for f in project.findings
        if f.status in (FindingStatus.RESOLVED, FindingStatus.REJECTED)
    ]

    structured: dict[str, Any] = {
        "project_id": project.id,
        "name": project.name,
        "objective": project.objective,
        "intended_users": project.intended_users,
        "success_criteria": project.success_criteria,
        "scope_in": project.scope_in,
        "scope_out": project.scope_out,
        "functional_requirements": [r.model_dump(mode="json") for r in project.functional_requirements],
        "non_functional_requirements": [
            r.model_dump(mode="json") for r in project.non_functional_requirements
        ],
        "constraints": [c.model_dump(mode="json") for c in project.constraints],
        "decisions": [d.model_dump(mode="json") for d in project.decisions],
        "assumptions": [a.model_dump(mode="json") for a in project.assumptions],
        "tech_stack": project.tech_stack,
        "architecture_notes": project.architecture_notes,
        "data_model_notes": project.data_model_notes,
        "security_notes": project.security_notes,
        "testing_notes": project.testing_notes,
        "milestones": project.milestones,
        "open_findings": [f.model_dump(mode="json") for f in open_findings],
        "accepted_risks": [f.model_dump(mode="json") for f in accepted],
        "readiness": readiness.model_dump(mode="json"),
    }

    # Do not invent decisions — only reflect persisted state
    status_banner = {
        "ready": "READY TO IMPLEMENT",
        "ready_with_accepted_risks": "READY WITH EXPLICITLY ACCEPTED RISKS",
        "not_ready": "NOT READY — ESSENTIAL DECISIONS OR BLOCKERS REMAIN",
    }.get(readiness.status, readiness.status)

    md_parts = [
        f"# Implementation Specification: {project.name}",
        "",
        f"**Compilation status:** {status_banner}",
        "",
        "This specification is generated from persisted project state. "
        "It does not invent missing decisions.",
        "",
        "## 1. Objective and target users",
        "",
        project.objective or "_Objective not yet defined._",
        "",
        "**Intended users:**",
        _bullets(project.intended_users),
        "",
        "**Success criteria:**",
        _bullets(project.success_criteria),
        "",
        "## 2. Scope and non-goals",
        "",
        "**In scope:**",
        _bullets(project.scope_in),
        "",
        "**Out of scope / non-goals:**",
        _bullets(project.scope_out),
        "",
        "## 3. Requirements and acceptance criteria",
        "",
        "### Functional",
    ]

    if project.functional_requirements:
        for req in project.functional_requirements:
            md_parts.append(f"- **{req.id}:** {req.text}")
            for ac in req.acceptance_criteria:
                md_parts.append(f"  - Acceptance: {ac}")
    else:
        md_parts.append("_None recorded._")

    md_parts.extend(["", "### Non-functional"])
    if project.non_functional_requirements:
        for req in project.non_functional_requirements:
            md_parts.append(f"- **{req.id}:** {req.text}")
    else:
        md_parts.append("_None recorded._")

    md_parts.extend(
        [
            "",
            "## 4. Architecture and technology decisions",
            "",
            f"**Tech stack:** {', '.join(project.tech_stack) if project.tech_stack else '_Not specified._'}",
            "",
            project.architecture_notes or "_No architecture notes recorded._",
            "",
        ]
    )
    if project.decisions:
        for d in project.decisions:
            md_parts.append(f"- **{d.title}:** {d.choice}")
            if d.rationale:
                md_parts.append(f"  - Rationale: {d.rationale}")
    else:
        md_parts.append("_No explicit decisions recorded._")

    md_parts.extend(
        [
            "",
            "## 5. Data model and interfaces",
            "",
            project.data_model_notes or "_Not specified — do not invent schemas._",
            "",
            "## 6. Security and privacy",
            "",
            project.security_notes or "_Not specified — flag as unresolved if handling personal data._",
            "",
            "## 7. Constraints and assumptions",
            "",
            "**Constraints:**",
        ]
    )
    if project.constraints:
        for c in project.constraints:
            md_parts.append(f"- ({c.category}) {c.text}")
    else:
        md_parts.append("_None recorded._")

    md_parts.append("")
    md_parts.append("**Assumptions:**")
    if project.assumptions:
        for a in project.assumptions:
            md_parts.append(f"- [{a.status.value}] {a.statement}")
    else:
        md_parts.append("_None recorded._")

    md_parts.extend(
        [
            "",
            "## 8. Testing and validation",
            "",
            project.testing_notes or "_Define tests before treating the build as complete._",
            "",
            "## 9. Milestones / phases",
            "",
            _bullets(project.milestones),
            "",
            "## 10. Unresolved decisions and accepted risks",
            "",
            "### Open findings",
        ]
    )
    if open_findings:
        for f in open_findings:
            md_parts.append(
                f"- **[{f.severity.value}] {f.title}** ({f.status.value}): {f.challenged_claim}"
            )
            md_parts.append(f"  - Next step: {f.recommended_next_step or 'Decide or provide evidence'}")
    else:
        md_parts.append("_None._")

    md_parts.extend(["", "### Explicitly accepted risks"])
    if accepted:
        for f in accepted:
            md_parts.append(f"- **{f.title}:** {f.challenged_claim}")
            if f.resolution_note:
                md_parts.append(f"  - Acceptance note: {f.resolution_note}")
    else:
        md_parts.append("_None._")

    if readiness.blockers:
        md_parts.extend(["", "### Readiness blockers"])
        for b in readiness.blockers:
            md_parts.append(f"- {b}")

    if resolved:
        md_parts.extend(["", "### Previously resolved / rejected (for traceability)"])
        for f in resolved[:20]:
            md_parts.append(f"- [{f.status.value}] {f.title}")

    md_parts.append("")
    markdown = "\n".join(md_parts)

    return SpecificationResult(
        readiness=readiness,
        markdown=markdown,
        structured=structured,
    )
