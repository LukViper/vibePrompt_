"""Prompt quality validation — length alone is never sufficient."""

from __future__ import annotations

import re
from typing import Any

from app.projects.models import ProjectState, PromptQualityReport


_VAGUE = re.compile(
    r"\b(somehow|maybe implement|figure out|as appropriate|etc\.?|and so on|"
    r"make it good|do the needful|various things)\b",
    re.I,
)


def validate_agent_prompt(
    project: ProjectState,
    prompt: str,
    *,
    agent: str,
    structured: dict[str, Any] | None = None,
) -> PromptQualityReport:
    issues: list[str] = []
    checks: dict[str, bool] = {}
    text = prompt or ""
    low = text.lower()

    def ok(name: str, condition: bool, issue: str) -> None:
        checks[name] = condition
        if not condition:
            issues.append(issue)

    # 1 Completeness
    ok(
        "completeness",
        "acceptance" in low and ("requirement" in low or "functional" in low),
        "Prompt lacks requirements/acceptance coverage.",
    )
    # 2 Technical consistency — rejected tech must not appear as selected stack line
    rejected = [
        (r.approach or "").strip().lower()
        for r in getattr(project, "rejected_approaches", []) or []
        if (r.approach or "").strip()
    ]
    stack_line = ""
    for line in text.splitlines():
        if line.lower().startswith("**tech stack:**") or line.lower().startswith(
            "tech stack:"
        ):
            stack_line = line.lower()
            break
    tech_ok = True
    for approach in rejected:
        if approach and approach in stack_line:
            tech_ok = False
            break
    ok(
        "technical_consistency",
        tech_ok,
        "Rejected technology appears on the tech stack line.",
    )

    # 3 Context accuracy — objective / name present
    name_ok = (project.name or "").lower() in low if project.name else True
    obj = (project.objective or project.problem_statement or "").strip()
    obj_ok = True
    if obj:
        # Require at least one distinctive token from objective
        tokens = [t for t in re.findall(r"[a-z0-9]{4,}", obj.lower()) if t not in {"with", "that", "this", "from"}]
        obj_ok = any(t in low for t in tokens[:5]) if tokens else True
    ok(
        "context_accuracy",
        name_ok and obj_ok,
        "Prompt context does not reflect project name/objective.",
    )

    # 4 Requirement coverage
    req_ok = True
    for req in project.functional_requirements[:5]:
        key_tokens = [t for t in re.findall(r"[a-z0-9]{4,}", (req.text or "").lower())][:2]
        if key_tokens and not any(t in low for t in key_tokens):
            req_ok = False
            break
    ok(
        "requirement_coverage",
        req_ok or not project.functional_requirements,
        "One or more functional requirements are missing from the prompt.",
    )

    # 5 Implementation clarity
    ok(
        "implementation_clarity",
        ("task" in low or "goal" in low or "implement" in low)
        and not bool(_VAGUE.search(text)),
        "Implementation instructions are vague or missing a clear task.",
    )

    # 6 Testability
    ok(
        "testability",
        "verif" in low or "test" in low or "acceptance" in low,
        "Prompt lacks testable verification/acceptance instructions.",
    )

    # 7 Scope boundaries
    ok(
        "scope_boundaries",
        "out of scope" in low or "prohibited" in low or "do not" in low,
        "Prompt lacks explicit scope boundaries.",
    )

    # 8 Agent compatibility
    agent_l = (agent or "").lower()
    if "cursor" in agent_l:
        agent_ok = "cursor" in low or "repository" in low or "inspect" in low
    elif "antigravity" in agent_l:
        agent_ok = "antigravity" in low or "decomposition" in low or "deliverable" in low
    elif "codex" in agent_l:
        agent_ok = "codex" in low or "done when" in low or "completion criteria" in low
    else:
        agent_ok = True
    ok(
        "agent_compatibility",
        agent_ok,
        f"Prompt does not match expected shape for agent '{agent}'.",
    )

    # 9 Unsupported assumptions / invented details
    invented = False
    # Flag common invented stacks not in project
    known = {t.lower() for t in (project.tech_stack or [])}
    for guess in ("kubernetes", "kafka", "elasticsearch", "mongodb", "redis", "graphql"):
        if guess in low and guess not in known and not any(guess in r for r in rejected):
            # Allowed if listed as rejected
            if f"rejected: {guess}" in low or f"rejected:{guess}" in low:
                continue
            # Also OK in "do not" / rejected sections
            if re.search(rf"(rejected|do not|prohibited).{{0,40}}{guess}", low):
                continue
            # Mention only as example elsewhere still risky if presented as required
            if re.search(rf"\b(use|using|adopt|choose)\b[^\n]{{0,40}}\b{guess}\b", low):
                invented = True
                break
    ok(
        "no_invented_details",
        not invented,
        "Prompt appears to introduce technologies not present in project context.",
    )

    # 10 Redundancy — extremely long + duplicated headers
    header_counts: dict[str, int] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            header_counts[line] = header_counts.get(line, 0) + 1
    redundant = any(v > 1 for v in header_counts.values()) or len(text) > 40_000
    ok(
        "no_redundancy",
        not redundant,
        "Prompt has duplicated sections or excessive length without structure.",
    )

    # Contradictory requirements already checked at readiness; re-check soft
    if project.scope_in and project.scope_out:
        for item in project.scope_in:
            if item and item in project.scope_out:
                issues.append(f"Contradictory scope item still present: {item}")
                checks["no_contradictions"] = False
    checks.setdefault("no_contradictions", True)

    passed_count = sum(1 for v in checks.values() if v)
    total = max(1, len(checks))
    score = int(round(100 * passed_count / total))
    # Fail if any critical checks fail
    critical = {
        "completeness",
        "technical_consistency",
        "context_accuracy",
        "scope_boundaries",
        "testability",
        "no_invented_details",
        "no_contradictions",
    }
    critical_ok = all(checks.get(k, True) for k in critical)
    return PromptQualityReport(
        passed=critical_ok and score >= 70,
        score_pct=score,
        issues=issues,
        checks=checks,
    )
