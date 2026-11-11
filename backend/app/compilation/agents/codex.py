"""OpenAI Codex adapter — goal / context / constraints / done-when prompting.

Informed by Codex best practices and AGENTS.md conventions: clear goal, relevant
context, explicit constraints, completion criteria, and verification.
"""

from __future__ import annotations

from app.compilation.agents.base import AgentCompileInput, bullets, common_context_sections


def compile_codex_prompt(payload: AgentCompileInput) -> str:
    parts = [
        f"# Codex Task: {payload.project_name}",
        "",
        "## Goal",
        payload.task,
        "",
        "## Repository context",
        "Use the structured project context below as authoritative. "
        "Inspect the repository for matching modules before implementing. "
        "If an `AGENTS.md` exists in the repo, follow it in addition to this task prompt.",
        "",
        "## Explicit task definition",
        bullets(
            [
                f"Primary task: {payload.task}",
                "Implement only what is required for acceptance criteria.",
                "Prefer the smallest change that satisfies the goal.",
            ]
        ),
        "",
        "## Implementation constraints",
        bullets(
            [
                f"Stack: {', '.join(payload.tech_stack) or 'do not invent a stack'}",
                *payload.constraints,
                "Do not reintroduce rejected approaches listed below.",
                "Do not invent APIs, libraries, or credentials not listed in context.",
            ]
            if payload.constraints
            else [
                f"Stack: {', '.join(payload.tech_stack) or 'do not invent a stack'}",
                "Do not reintroduce rejected approaches listed below.",
                "Do not invent APIs, libraries, or credentials not listed in context.",
            ]
        ),
        "",
        "## Expected behavior",
        bullets(payload.functional_requirements or [payload.task]),
        "",
        "## Testing instructions",
        bullets(payload.verification),
        "",
        "## Completion criteria (done when)",
        bullets(
            payload.acceptance
            + [
                "Relevant tests/lint pass when a harness exists.",
                "No out-of-scope features were added.",
            ]
        ),
        "",
    ]
    parts.extend(common_context_sections(payload))
    parts.extend(
        [
            "## Codex-specific rules",
            "- Bias to action with the constraints above; do not stop at a plan unless blocked.",
            "- Gather repo context with search/read tools before large edits.",
            "- Persist until verification completes or a precise blocker is reported.",
            "- Avoid repeating the same failing edit loop; stop with a clear summary if stuck.",
            "- Never invent secrets, API keys, or undocumented endpoints.",
        ]
    )
    return "\n".join(parts).strip() + "\n"
