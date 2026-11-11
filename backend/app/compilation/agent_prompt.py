"""Generate coding-agent prompts from structured project context.

Thin facade over the book-informed prompt pipeline so existing callers keep working.
Prefer `run_prompt_pipeline` when skill registry / knowledge store are available.
"""

from __future__ import annotations

from app.compilation.prompt_pipeline import run_prompt_pipeline
from app.knowledge.store import KnowledgeStore
from app.projects.models import AgentPromptResult, ProjectState
from app.skills.registry import SkillRegistry


def compile_agent_prompt(
    project: ProjectState,
    *,
    task: str | None = None,
    force: bool = False,
    agent: str = "cursor",
    include_skills: bool = True,
    user_selected_skills: list[str] | None = None,
    refine_notes: str | None = None,
    registry: SkillRegistry | None = None,
    store: KnowledgeStore | None = None,
) -> AgentPromptResult:
    """
    Build an agent-specific implementation prompt.

    Blocks by default when the project is not implementation-ready, unless force=True.
    When registry/store are omitted, skills are skipped (still agent-adapted).
    """
    return run_prompt_pipeline(
        project,
        task=task,
        agent=agent,
        force=force,
        include_skills=include_skills and registry is not None and store is not None,
        user_selected_skills=user_selected_skills,
        refine_notes=refine_notes,
        registry=registry,
        store=store,
    )
