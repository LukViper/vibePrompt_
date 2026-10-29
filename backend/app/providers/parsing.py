"""Shared parsing of model JSON into application contracts."""

from __future__ import annotations

from app.providers.base import (
    CandidateFinding,
    CriticFindingAction,
    CriticReview,
    PrimaryAnalysis,
    ProviderError,
    ProviderErrorKind,
    StatePatch,
)
from app.providers.json_utils import extract_json_object


def parse_primary_analysis(text: str) -> PrimaryAnalysis:
    try:
        raw = extract_json_object(text)
    except ValueError as exc:
        raise ProviderError(ProviderErrorKind.MALFORMED, str(exc)) from exc

    findings: list[CandidateFinding] = []
    for item in raw.get("findings") or []:
        if not isinstance(item, dict):
            continue
        try:
            findings.append(CandidateFinding.model_validate(item))
        except Exception:
            continue

    patch_data = raw.get("state_patch") or {}
    try:
        patch = StatePatch.model_validate(patch_data if isinstance(patch_data, dict) else {})
    except Exception:
        patch = StatePatch()

    return PrimaryAnalysis(
        reply=str(raw.get("reply") or "").strip()
        or "I need a bit more concrete detail before I can challenge this usefully.",
        intent=str(raw.get("intent") or "general"),
        findings=findings,
        most_important_question=raw.get("most_important_question"),
        state_patch=patch,
    )


def parse_critic_review(text: str) -> CriticReview:
    try:
        raw = extract_json_object(text)
    except ValueError as exc:
        raise ProviderError(ProviderErrorKind.MALFORMED, str(exc)) from exc

    actions: list[CriticFindingAction] = []
    for item in raw.get("actions") or []:
        if not isinstance(item, dict):
            continue
        revised = None
        if isinstance(item.get("revised"), dict):
            try:
                revised = CandidateFinding.model_validate(item["revised"])
            except Exception:
                revised = None
        try:
            actions.append(
                CriticFindingAction(
                    finding_index=item.get("finding_index"),
                    action=str(item.get("action") or "insufficient_evidence"),
                    revised=revised,
                    notes=str(item.get("notes") or ""),
                )
            )
        except Exception:
            continue

    return CriticReview(
        actions=actions,
        overall_notes=str(raw.get("overall_notes") or ""),
        insufficient_context=bool(raw.get("insufficient_context")),
    )
