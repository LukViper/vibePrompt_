"""Cursor Agent adapter — repo-aware, file-boundary, scoped implementation prompts.

Informed by Cursor Agent workflows: inspect existing architecture, respect module
boundaries, implement with tests, and stay within stated scope.
"""

from __future__ import annotations

from app.compilation.agents.base import AgentCompileInput, bullets, common_context_sections


def compile_cursor_prompt(payload: AgentCompileInput) -> str:
    parts = [
        f"# Cursor Agent Task: {payload.project_name}",
        "",
        "## Intended task",
        payload.task,
        "",
        "## Cursor workflow",
        "1. **Inspect the repository first** — list relevant directories, locate existing "
        "modules that already solve adjacent problems, and reuse patterns before creating new ones.",
        "2. **Respect architecture awareness** — follow the decisions and architecture notes below; "
        "do not introduce a parallel stack.",
        "3. **Honor file and module boundaries** — prefer small, reviewable diffs in existing modules; "
        "create new files only when boundaries require it.",
        "4. **Implement against requirements** — map each change to functional/NFR items and acceptance criteria.",
        "5. **Add or update tests** — cover acceptance criteria with automated tests when a harness exists.",
        "6. **Stay in scope** — refuse out-of-scope and rejected approaches.",
        "",
    ]
    parts.extend(common_context_sections(payload))
    parts.extend(
        [
            "## Cursor-specific rules",
            "- Start by inspecting the repo layout and existing related code before editing.",
            "- Prefer editing existing modules that own the concern; avoid drive-by refactors.",
            "- Keep changes minimal and reviewable; call out new files and why they are needed.",
            "- Run the project's existing tests / lint if present; report evidence of verification.",
            "- If context is insufficient for a safe change, stop and ask one precise question.",
            "- Never invent secrets, API keys, or undocumented endpoints.",
            "",
            "## Suggested module boundaries",
            bullets(
                [
                    "Keep ingest / parse / persist / query layers separate when architecture notes imply a pipeline.",
                    "Do not collapse rejected infrastructure into the MVP.",
                    "Place tests next to the code they verify when the repo already does so.",
                ]
            ),
        ]
    )
    return "\n".join(parts).strip() + "\n"
