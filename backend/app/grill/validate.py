"""Validate model responses against the selected mentoring mode."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.grill.modes import BehaviouralMode, canonical_mode
from app.providers.base import PrimaryAnalysis


@dataclass
class ModeValidation:
    ok: bool = True
    warnings: list[str] = field(default_factory=list)
    adjusted_reply: str | None = None


_BUILD_PREMATURE = re.compile(
    r"\b(here('s| is) (your |the )?(full )?implementation|copy[- ]paste this (into|to)|"
    r"create these files now|scaffold the entire)\b",
    re.I,
)
_RESTART_IDEATION = re.compile(
    r"\b(let'?s start (over|from scratch)|what (project|product) (do you|would you) "
    r"(want|like) to build|tell me about your idea from the beginning)\b",
    re.I,
)


def validate_analysis_for_mode(
    analysis: PrimaryAnalysis,
    *,
    mode: BehaviouralMode | str,
    has_objective: bool,
    readiness_ready: bool,
) -> ModeValidation:
    """
    Lightweight post-checks. Does not invent content — only flags / lightly annotates.
    """
    canon = canonical_mode(mode)
    warnings: list[str] = []
    reply = (analysis.reply or "").strip()
    adjusted: str | None = None

    if canon == BehaviouralMode.BUILD and not readiness_ready:
        if _BUILD_PREMATURE.search(reply):
            warnings.append("BUILD attempted premature implementation guidance while not ready.")
            note = (
                "\n\n_(Grill note: critical requirements or blockers remain unresolved — "
                "resolve those before treating this as an implementation prompt.)_"
            )
            if note.strip() not in reply:
                adjusted = reply + note

    if has_objective and _RESTART_IDEATION.search(reply):
        warnings.append("Response attempted to restart ideation despite established objective.")
        if adjusted is None:
            adjusted = reply

    if canon == BehaviouralMode.EXPLORE and analysis.findings:
        # Soft: explore may emit findings only for material risks — leave as-is
        pass

    if canon in {BehaviouralMode.EXPLORE, BehaviouralMode.PLAN, BehaviouralMode.BUILD}:
        # Discourage dumping large finding sets outside review
        if len(analysis.findings) > 3:
            warnings.append(f"{canon.value} produced many findings; prefer REVIEW for deep critique.")

    return ModeValidation(
        ok=len(warnings) == 0,
        warnings=warnings,
        adjusted_reply=adjusted,
    )
