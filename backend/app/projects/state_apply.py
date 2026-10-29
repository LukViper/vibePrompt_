"""Deterministically validate and apply model-proposed state patches."""

from __future__ import annotations

from app.projects.models import (
    Assumption,
    Constraint,
    Decision,
    OpenQuestion,
    ProjectState,
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
        # Store as data with a marker; never treat as instructions
        text = f"[flagged content] {text}"
    return text[:max_len]


def apply_state_patch(project: ProjectState, patch: StatePatch) -> ProjectState:
    if patch.objective:
        cleaned = _clean_text(patch.objective, max_len=2000)
        if cleaned and not project.objective:
            project.objective = cleaned

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
            if cleaned:
                project.functional_requirements.append(Requirement(text=cleaned, kind="functional"))

    if patch.add_non_functional_requirements:
        for r in patch.add_non_functional_requirements:
            cleaned = _clean_text(r)
            if cleaned:
                project.non_functional_requirements.append(
                    Requirement(text=cleaned, kind="non_functional")
                )

    if patch.add_scope_in:
        for s in patch.add_scope_in:
            cleaned = _clean_text(s, max_len=500)
            if cleaned and cleaned not in project.scope_in:
                project.scope_in.append(cleaned)

    if patch.add_scope_out:
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
            category = str(item.get("category") or "general")[:40]
            project.constraints.append(Constraint(text=text, category=category))

    if patch.add_decisions:
        for item in patch.add_decisions:
            if not isinstance(item, dict):
                continue
            title = _clean_text(str(item.get("title") or ""), max_len=200)
            choice = _clean_text(str(item.get("choice") or ""), max_len=500)
            if not title or not choice:
                continue
            rationale = _clean_text(str(item.get("rationale") or ""), max_len=1000) or ""
            project.decisions.append(
                Decision(title=title, choice=choice, rationale=rationale)
            )

    if patch.add_assumptions:
        for a in patch.add_assumptions:
            cleaned = _clean_text(a)
            if cleaned:
                project.assumptions.append(Assumption(statement=cleaned))

    if patch.add_open_questions:
        for q in patch.add_open_questions:
            cleaned = _clean_text(q, max_len=500)
            if cleaned:
                project.open_questions.append(OpenQuestion(text=cleaned))

    if patch.tech_stack:
        for t in patch.tech_stack:
            cleaned = _clean_text(t, max_len=80)
            if cleaned and cleaned not in project.tech_stack:
                project.tech_stack.append(cleaned)

    if patch.architecture_notes:
        cleaned = _clean_text(patch.architecture_notes, max_len=4000)
        if cleaned:
            project.architecture_notes = cleaned

    if patch.data_model_notes:
        cleaned = _clean_text(patch.data_model_notes, max_len=4000)
        if cleaned:
            project.data_model_notes = cleaned

    if patch.security_notes:
        cleaned = _clean_text(patch.security_notes, max_len=4000)
        if cleaned:
            project.security_notes = cleaned

    if patch.testing_notes:
        cleaned = _clean_text(patch.testing_notes, max_len=4000)
        if cleaned:
            project.testing_notes = cleaned

    if patch.milestones:
        for m in patch.milestones:
            cleaned = _clean_text(m, max_len=300)
            if cleaned and cleaned not in project.milestones:
                project.milestones.append(cleaned)

    project.touch()
    return project
