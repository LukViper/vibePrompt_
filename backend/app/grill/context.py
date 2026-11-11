"""Context Management Engine — structured project memory and retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.grill.modes import BehaviouralMode, canonical_mode
from app.projects.models import (
    Decision,
    FindingStatus,
    ProjectState,
    RejectedApproach,
)
from app.providers.base import StatePatch
from app.providers.json_utils import sanitize_untrusted_text


@dataclass
class Contradiction:
    field: str
    existing: str
    incoming: str
    message: str


@dataclass
class ContextBundle:
    """Mode-relevant slice of project context for prompt assembly."""

    mode: BehaviouralMode
    snapshot: dict[str, Any]
    contradictions: list[Contradiction] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_prompt_json(self) -> dict[str, Any]:
        payload = dict(self.snapshot)
        if self.contradictions:
            payload["pending_contradictions"] = [
                {
                    "field": c.field,
                    "existing": c.existing,
                    "incoming": c.incoming,
                    "message": c.message,
                }
                for c in self.contradictions
            ]
        if self.notes:
            payload["context_notes"] = self.notes
        return payload


_NORM = re.compile(r"[^a-z0-9]+")


def _norm(text: str) -> str:
    return _NORM.sub(" ", (text or "").lower()).strip()


def _overlap(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    aw, bw = set(na.split()), set(nb.split())
    if not aw or not bw:
        return False
    return len(aw & bw) / max(len(aw), len(bw)) >= 0.6


def detect_contradictions(project: ProjectState, patch: StatePatch) -> list[Contradiction]:
    """Detect conflicts between a proposed patch and established decisions."""
    from app.grill.tech import (
        conflicts_with_selection,
        hydrate_selections_from_legacy,
        parse_technology_token,
    )

    found: list[Contradiction] = []
    selections = hydrate_selections_from_legacy(
        selections=getattr(project, "technology_selections", []) or [],
        tech_stack=list(project.tech_stack or []),
        decisions=list(project.decisions or []),
    )

    rejected_texts = [
        (r.approach, r.reason) for r in getattr(project, "rejected_approaches", []) or []
    ]
    if patch.tech_stack:
        for tech in patch.tech_stack:
            parsed = parse_technology_token(tech)
            for approach, reason in rejected_texts:
                if _overlap(tech, approach) or (
                    parsed.canonical and _overlap(parsed.canonical, approach)
                ):
                    found.append(
                        Contradiction(
                            field="tech_stack",
                            existing=f"rejected: {approach} ({reason})",
                            incoming=tech,
                            message=(
                                f"Proposed tech '{tech}' overlaps previously rejected "
                                f"approach '{approach}'."
                            ),
                        )
                    )
            if parsed.canonical and parsed.category and not parsed.ambiguous:
                conflict = conflicts_with_selection(
                    selections,
                    canonical=parsed.canonical,
                    category=parsed.category,
                )
                if conflict:
                    found.append(
                        Contradiction(
                            field="tech_stack",
                            existing=f"{conflict.category}: {conflict.selected}",
                            incoming=parsed.canonical,
                            message=(
                                f"Proposed {parsed.category} '{parsed.canonical}' conflicts with "
                                f"selected '{conflict.selected}'."
                            ),
                        )
                    )
            if parsed.ambiguous:
                found.append(
                    Contradiction(
                        field="tech_stack",
                        existing="(established stack)",
                        incoming=tech,
                        message=(
                            f"Ambiguous technology proposal '{tech}' cannot become a selection "
                            "until one option is chosen."
                        ),
                    )
                )

    if patch.add_decisions:
        for item in patch.add_decisions:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "")
            choice = str(item.get("choice") or "")
            for existing in project.decisions:
                if _overlap(title, existing.title) and choice and not _overlap(choice, existing.choice):
                    found.append(
                        Contradiction(
                            field="decisions",
                            existing=f"{existing.title}: {existing.choice}",
                            incoming=f"{title}: {choice}",
                            message=(
                                f"New decision '{title}' contradicts accepted decision "
                                f"'{existing.title}' ({existing.choice})."
                            ),
                        )
                    )
            for approach, reason in rejected_texts:
                if _overlap(choice, approach) or _overlap(title, approach):
                    found.append(
                        Contradiction(
                            field="decisions",
                            existing=f"rejected: {approach} ({reason})",
                            incoming=f"{title}: {choice}",
                            message=(
                                f"Proposed decision reintroduces rejected approach '{approach}'."
                            ),
                        )
                    )

    if patch.add_scope_in:
        for item in patch.add_scope_in:
            for out in project.scope_out:
                if _overlap(item, out):
                    found.append(
                        Contradiction(
                            field="scope",
                            existing=f"out of scope: {out}",
                            incoming=f"in scope: {item}",
                            message=f"'{item}' was previously marked out of scope.",
                        )
                    )

    if patch.add_scope_out:
        for item in patch.add_scope_out:
            for inn in project.scope_in:
                if _overlap(item, inn):
                    found.append(
                        Contradiction(
                            field="scope",
                            existing=f"in scope: {inn}",
                            incoming=f"out of scope: {item}",
                            message=f"'{item}' was previously marked in scope.",
                        )
                    )

    # Deduplicate by message
    seen: set[str] = set()
    unique: list[Contradiction] = []
    for c in found:
        if c.message not in seen:
            seen.add(c.message)
            unique.append(c)
    return unique


def _decision_dump(d: Decision) -> dict[str, Any]:
    return {
        "title": d.title,
        "choice": d.choice,
        "rationale": d.rationale,
        "status": getattr(d, "status", "accepted"),
    }


def retrieve_relevant_context(
    project: ProjectState,
    *,
    mode: BehaviouralMode | str,
    user_message: str = "",
    max_findings: int = 8,
    max_messages: int = 6,
) -> ContextBundle:
    """
    Retrieve only mode-relevant project context.

    Full message history is sent separately as multi-turn; this snapshot is the
    structured memory the model should treat as project truth.
    """
    canon = canonical_mode(mode)
    notes: list[str] = []

    base: dict[str, Any] = {
        "id": project.id,
        "name": project.name,
        "description": getattr(project, "description", "") or "",
        "objective": project.objective,
        "problem_statement": getattr(project, "problem_statement", "") or "",
        "intended_users": list(project.intended_users),
        "behavioural_mode": canon.value,
    }

    rejected = [
        {"approach": r.approach, "reason": r.reason}
        for r in getattr(project, "rejected_approaches", []) or []
    ]
    preferences = list(getattr(project, "preferences", []) or [])
    completed = list(getattr(project, "completed_milestones", []) or [])
    outstanding = list(getattr(project, "outstanding_tasks", []) or [])
    known_risks = list(getattr(project, "known_risks", []) or [])
    impl_status = getattr(project, "implementation_status", "") or ""

    # Always surface rejected approaches so the model does not re-suggest them
    base["rejected_approaches"] = rejected
    base["technology_selections"] = [
        s.model_dump(mode="json")
        for s in getattr(project, "technology_selections", []) or []
        if getattr(s, "status", "accepted") in {"accepted", "provisional", "unverified"}
    ]
    base["tech_stack"] = list(project.tech_stack)
    if rejected:
        notes.append("Do not reintroduce rejected approaches unless the user explicitly revisits them.")

    open_findings = [
        {
            "title": f.title,
            "severity": f.severity.value if hasattr(f.severity, "value") else f.severity,
            "challenged_claim": f.challenged_claim,
            "status": f.status.value if hasattr(f.status, "value") else f.status,
        }
        for f in project.findings
        if f.status == FindingStatus.OPEN
    ][:max_findings]

    accepted_risks = [
        {"title": f.title, "claim": f.challenged_claim}
        for f in project.findings
        if f.status == FindingStatus.ACCEPTED_RISK
    ][:max_findings]

    if canon == BehaviouralMode.EXPLORE:
        base.update(
            {
                "success_criteria": list(project.success_criteria),
                "assumptions": [a.statement for a in project.assumptions if not a.evidence],
                "open_questions": [
                    q.text for q in project.open_questions if not q.answered
                ],
                "preferences": preferences,
                "constraints": [c.text for c in project.constraints],
            }
        )
    elif canon == BehaviouralMode.PLAN:
        base.update(
            {
                "success_criteria": list(project.success_criteria),
                "functional_requirements": [r.text for r in project.functional_requirements],
                "non_functional_requirements": [
                    r.text for r in project.non_functional_requirements
                ],
                "scope_in": list(project.scope_in),
                "scope_out": list(project.scope_out),
                "constraints": [
                    {"text": c.text, "category": c.category} for c in project.constraints
                ],
                "decisions": [_decision_dump(d) for d in project.decisions],
                "assumptions": [a.statement for a in project.assumptions],
                "tech_stack": list(project.tech_stack),
                "architecture_notes": project.architecture_notes,
                "milestones": list(project.milestones),
                "open_findings": open_findings,
                "preferences": preferences,
                "known_risks": known_risks,
            }
        )
    elif canon == BehaviouralMode.BUILD:
        base.update(
            {
                "functional_requirements": [
                    {
                        "text": r.text,
                        "acceptance_criteria": list(r.acceptance_criteria),
                    }
                    for r in project.functional_requirements
                ],
                "non_functional_requirements": [
                    r.text for r in project.non_functional_requirements
                ],
                "scope_in": list(project.scope_in),
                "scope_out": list(project.scope_out),
                "constraints": [c.text for c in project.constraints],
                "decisions": [_decision_dump(d) for d in project.decisions],
                "tech_stack": list(project.tech_stack),
                "architecture_notes": project.architecture_notes,
                "data_model_notes": project.data_model_notes,
                "security_notes": project.security_notes,
                "testing_notes": project.testing_notes,
                "milestones": list(project.milestones),
                "completed_milestones": completed,
                "outstanding_tasks": outstanding,
                "implementation_status": impl_status,
                "accepted_risks": accepted_risks,
                "open_findings": open_findings,
                "preferences": preferences,
            }
        )
        if open_findings:
            notes.append(
                "Open material findings remain — do not claim readiness without addressing them."
            )
    elif canon == BehaviouralMode.REVIEW:
        base.update(
            {
                "functional_requirements": [r.text for r in project.functional_requirements],
                "scope_in": list(project.scope_in),
                "scope_out": list(project.scope_out),
                "decisions": [_decision_dump(d) for d in project.decisions],
                "tech_stack": list(project.tech_stack),
                "architecture_notes": project.architecture_notes,
                "security_notes": project.security_notes,
                "constraints": [c.text for c in project.constraints],
                "assumptions": [a.statement for a in project.assumptions],
                "open_findings": open_findings,
                "accepted_risks": accepted_risks,
                "known_risks": known_risks,
            }
        )
    elif canon == BehaviouralMode.DEBUG:
        base.update(
            {
                "tech_stack": list(project.tech_stack),
                "architecture_notes": project.architecture_notes,
                "data_model_notes": project.data_model_notes,
                "implementation_status": impl_status,
                "outstanding_tasks": outstanding,
                "known_risks": known_risks,
                "open_findings": open_findings,
                "decisions": [_decision_dump(d) for d in project.decisions],
                "recent_error_cues": _extract_error_cues(user_message),
            }
        )
        notes.append("Ground root-cause hypotheses in the reported failure evidence.")
    else:
        base.update(
            {
                "success_criteria": list(project.success_criteria),
                "decisions": [_decision_dump(d) for d in project.decisions],
                "tech_stack": list(project.tech_stack),
                "open_questions": [
                    q.text for q in project.open_questions if not q.answered
                ],
            }
        )

    # Compact recent messages for continuity (full history still sent as turns)
    base["recent_messages"] = [
        {"role": m.role, "content": sanitize_untrusted_text(m.content[:400])}
        for m in project.messages[-max_messages:]
    ]

    return ContextBundle(mode=canon, snapshot=base, notes=notes)


def _extract_error_cues(message: str) -> list[str]:
    cues: list[str] = []
    for line in (message or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(
            k in lower
            for k in (
                "error",
                "exception",
                "traceback",
                "failed",
                "errno",
                "typeerror",
                "valueerror",
                "panic",
                "fatal",
            )
        ):
            cues.append(stripped[:300])
    return cues[:12]


def project_context_view(project: ProjectState) -> dict[str, Any]:
    """Full inspectable context for users (no message bodies beyond counts)."""
    return {
        "id": project.id,
        "name": project.name,
        "description": getattr(project, "description", "") or "",
        "objective": project.objective,
        "problem_statement": getattr(project, "problem_statement", "") or "",
        "intended_users": list(project.intended_users),
        "success_criteria": list(project.success_criteria),
        "functional_requirements": [r.model_dump(mode="json") for r in project.functional_requirements],
        "non_functional_requirements": [
            r.model_dump(mode="json") for r in project.non_functional_requirements
        ],
        "scope_in": list(project.scope_in),
        "scope_out": list(project.scope_out),
        "constraints": [c.model_dump(mode="json") for c in project.constraints],
        "decisions": [d.model_dump(mode="json") for d in project.decisions],
        "assumptions": [a.model_dump(mode="json") for a in project.assumptions],
        "open_questions": [q.model_dump(mode="json") for q in project.open_questions],
        "tech_stack": list(project.tech_stack),
        "technology_selections": [
            s.model_dump(mode="json")
            for s in getattr(project, "technology_selections", []) or []
        ],
        "architecture_notes": project.architecture_notes,
        "architecture_note_history": [
            h.model_dump(mode="json")
            for h in getattr(project, "architecture_note_history", []) or []
        ],
        "data_model_notes": project.data_model_notes,
        "security_notes": project.security_notes,
        "testing_notes": project.testing_notes,
        "milestones": list(project.milestones),
        "preferences": list(getattr(project, "preferences", []) or []),
        "rejected_approaches": [
            r.model_dump(mode="json")
            for r in getattr(project, "rejected_approaches", []) or []
        ],
        "implementation_status": getattr(project, "implementation_status", "") or "",
        "completed_milestones": list(getattr(project, "completed_milestones", []) or []),
        "outstanding_tasks": list(getattr(project, "outstanding_tasks", []) or []),
        "known_risks": list(getattr(project, "known_risks", []) or []),
        "behavioural_mode": (
            project.behavioural_mode.value
            if hasattr(project.behavioural_mode, "value")
            else project.behavioural_mode
        ),
        "open_finding_count": len(project.open_findings()),
        "message_count": len(project.messages),
        "conversation_summary": (
            project.conversation_summary.model_dump(mode="json")
            if getattr(project, "conversation_summary", None)
            else None
        ),
        "working_memory": (
            project.working_memory.model_dump(mode="json")
            if getattr(project, "working_memory", None)
            else None
        ),
    }


def apply_manual_context_update(
    project: ProjectState,
    updates: dict[str, Any],
) -> tuple[ProjectState, list[str]]:
    """
    Allow users to inspect/correct stored context.
    Returns (project, list of applied field names).
    """
    from app.grill.notes import apply_note_update
    from app.grill.tech import (
        apply_technology_tokens,
        hydrate_selections_from_legacy,
        stack_from_selections,
    )

    applied: list[str] = []

    str_fields = (
        "name",
        "description",
        "objective",
        "problem_statement",
        "implementation_status",
    )
    for key in str_fields:
        if key in updates and updates[key] is not None:
            setattr(project, key, str(updates[key])[:4000])
            applied.append(key)

    # Long-form notes: explicit manual updates are intentional replacements
    for note_field in (
        "architecture_notes",
        "data_model_notes",
        "security_notes",
        "testing_notes",
    ):
        if note_field in updates and updates[note_field] is not None:
            result = apply_note_update(
                field=note_field,
                existing=getattr(project, note_field) or "",
                incoming=str(updates[note_field])[:4000],
                mode="replace",
            )
            setattr(project, note_field, result.value)
            if note_field == "architecture_notes":
                project.architecture_note_history.extend(result.history_append)
            else:
                project.note_history.extend(result.history_append)
            applied.append(note_field)

    list_str_fields = (
        "intended_users",
        "success_criteria",
        "scope_in",
        "scope_out",
        "milestones",
        "preferences",
        "completed_milestones",
        "outstanding_tasks",
        "known_risks",
    )
    for key in list_str_fields:
        if key in updates and updates[key] is not None:
            raw = updates[key]
            if not isinstance(raw, list):
                continue
            cleaned = [str(x).strip()[:500] for x in raw if str(x).strip()]
            setattr(project, key, cleaned)
            applied.append(key)

    if "tech_stack" in updates and updates["tech_stack"] is not None:
        raw = updates["tech_stack"]
        if isinstance(raw, list):
            project.technology_selections = hydrate_selections_from_legacy(
                selections=project.technology_selections,
                tech_stack=project.tech_stack,
                decisions=project.decisions,
            )
            # Manual edits are explicit user corrections → allow category replace
            sels, _applied, _cons, _deferred = apply_technology_tokens(
                project.technology_selections,
                [str(x).strip() for x in raw if str(x).strip()],
                reason="manual context update",
                explicit_replace=True,
                rejected_names=[r.approach for r in project.rejected_approaches],
            )
            project.technology_selections = sels
            project.tech_stack = stack_from_selections(sels)
            # Keep database decision aligned when user explicitly changes DB tech
            for sel in sels:
                if sel.category == "database" and sel.status == "accepted":
                    existing = next(
                        (
                            d
                            for d in project.decisions
                            if d.title.lower() in {"database", "datastore", "primary datastore"}
                            and d.status != "superseded"
                        ),
                        None,
                    )
                    if existing and existing.choice != sel.selected:
                        existing.status = "superseded"
                        from app.projects.models import Decision, DecisionStatus

                        project.decisions.append(
                            Decision(
                                title=existing.title,
                                choice=sel.selected,
                                rationale="Updated via manual context edit",
                                status=DecisionStatus.CONFIRMED.value,
                                source="manual_context",
                                alternatives_considered=list(
                                    dict.fromkeys(
                                        (existing.alternatives_considered or [])
                                        + [existing.choice]
                                    )
                                ),
                            )
                        )
                    elif not existing:
                        from app.projects.models import Decision, DecisionStatus

                        project.decisions.append(
                            Decision(
                                title="Database",
                                choice=sel.selected,
                                rationale="Updated via manual context edit",
                                status=DecisionStatus.CONFIRMED.value,
                                source="manual_context",
                            )
                        )
            applied.append("tech_stack")

    if "rejected_approaches" in updates and updates["rejected_approaches"] is not None:
        items: list[RejectedApproach] = []
        for raw in updates["rejected_approaches"]:
            if isinstance(raw, dict):
                approach = str(raw.get("approach") or "").strip()
                reason = str(raw.get("reason") or "").strip()
                if approach:
                    items.append(RejectedApproach(approach=approach[:500], reason=reason[:1000]))
            elif isinstance(raw, str) and raw.strip():
                items.append(RejectedApproach(approach=raw.strip()[:500]))
        project.rejected_approaches = items
        applied.append("rejected_approaches")

    project.touch()
    return project, applied


def filter_brainstorm_patch(patch: StatePatch, mode: BehaviouralMode | str) -> StatePatch:
    """
    In EXPLORE, demote clearly provisional ideas to assumptions.
    Confirmed decisions (default) are preserved so architecture choices stick.
    """
    canon = canonical_mode(mode)
    if canon != BehaviouralMode.EXPLORE:
        return patch
    if not patch.add_decisions:
        return patch

    confirmed: list[dict[str, Any]] = []
    assumptions = list(patch.add_assumptions or [])
    provisional_markers = ("maybe", "perhaps", "consider", "could use", "might use", "idea:")

    for item in patch.add_decisions:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        choice = str(item.get("choice") or "")
        status = str(item.get("status") or "confirmed").lower()
        blob = f"{title} {choice}".lower()
        # Explicit mentor/proposed statuses demote; missing status stays confirmable
        provisional = status in {
            "provisional",
            "provisionally_accepted",
            "proposed",
            "unverified",
        } or any(m in blob for m in provisional_markers)
        if provisional:
            assumptions.append(
                f"Provisional idea (not confirmed): {title} — {choice}".strip(" —")
            )
        else:
            confirmed.append(item)

    return patch.model_copy(
        update={
            "add_decisions": confirmed or None,
            "add_assumptions": assumptions or None,
        }
    )
