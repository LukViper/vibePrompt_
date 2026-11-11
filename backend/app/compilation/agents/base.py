"""Shared structures for agent-specific prompt compilers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentFamily(str, Enum):
    CURSOR = "cursor"
    ANTIGRAVITY = "antigravity"
    CODEX = "codex"


def normalize_agent(value: str | None) -> AgentFamily:
    raw = (value or "cursor").strip().lower()
    aliases = {
        "cursor": AgentFamily.CURSOR,
        "cursor-agent": AgentFamily.CURSOR,
        "antigravity": AgentFamily.ANTIGRAVITY,
        "google-antigravity": AgentFamily.ANTIGRAVITY,
        "agy": AgentFamily.ANTIGRAVITY,
        "codex": AgentFamily.CODEX,
        "openai-codex": AgentFamily.CODEX,
        "codex-cli": AgentFamily.CODEX,
    }
    return aliases.get(raw, AgentFamily.CURSOR)


@dataclass
class AgentCompileInput:
    project_name: str
    task: str
    objective: str
    problem: str
    description: str
    users: list[str]
    tech_stack: list[str]
    constraints: list[str]
    decisions: list[str]
    architecture_notes: str
    data_model_notes: str
    security_notes: str
    scope_in: list[str]
    scope_out: list[str]
    functional_requirements: list[str]
    non_functional_requirements: list[str]
    acceptance: list[str]
    verification: list[str]
    rejected: list[str]
    outstanding: list[str]
    completed: list[str]
    milestones: list[str]
    open_findings: list[str]
    accepted_risks: list[str]
    skill_block: str = ""
    skill_reasons: dict[str, str] = field(default_factory=dict)
    refine_notes: str = ""
    readiness_status: str = "ready"
    extra: dict[str, Any] = field(default_factory=dict)


def bullets(items: list[str], empty: str = "(none recorded)") -> str:
    if not items:
        return empty
    return "\n".join(f"- {i}" for i in items)


def common_context_sections(payload: AgentCompileInput) -> list[str]:
    parts = [
        "## Project context",
        f"**Objective:** {payload.objective or '(missing)'}",
    ]
    if payload.problem:
        parts.append(f"**Problem:** {payload.problem}")
    if payload.description:
        parts.append(f"**Description:** {payload.description}")
    parts.append(
        f"**Target users:** {', '.join(payload.users) or '(unspecified)'}"
    )
    parts.extend(
        [
            "",
            "## Technical constraints",
            f"**Tech stack:** {', '.join(payload.tech_stack) or '(not specified — do not invent a stack)'}",
            bullets(payload.constraints, empty="- (none)"),
            "",
            "## Architecture decisions (follow these)",
            bullets(
                payload.decisions,
                empty="- (none recorded — ask before inventing architecture)",
            ),
            "",
        ]
    )
    if payload.architecture_notes:
        parts.extend(["### Architecture notes", payload.architecture_notes, ""])
    if payload.data_model_notes:
        parts.extend(["### Data model", payload.data_model_notes, ""])
    if payload.security_notes:
        parts.extend(["### Security", payload.security_notes, ""])
    parts.extend(
        [
            "## Implementation requirements",
            "**In scope:**",
            bullets(payload.scope_in),
            "",
            "**Functional requirements:**",
            bullets(payload.functional_requirements),
            "",
            "**Non-functional requirements:**",
            bullets(payload.non_functional_requirements),
            "",
            "## Acceptance criteria",
            bullets(
                payload.acceptance,
                empty="- Define with the user before treating done",
            ),
            "",
        ]
    )
    out_of_scope = list(payload.scope_out) + [
        "Do not reintroduce rejected approaches",
        "Do not add unrelated features beyond the stated task",
        "Do not invent APIs, libraries, or credentials not listed in context",
    ]
    if payload.rejected:
        out_of_scope.extend(f"Rejected: {r}" for r in payload.rejected)
    parts.extend(
        [
            "## Out of scope / prohibited changes",
            bullets(out_of_scope),
            "",
            "## Verification steps",
            bullets(payload.verification),
            "",
        ]
    )
    if payload.accepted_risks:
        parts.extend(
            [
                "## Explicitly accepted risks",
                bullets(payload.accepted_risks),
                "",
            ]
        )
    if payload.open_findings:
        parts.extend(
            [
                "## Open concerns (address or escalate — do not ignore)",
                bullets(payload.open_findings),
                "",
            ]
        )
    if payload.milestones or payload.completed or payload.outstanding:
        parts.append("## Progress")
        if payload.milestones:
            parts.append("**Milestones:**")
            parts.append(bullets(payload.milestones))
        if payload.completed:
            parts.append("**Completed:**")
            parts.append(bullets(payload.completed))
        if payload.outstanding:
            parts.append("**Outstanding:**")
            parts.append(bullets(payload.outstanding))
        parts.append("")
    if payload.skill_block:
        parts.extend(
            [
                "## Book-informed guidance (abstracted principles — not copyrighted text)",
                payload.skill_block,
                "",
            ]
        )
        if payload.skill_reasons:
            parts.append("### Why these skills were selected")
            parts.append(
                bullets(
                    [f"{slug}: {reason}" for slug, reason in payload.skill_reasons.items()]
                )
            )
            parts.append("")
    if payload.refine_notes:
        parts.extend(["## User refinement notes", payload.refine_notes.strip(), ""])
    if payload.readiness_status == "ready_with_accepted_risks":
        parts.append(
            "_Readiness: ready with explicitly accepted risks. "
            "Do not reopen accepted risks without new evidence._"
        )
        parts.append("")
    return parts
