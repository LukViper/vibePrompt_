"""Google Antigravity adapter — plan → implement → verify agentic workflow.

Aligned with Antigravity docs: project understanding, task decomposition,
implementation sequence, verification loops, and clear deliverables.
Uses progressive disclosure: keep the prompt actionable without dumping entire books.
"""

from __future__ import annotations

from app.compilation.agents.base import AgentCompileInput, bullets, common_context_sections


def compile_antigravity_prompt(payload: AgentCompileInput) -> str:
    sequence = [
        "Understand the project context and constraints below.",
        "Produce a short implementation plan with ordered steps before editing.",
        "Identify relevant files/modules and dependencies for each step.",
        "Implement step-by-step, keeping diffs reviewable.",
        "Run verification (tests / manual acceptance checks) after material changes.",
        "Summarize deliverables and remaining risks.",
    ]
    if payload.outstanding:
        sequence.insert(
            2,
            f"Prioritize outstanding work: {payload.outstanding[0]}.",
        )

    parts = [
        f"# Antigravity Agent Task: {payload.project_name}",
        "",
        "## Intended task",
        payload.task,
        "",
        "## Project understanding (read first)",
        "Treat the structured context below as project truth. Do not restart product discovery. "
        "If a conflict appears between chat history and structured decisions, structured decisions win.",
        "",
        "## Task decomposition",
        bullets(
            [
                "Break the task into 3–7 concrete implementation steps.",
                "Call out dependencies between steps (e.g. data model before API).",
                "Mark steps that need human approval (security-sensitive, destructive migrations).",
            ]
        ),
        "",
        "## Implementation sequence",
        bullets(sequence),
        "",
        "## Relevant files and dependencies",
        bullets(
            [
                "Locate modules matching the tech stack and architecture notes before creating new packages.",
                f"Tech stack to honor: {', '.join(payload.tech_stack) or '(unspecified)'}.",
                "List files you will touch before editing; prefer isolated Git worktree-friendly changes.",
            ]
        ),
        "",
        "## Verification requirements",
        bullets(payload.verification),
        "",
        "## Expected deliverables",
        bullets(
            [
                "Working implementation that satisfies acceptance criteria.",
                "Updated or new tests covering the change.",
                "Brief summary of files changed and how to verify.",
                "Explicit list of anything left unresolved.",
            ]
        ),
        "",
    ]
    parts.extend(common_context_sections(payload))
    parts.extend(
        [
            "## Antigravity-specific rules",
            "- Prefer a visible plan + verification loop over silent large rewrites.",
            "- Keep tool use bounded to the project workspace; do not expand scope.",
            "- Use progressive loading of guidance: follow skill principles below only when relevant to a step.",
            "- Stop and ask when acceptance criteria are ambiguous — do not invent product requirements.",
            "- Never invent secrets, API keys, or undocumented endpoints.",
        ]
    )
    return "\n".join(parts).strip() + "\n"
