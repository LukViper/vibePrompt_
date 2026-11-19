"""Cursor / Codex / Antigravity readiness-gate injection contract."""

from __future__ import annotations

from typing import Any

from app.compilation.readiness import assess_readiness
from app.projects.models import ProjectState


def build_gate_status(project: ProjectState) -> dict[str, Any]:
    """
    Plugin-facing payload: inject before agent implementation runs.

    Agents should refuse to implement when `allow_implementation` is false
    unless the user explicitly forces export.
    """
    readiness = assess_readiness(project)
    open_blocking = [
        {
            "id": f.id,
            "title": f.title,
            "severity": f.severity,
            "kind": f.kind,
        }
        for f in project.findings
        if f.status.value == "open"
        and (f.kind or "").lower() == "blocking_contradiction"
    ]
    allow = bool(readiness.implementation_ready)
    return {
        "project_id": project.id,
        "project_name": project.name,
        "allow_implementation": allow,
        "readiness": readiness.model_dump(),
        "blocking_findings": open_blocking,
        "rejected_approaches": [
            {"approach": r.approach, "reason": r.reason}
            for r in (project.rejected_approaches or [])
        ],
        "instructions": {
            "when_blocked": (
                "Do not implement. Resolve blocking findings with evidence "
                "or re-run Grill review. Use force export only with explicit user consent."
            ),
            "when_allowed": (
                "Call POST /projects/{id}/agent-prompt to obtain Cursor/Codex/Antigravity prompts."
            ),
            "poll": "GET /integrations/agent-gate/{project_id}",
        },
    }


def plugin_manifest() -> dict[str, Any]:
    return {
        "name": "vibeprompt-readiness-gate",
        "version": "1.0.0",
        "agents": ["cursor", "codex", "antigravity"],
        "endpoints": {
            "status": "GET /api/v1/integrations/agent-gate/{project_id}",
            "export": "POST /api/v1/projects/{project_id}/agent-prompt",
            "cli": "python -m app.cli review --project . --fail-on-block",
        },
        "pre_implementation_hook": (
            "Fetch gate status; abort agent run when allow_implementation is false."
        ),
    }
