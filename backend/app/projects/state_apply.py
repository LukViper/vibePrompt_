"""Deterministically validate and apply model-proposed state patches."""

from __future__ import annotations

from app.grill.context import detect_contradictions, filter_brainstorm_patch
from app.grill.modes import BehaviouralMode
from app.grill.notes import apply_note_update
from app.grill.tech import (
    apply_technology_tokens,
    hydrate_selections_from_legacy,
    stack_from_selections,
)
from app.grill.decisions import apply_decision_dict
from app.projects.models import (
    Assumption,
    AssumptionClassification,
    Constraint,
    OpenQuestion,
    ProjectState,
    RejectedApproach,
    Requirement,
)
from app.providers.base import StatePatch
from app.providers.json_utils import INJECTION_MARKERS


def _clean_text(value: str, *, max_len: int = 2000) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    lower = text.lower()
    if any(m in lower for m in INJECTION_MARKERS):
        text = f"[flagged content] {text}"
    return text[:max_len]


def _already_has_requirement(project: ProjectState, text: str, kind: str) -> bool:
    bucket = (
        project.functional_requirements
        if kind == "functional"
        else project.non_functional_requirements
    )
    needle = text.lower()
    return any(r.text.lower() == needle for r in bucket)


def _already_has_assumption(project: ProjectState, text: str) -> bool:
    needle = text.lower()
    return any(a.statement.lower() == needle for a in project.assumptions)


def _already_has_question(project: ProjectState, text: str) -> bool:
    needle = text.lower()
    return any(q.text.lower() == needle for q in project.open_questions)


def _sync_tech_stack(project: ProjectState) -> None:
    project.tech_stack = stack_from_selections(project.technology_selections)


def _apply_long_note(
    project: ProjectState,
    *,
    field: str,
    incoming: str | None,
    mode: str | None,
) -> list[str]:
    msgs: list[str] = []
    if not incoming:
        return msgs
    cleaned = _clean_text(incoming, max_len=4000)
    if not cleaned:
        return msgs
    current = getattr(project, field) or ""
    result = apply_note_update(
        field=field, existing=current, incoming=cleaned, mode=mode
    )
    setattr(project, field, result.value)
    if field == "architecture_notes":
        project.architecture_note_history.extend(result.history_append)
    else:
        project.note_history.extend(result.history_append)
    if result.contradiction:
        msgs.append(result.contradiction)
        q = f"Resolve contradiction: {result.contradiction}"
        if not _already_has_question(project, q):
            project.open_questions.append(OpenQuestion(text=q, priority="high"))
    return msgs


def apply_state_patch(
    project: ProjectState,
    patch: StatePatch,
    *,
    mode: BehaviouralMode | str | None = None,
    allow_contradictions: bool = False,
) -> tuple[ProjectState, list[str]]:
    """
    Apply a validated state patch.

    Returns (project, contradiction_messages).
    """
    if mode is not None:
        patch = filter_brainstorm_patch(patch, mode)

    # Bootstrap structured tech from legacy flat stack/decisions when needed
    project.technology_selections = hydrate_selections_from_legacy(
        selections=project.technology_selections,
        tech_stack=project.tech_stack,
        decisions=project.decisions,
    )
    if project.technology_selections and not project.tech_stack:
        _sync_tech_stack(project)

    contradictions = detect_contradictions(project, patch)
    contradiction_msgs = [c.message for c in contradictions]
    blocked_fields = {c.field for c in contradictions} if not allow_contradictions else set()

    if patch.objective:
        cleaned = _clean_text(patch.objective, max_len=2000)
        if cleaned and not project.objective:
            project.objective = cleaned
        elif cleaned and project.objective and cleaned.lower() != project.objective.lower():
            if "objective" not in blocked_fields:
                q = f"Confirm updated objective: {cleaned}"
                if not _already_has_question(project, q):
                    project.open_questions.append(OpenQuestion(text=q, priority="high"))

    if patch.description:
        cleaned = _clean_text(patch.description, max_len=2000)
        if cleaned and not project.description:
            project.description = cleaned

    if patch.problem_statement:
        cleaned = _clean_text(patch.problem_statement, max_len=2000)
        if cleaned and not project.problem_statement:
            project.problem_statement = cleaned

    if patch.intended_users:
        for u in patch.intended_users:
            cleaned = _clean_text(u, max_len=200)
            if cleaned and cleaned not in project.intended_users:
                project.intended_users.append(cleaned)

    if patch.success_criteria:
        for c in patch.success_criteria:
            cleaned = _clean_text(c, max_len=500)
            if cleaned and cleaned not in project.success_criteria:
                project.success_criteria.append(cleaned)

    if patch.add_functional_requirements:
        for r in patch.add_functional_requirements:
            cleaned = _clean_text(r)
            if cleaned and not _already_has_requirement(project, cleaned, "functional"):
                project.functional_requirements.append(Requirement(text=cleaned, kind="functional"))

    if patch.add_non_functional_requirements:
        for r in patch.add_non_functional_requirements:
            cleaned = _clean_text(r)
            if cleaned and not _already_has_requirement(project, cleaned, "non_functional"):
                project.non_functional_requirements.append(
                    Requirement(text=cleaned, kind="non_functional")
                )

    if patch.add_scope_in and "scope" not in blocked_fields:
        for s in patch.add_scope_in:
            cleaned = _clean_text(s, max_len=500)
            if cleaned and cleaned not in project.scope_in:
                project.scope_in.append(cleaned)

    if patch.add_scope_out and "scope" not in blocked_fields:
        for s in patch.add_scope_out:
            cleaned = _clean_text(s, max_len=500)
            if cleaned and cleaned not in project.scope_out:
                project.scope_out.append(cleaned)

    if patch.add_constraints:
        for item in patch.add_constraints:
            if not isinstance(item, dict):
                continue
            text = _clean_text(str(item.get("text") or item.get("constraint") or ""))
            if not text:
                continue
            if any(c.text.lower() == text.lower() for c in project.constraints):
                continue
            category = str(item.get("category") or "general")[:40]
            project.constraints.append(Constraint(text=text, category=category))

    if patch.add_decisions and "decisions" not in blocked_fields:
        for item in patch.add_decisions:
            if not isinstance(item, dict):
                continue
            title = _clean_text(str(item.get("title") or ""), max_len=200)
            choice = _clean_text(str(item.get("choice") or ""), max_len=500)
            if not title or not choice:
                continue
            rationale = _clean_text(str(item.get("rationale") or ""), max_len=1000) or ""
            payload = {
                **item,
                "title": title,
                "choice": choice,
                "rationale": rationale,
            }
            explicit_replace = bool(item.get("replace") or allow_contradictions)
            _dec, conflict = apply_decision_dict(
                project,
                payload,
                allow_replace=explicit_replace,
            )
            if conflict:
                contradiction_msgs.append(conflict)

    if patch.add_assumptions:
        for a in patch.add_assumptions:
            cleaned = _clean_text(a)
            if cleaned and not _already_has_assumption(project, cleaned):
                project.assumptions.append(
                    Assumption(
                        statement=cleaned,
                        classification=AssumptionClassification.UNVERIFIED,
                        source="state_patch",
                    )
                )

    if patch.add_open_questions:
        for q in patch.add_open_questions:
            cleaned = _clean_text(q, max_len=500)
            if cleaned and not _already_has_question(project, cleaned):
                project.open_questions.append(OpenQuestion(text=cleaned))

    if patch.add_preferences:
        for p in patch.add_preferences:
            cleaned = _clean_text(p, max_len=500)
            if cleaned and cleaned not in project.preferences:
                project.preferences.append(cleaned)

    if patch.add_rejected_approaches:
        for item in patch.add_rejected_approaches:
            if not isinstance(item, dict):
                continue
            approach = _clean_text(str(item.get("approach") or ""), max_len=500)
            if not approach:
                continue
            if any(r.approach.lower() == approach.lower() for r in project.rejected_approaches):
                continue
            reason = _clean_text(str(item.get("reason") or ""), max_len=1000) or ""
            project.rejected_approaches.append(
                RejectedApproach(approach=approach, reason=reason)
            )
            # Also mark on matching technology selections
            for sel in project.technology_selections:
                if sel.selected.lower() == approach.lower() and sel.status == "accepted":
                    sel.status = "superseded"
                if approach not in sel.rejected:
                    # Only attach if same category-ish name match
                    if approach.lower() in (sel.selected.lower(),) or any(
                        approach.lower() == a.lower() for a in sel.alternatives
                    ):
                        sel.rejected.append(approach)

    if patch.add_known_risks:
        for risk in patch.add_known_risks:
            cleaned = _clean_text(risk, max_len=500)
            if cleaned and cleaned not in project.known_risks:
                project.known_risks.append(cleaned)

    if patch.add_outstanding_tasks:
        for task in patch.add_outstanding_tasks:
            cleaned = _clean_text(task, max_len=500)
            if cleaned and cleaned not in project.outstanding_tasks:
                project.outstanding_tasks.append(cleaned)

    if patch.add_completed_milestones:
        for m in patch.add_completed_milestones:
            cleaned = _clean_text(m, max_len=300)
            if not cleaned:
                continue
            if cleaned not in project.completed_milestones:
                project.completed_milestones.append(cleaned)
            project.outstanding_tasks = [
                t for t in project.outstanding_tasks if t.lower() != cleaned.lower()
            ]

    # Structured technology selections from explicit patch entries
    if patch.add_technology_selections:
        for item in patch.add_technology_selections:
            if not isinstance(item, dict):
                continue
            selected = _clean_text(str(item.get("selected") or ""), max_len=80)
            category = str(item.get("category") or "other")[:40]
            if not selected:
                continue
            explicit = bool(item.get("replace") or patch.replace_technology)
            sels, _applied, cons, deferred = apply_technology_tokens(
                project.technology_selections,
                [selected],
                reason=_clean_text(str(item.get("reason") or ""), max_len=500) or "",
                explicit_replace=explicit or allow_contradictions,
            )
            project.technology_selections = sels
            contradiction_msgs.extend(cons)
            for d in deferred:
                if not _already_has_question(project, d):
                    project.open_questions.append(OpenQuestion(text=d, priority="medium"))

    # Flat tech_stack tokens — always validated; conflicts become alternatives + messages
    if patch.tech_stack:
        explicit = bool(patch.replace_technology) or allow_contradictions
        sels, _applied, cons, deferred = apply_technology_tokens(
            project.technology_selections,
            list(patch.tech_stack),
            reason="state_patch.tech_stack",
            explicit_replace=explicit,
            rejected_names=[r.approach for r in project.rejected_approaches],
        )
        project.technology_selections = sels
        contradiction_msgs.extend(cons)
        for d in deferred:
            if not _already_has_question(project, d):
                project.open_questions.append(OpenQuestion(text=d, priority="medium"))

    _sync_tech_stack(project)

    contradiction_msgs.extend(
        _apply_long_note(
            project,
            field="architecture_notes",
            incoming=patch.architecture_notes,
            mode=patch.architecture_notes_mode,
        )
    )
    contradiction_msgs.extend(
        _apply_long_note(
            project,
            field="data_model_notes",
            incoming=patch.data_model_notes,
            mode=patch.data_model_notes_mode,
        )
    )
    contradiction_msgs.extend(
        _apply_long_note(
            project,
            field="security_notes",
            incoming=patch.security_notes,
            mode=patch.security_notes_mode,
        )
    )
    contradiction_msgs.extend(
        _apply_long_note(
            project,
            field="testing_notes",
            incoming=patch.testing_notes,
            mode=patch.testing_notes_mode,
        )
    )

    if patch.milestones:
        for m in patch.milestones:
            cleaned = _clean_text(m, max_len=300)
            if cleaned and cleaned not in project.milestones:
                project.milestones.append(cleaned)

    if patch.implementation_status:
        cleaned = _clean_text(patch.implementation_status, max_len=1000)
        if cleaned:
            project.implementation_status = cleaned

    # Deduplicate contradiction messages; surface as open questions
    seen: set[str] = set()
    unique_msgs: list[str] = []
    for msg in contradiction_msgs:
        if msg not in seen:
            seen.add(msg)
            unique_msgs.append(msg)
    for msg in unique_msgs:
        q = f"Resolve contradiction: {msg}"
        if not _already_has_question(project, q):
            project.open_questions.append(OpenQuestion(text=q, priority="high"))

    project.touch()
    return project, unique_msgs


def apply_state_patch_legacy(project: ProjectState, patch: StatePatch) -> ProjectState:
    updated, _ = apply_state_patch(project, patch)
    return updated
