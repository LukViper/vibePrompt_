"""Book-informed, multi-agent prompt generation pipeline.

Project Context → Readiness Validation → Task Classification → Skill Selection →
Knowledge Retrieval → Agent Adapter → Prompt Compilation → Quality Validation

Reuses Grill ProjectState, assess_readiness, skill orchestrator, and agent adapters.
Does not create a separate orchestration engine.
"""

from __future__ import annotations

import re
from typing import Any

from app.compilation.agents import compile_for_agent, normalize_agent
from app.compilation.agents.base import AgentCompileInput
from app.compilation.quality import validate_agent_prompt
from app.compilation.readiness import assess_readiness
from app.compilation.spec import compile_specification
from app.grill.modes import BehaviouralMode
from app.knowledge.store import KnowledgeStore
from app.projects.models import (
    AgentPromptResult,
    FindingStatus,
    ProjectState,
    PromptQualityReport,
)
from app.skills.orchestrator import OrchestrationPlan, build_orchestration_context
from app.skills.registry import SkillRegistry


def classify_prompt_task(project: ProjectState, task: str | None) -> str:
    """Classify the generation task for skill selection (not a separate engine)."""
    text = " ".join(
        [
            task or "",
            project.objective or "",
            project.problem_statement or "",
            " ".join(project.scope_in or []),
            " ".join(project.tech_stack or []),
            " ".join(r.text for r in project.functional_requirements[:6]),
        ]
    ).lower()

    if re.search(r"\b(security|cyber|auth|siem|threat|malware|encrypt)\b", text):
        return "security_platform"
    if re.search(r"\b(nlp|llm|embedding|transformer|language model|tokenizer)\b", text):
        return "nlp_application"
    if re.search(r"\b(data pipeline|etl|spark|warehouse|analytics)\b", text):
        return "data_pipeline"
    if re.search(r"\b(mobile|ios|android|react native)\b", text):
        return "mobile_app"
    if re.search(r"\b(api|backend|fastapi|express|django)\b", text):
        return "backend_service"
    return "general_implementation"


_DOMAIN_SKILL_HINTS: dict[str, list[str]] = {
    "security_platform": [
        "technical_architecture",
        "project_planning",
        "prompt_engineering",
        "grill",
        "prompt_evaluator",
    ],
    "nlp_application": [
        "agent_engineering",
        "technical_architecture",
        "prompt_engineering",
        "prompt_evaluator",
        "project_planning",
    ],
    "data_pipeline": [
        "technical_architecture",
        "project_planning",
        "prompt_engineering",
    ],
    "backend_service": [
        "technical_architecture",
        "agent_engineering",
        "prompt_engineering",
        "project_planning",
    ],
    "mobile_app": [
        "product_discovery",
        "technical_architecture",
        "prompt_engineering",
    ],
    "general_implementation": [
        "prompt_engineering",
        "agent_engineering",
        "technical_architecture",
        "project_planning",
        "prompt_evaluator",
    ],
}


def _bullets_blocked(reasons: list[str]) -> str:
    if not reasons:
        return "- Unknown blockers"
    return "\n".join(f"- {r}" for r in reasons)


def build_agent_compile_input(
    project: ProjectState,
    *,
    task: str,
    skill_plan: OrchestrationPlan | None,
    refine_notes: str | None,
    readiness_status: str,
) -> AgentCompileInput:
    acceptance: list[str] = list(project.success_criteria)
    for req in project.functional_requirements:
        acceptance.extend(req.acceptance_criteria)
        if not req.acceptance_criteria:
            acceptance.append(f"Requirement satisfied: {req.text}")

    verification: list[str] = []
    if project.testing_notes:
        verification.append(project.testing_notes)
    verification.extend(
        [
            "Run the project's existing tests / lint if present.",
            "Manually verify each acceptance criterion above.",
            "Do not claim success without evidence from those checks.",
        ]
    )

    open_findings = [
        f"[{f.severity.value}] {f.title}: {f.challenged_claim}"
        for f in project.findings
        if f.status == FindingStatus.OPEN
    ]
    accepted = [
        f"{f.title}: {f.challenged_claim}"
        for f in project.findings
        if f.status == FindingStatus.ACCEPTED_RISK
    ]
    decisions = [
        f"{d.title}: {d.choice}" + (f" ({d.rationale})" if d.rationale else "")
        for d in project.decisions
        if getattr(d, "status", "accepted") != "superseded"
    ]
    rejected = [
        f"{r.approach} — {r.reason}".strip(" —")
        for r in getattr(project, "rejected_approaches", []) or []
    ]

    return AgentCompileInput(
        project_name=project.name,
        task=task,
        objective=project.objective or "",
        problem=getattr(project, "problem_statement", "") or "",
        description=getattr(project, "description", "") or "",
        users=list(project.intended_users),
        tech_stack=list(project.tech_stack),
        constraints=[c.text for c in project.constraints],
        decisions=decisions,
        architecture_notes=project.architecture_notes or "",
        data_model_notes=project.data_model_notes or "",
        security_notes=project.security_notes or "",
        scope_in=list(project.scope_in),
        scope_out=list(project.scope_out),
        functional_requirements=[r.text for r in project.functional_requirements],
        non_functional_requirements=[
            r.text for r in project.non_functional_requirements
        ],
        acceptance=acceptance,
        verification=verification,
        rejected=rejected,
        outstanding=list(getattr(project, "outstanding_tasks", []) or []),
        completed=list(getattr(project, "completed_milestones", []) or []),
        milestones=list(project.milestones or []),
        open_findings=open_findings,
        accepted_risks=accepted,
        skill_block=(skill_plan.prompt_block if skill_plan else "") or "",
        skill_reasons=dict(skill_plan.reasons) if skill_plan else {},
        refine_notes=(refine_notes or "").strip(),
        readiness_status=readiness_status,
    )


def select_skills_for_prompt(
    project: ProjectState,
    *,
    task: str,
    registry: SkillRegistry | None,
    store: KnowledgeStore | None,
    user_selected: list[str] | None = None,
    include_skills: bool = True,
) -> OrchestrationPlan | None:
    if not include_skills or registry is None or store is None:
        return None

    task_class = classify_prompt_task(project, task)
    domain_slugs = _DOMAIN_SKILL_HINTS.get(task_class, [])
    # Message for cue matching: task + domain labels + project keywords
    cue_message = " ".join(
        [
            task,
            "coding agent prompt implementation",
            task_class.replace("_", " "),
            project.objective or "",
            " ".join(project.tech_stack or []),
        ]
    )
    selected = list(user_selected or [])
    for slug in domain_slugs:
        if slug not in selected:
            selected.append(slug)

    try:
        plan = build_orchestration_context(
            registry,
            store,
            mode=BehaviouralMode.BUILD,
            user_message=cue_message,
            user_selected=selected[:6],
            max_principles=8,
        )
        # Annotate domain reasons without wiping cue/mode reasons
        for slug in plan.selected_slugs:
            if slug in domain_slugs and plan.reasons.get(slug) == "user_selected":
                plan.reasons[slug] = f"domain_hint:{task_class}"
        return plan
    except Exception:
        return None


def run_prompt_pipeline(
    project: ProjectState,
    *,
    task: str | None = None,
    agent: str = "cursor",
    force: bool = False,
    include_skills: bool = True,
    user_selected_skills: list[str] | None = None,
    refine_notes: str | None = None,
    registry: SkillRegistry | None = None,
    store: KnowledgeStore | None = None,
) -> AgentPromptResult:
    """
    Full prompt-generation pipeline.

    Blocks when not implementation_ready unless force=True.
    Quality failures block presentation unless force=True (still attach report).
    """
    readiness = assess_readiness(project)
    agent_id = normalize_agent(agent).value

    block_reasons = (
        list(readiness.missing_essentials)
        + list(readiness.blockers)
        + list(readiness.conflicts)
    )
    # Prefer implementation gate for agent prompts
    gated = not readiness.implementation_ready
    blocked = gated and not force

    task_line = (task or "").strip() or (
        project.outstanding_tasks[0]
        if getattr(project, "outstanding_tasks", None)
        else f"Implement the MVP for {project.name}"
    )

    if blocked:
        prompt = (
            f"# Implementation blocked for {project.name}\n\n"
            "Critical project context is incomplete or contradictory. "
            "Do not start coding yet.\n\n"
            f"**Readiness score (informational):** {readiness.score_pct}% — "
            "score alone is never sufficient; checklist and conflicts decide.\n\n"
            "## Checklist gaps\n"
            + _bullets_blocked(
                [
                    f"{'[ok]' if i.present else '[missing]'} {i.label}"
                    f" ({i.category})"
                    for i in readiness.checklist
                ]
            )
            + "\n\n## Resolve first\n"
            + _bullets_blocked(block_reasons or ["Unknown blockers"])
            + "\n\n## Suggested next step\n"
            + _bullets_blocked(
                readiness.unblock_actions
                or ["Clarify mandatory context with Grill before generating a prompt."]
            )
        )
        return AgentPromptResult(
            readiness=readiness,
            prompt=prompt,
            blocked=True,
            block_reasons=block_reasons,
            structured={
                "ready": False,
                "implementation_ready": False,
                "project_id": project.id,
                "agent": agent_id,
                "task_class": classify_prompt_task(project, task_line),
            },
            agent=agent_id,
            warnings=list(readiness.warnings),
        )

    skill_plan = select_skills_for_prompt(
        project,
        task=task_line,
        registry=registry,
        store=store,
        user_selected=user_selected_skills,
        include_skills=include_skills,
    )

    payload = build_agent_compile_input(
        project,
        task=task_line,
        skill_plan=skill_plan,
        refine_notes=refine_notes,
        readiness_status=readiness.status,
    )
    prompt = compile_for_agent(agent_id, payload)
    quality = validate_agent_prompt(project, prompt, agent=agent_id)

    warnings = list(readiness.warnings)
    quality_blocked = False
    if not quality.passed and not force:
        quality_blocked = True
        warnings.extend(quality.issues)
        prompt = (
            f"# Prompt quality validation failed for {project.name}\n\n"
            "A draft was produced but failed quality checks. "
            "Resolve the issues below or regenerate with force=true after review.\n\n"
            "## Quality issues\n"
            + _bullets_blocked(quality.issues)
            + "\n\n## Draft (not implementation-ready)\n\n"
            + prompt
        )

    spec = compile_specification(project)
    skills_used = []
    skill_reasons: dict[str, str] = {}
    if skill_plan:
        skill_reasons = dict(skill_plan.reasons)
        skills_used = [
            {
                "slug": p.get("skill"),
                "title": p.get("title"),
                "summary": p.get("summary"),
                "source_book_id": p.get("source_book_id"),
                "chapter_ref": p.get("chapter_ref"),
                "confidence": p.get("confidence"),
            }
            for p in (skill_plan.principles or [])
        ]

    structured: dict[str, Any] = {
        "project_id": project.id,
        "name": project.name,
        "task": task_line,
        "agent": agent_id,
        "task_class": classify_prompt_task(project, task_line),
        "readiness": readiness.model_dump(mode="json"),
        "tech_stack": list(project.tech_stack),
        "decisions": [d.model_dump(mode="json") for d in project.decisions],
        "scope_out": list(project.scope_out),
        "rejected_approaches": [
            r.model_dump(mode="json")
            for r in getattr(project, "rejected_approaches", []) or []
        ],
        "acceptance_criteria": payload.acceptance,
        "specification": spec.structured,
        "skills": {
            "selected_slugs": skill_plan.selected_slugs if skill_plan else [],
            "reasons": skill_reasons,
            "principles": skill_plan.principles if skill_plan else [],
        },
        "quality": quality.model_dump(mode="json"),
        "book_informed": bool(skill_plan and skill_plan.prompt_block),
    }

    return AgentPromptResult(
        readiness=readiness,
        prompt=prompt if not quality_blocked else prompt,
        blocked=quality_blocked,
        block_reasons=(quality.issues if quality_blocked else (block_reasons if not readiness.implementation_ready else [])),
        structured=structured,
        agent=agent_id,
        skills_used=skills_used,
        skill_reasons=skill_reasons,
        quality=quality,
        warnings=warnings,
    )


def preview_skill_selection(
    project: ProjectState,
    *,
    task: str | None = None,
    registry: SkillRegistry,
    store: KnowledgeStore,
    user_selected_skills: list[str] | None = None,
) -> dict[str, Any]:
    task_line = (task or "").strip() or f"Implement the MVP for {project.name}"
    plan = select_skills_for_prompt(
        project,
        task=task_line,
        registry=registry,
        store=store,
        user_selected=user_selected_skills,
        include_skills=True,
    )
    return {
        "task": task_line,
        "task_class": classify_prompt_task(project, task_line),
        "selected_slugs": plan.selected_slugs if plan else [],
        "reasons": plan.reasons if plan else {},
        "principles": plan.principles if plan else [],
        "prompt_block": plan.prompt_block if plan else "",
        "readiness": assess_readiness(project).model_dump(mode="json"),
    }
