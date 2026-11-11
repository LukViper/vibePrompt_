"""Book-informed multi-agent prompt generation tests."""

from __future__ import annotations

from app.compilation.agent_prompt import compile_agent_prompt
from app.compilation.agents import normalize_agent
from app.compilation.agents.base import AgentFamily
from app.compilation.prompt_pipeline import (
    classify_prompt_task,
    preview_skill_selection,
    run_prompt_pipeline,
)
from app.compilation.quality import validate_agent_prompt
from app.compilation.readiness import assess_readiness, detect_project_conflicts
from app.knowledge.store import KnowledgeStore
from app.projects.models import (
    Constraint,
    Decision,
    ProjectState,
    RejectedApproach,
    Requirement,
)
from app.skills.registry import SkillRegistry


def _ready_project(**kwargs) -> ProjectState:
    base = dict(
        name="WinLog",
        objective="Help IR analysts investigate Windows Event Logs",
        problem_statement="Raw EVTX is hard to query during investigations",
        intended_users=["IR analysts"],
        success_criteria=["Load EVTX and filter by Event ID"],
        scope_in=["EVTX ingest", "Normalized query UI"],
        scope_out=["Real-time detection engine"],
        tech_stack=["Python", "FastAPI", "SQLite"],
        constraints=[Constraint(text="Solo developer, 4-week MVP")],
        decisions=[
            Decision(title="Use case", choice="Investigation assistance"),
            Decision(title="Backend", choice="Python + FastAPI"),
        ],
        functional_requirements=[
            Requirement(
                text="Ingest Windows EVTX files",
                acceptance_criteria=["Sample EVTX loads without crash"],
            )
        ],
        non_functional_requirements=[
            Requirement(text="Runs on a single laptop", kind="non_functional"),
        ],
        rejected_approaches=[
            RejectedApproach(approach="Elasticsearch", reason="Infra complexity"),
        ],
        architecture_notes="Batch ingest → normalize → SQLite → query UI",
        data_model_notes="events(id, event_id, timestamp, payload)",
        testing_notes="pytest for parsers",
    )
    base.update(kwargs)
    return ProjectState(**base)


def test_readiness_checklist_not_just_score():
    p = _ready_project()
    r = assess_readiness(p)
    assert r.implementation_ready
    assert r.score_pct == 100
    assert all(i.present for i in r.checklist)


def test_incomplete_project_lists_missing_not_fake_complete_prompt():
    p = ProjectState(name="Empty", objective="Something vague")
    r = assess_readiness(p)
    assert not r.implementation_ready
    assert r.score_pct < 100
    result = compile_agent_prompt(p)
    assert result.blocked
    assert "checklist" in result.prompt.lower() or "resolve" in result.prompt.lower()


def test_conflicts_block_implementation_ready():
    p = _ready_project(tech_stack=["Python", "Elasticsearch"])
    conflicts = detect_project_conflicts(p)
    assert conflicts
    r = assess_readiness(p)
    assert not r.implementation_ready
    assert r.conflicts


def test_agent_adapters_differ():
    p = _ready_project()
    cursor = compile_agent_prompt(p, agent="cursor", force=True)
    anti = compile_agent_prompt(p, agent="antigravity", force=True)
    codex = compile_agent_prompt(p, agent="codex", force=True)
    assert "cursor" in cursor.prompt.lower()
    assert "antigravity" in anti.prompt.lower()
    assert "codex" in codex.prompt.lower() or "done when" in codex.prompt.lower()
    # Not the same generic heading with a renamed title only
    assert cursor.prompt != anti.prompt
    assert anti.prompt != codex.prompt


def test_task_classification_security_vs_nlp():
    sec = _ready_project(
        objective="Cybersecurity log analysis platform with auth",
        security_notes="Local-only; no remote auth in MVP",
    )
    nlp = _ready_project(
        name="DocNLP",
        objective="NLP document classifier using embeddings",
        problem_statement="Classify support tickets with an LLM pipeline",
        security_notes="",
    )
    assert classify_prompt_task(sec, "implement ingest") == "security_platform"
    assert classify_prompt_task(nlp, "build tokenizer pipeline") == "nlp_application"


def test_book_informed_vs_without_skills(tmp_path):
    db = tmp_path / "skills.db"
    store = KnowledgeStore(str(db), skills_root=tmp_path / "skills")
    registry = SkillRegistry(store)
    registry.ensure_builtins()

    p = _ready_project()
    with_skills = run_prompt_pipeline(
        p,
        agent="cursor",
        include_skills=True,
        registry=registry,
        store=store,
    )
    without = run_prompt_pipeline(
        p,
        agent="cursor",
        include_skills=False,
        registry=registry,
        store=store,
    )
    assert not with_skills.blocked
    assert not without.blocked
    assert with_skills.structured.get("book_informed") is True
    assert without.structured.get("book_informed") is False
    # Book-informed should expose skill selection metadata
    assert with_skills.skill_reasons
    assert "Book-informed" in with_skills.prompt or with_skills.skills_used

    # Measurable completeness lift: skill section + principles increase signal
    with_q = with_skills.quality.score_pct if with_skills.quality else 0
    without_q = without.quality.score_pct if without.quality else 0
    assert with_q >= without_q
    assert len(with_skills.prompt) > len(without.prompt)
    assert with_skills.skills_used  # principles retrieved
    # Correctness: rejected Elasticsearch still present; not promoted to stack
    assert "elasticsearch" in with_skills.prompt.lower()
    stack_line = next(
        (
            ln
            for ln in with_skills.prompt.lower().splitlines()
            if "tech stack" in ln
        ),
        "",
    )
    assert "elasticsearch" not in stack_line


def test_prompt_generation_independent_of_byok_providers():
    """Compilation is deterministic — does not call BYOK / model providers."""
    p = _ready_project()
    # No registry/store and no provider wiring required
    result = compile_agent_prompt(p, agent="codex", include_skills=False)
    assert not result.blocked
    assert result.agent == "codex"
    assert result.quality is not None


def test_skill_dependencies_respected():
    from app.skills.orchestrator import select_skill_slugs

    plan = select_skill_slugs(
        mode="explore",
        user_message="",
        user_selected=["prompt_evaluator"],
        max_skills=6,
    )
    assert "prompt_evaluator" in plan.selected_slugs
    assert "prompt_engineering" in plan.selected_slugs
    # Prerequisite inserted because evaluator was selected
    assert plan.reasons["prompt_engineering"].startswith("dependency_of:")
    assert plan.selected_slugs.index("prompt_engineering") < plan.selected_slugs.index(
        "prompt_evaluator"
    )


def test_quality_rejects_invented_stack_promotion():
    p = _ready_project()
    bad = (
        "# Cursor Agent Task: WinLog\n\n"
        "## Intended task\nImplement ingest\n\n"
        "## Project context\n**Objective:** Help IR analysts\n"
        "**Tech stack:** Use Kubernetes and Kafka for everything\n"
        "## Acceptance criteria\n- done\n"
        "## Out of scope / prohibited changes\n- none\n"
        "## Verification steps\n- test\n"
    )
    report = validate_agent_prompt(p, bad, agent="cursor")
    assert report.checks.get("no_invented_details") is False
    assert not report.passed


def test_preview_skills_endpoint_logic(tmp_path):
    store = KnowledgeStore(str(tmp_path / "k.db"), skills_root=tmp_path / "skills")
    registry = SkillRegistry(store)
    registry.ensure_builtins()
    p = _ready_project()
    preview = preview_skill_selection(
        p, task="Implement EVTX ingest", registry=registry, store=store
    )
    assert preview["selected_slugs"]
    assert "reasons" in preview
    assert preview["task_class"]


def test_normalize_agent_aliases():
    assert normalize_agent("agy") == AgentFamily.ANTIGRAVITY
    assert normalize_agent("codex-cli") == AgentFamily.CODEX
    assert normalize_agent("cursor-agent") == AgentFamily.CURSOR


def test_missing_books_still_compiles_with_builtins(tmp_path):
    store = KnowledgeStore(str(tmp_path / "empty.db"), skills_root=tmp_path / "skills")
    registry = SkillRegistry(store)
    registry.ensure_builtins()
    p = _ready_project()
    result = compile_agent_prompt(
        p, agent="codex", registry=registry, store=store, include_skills=True
    )
    assert not result.blocked
    assert result.agent == "codex"


def test_long_spec_still_agent_compatible():
    p = _ready_project(
        functional_requirements=[
            Requirement(
                text=f"Requirement {i}: handle case {i} for EVTX ingest",
                acceptance_criteria=[f"Case {i} passes"],
            )
            for i in range(20)
        ],
        architecture_notes="A" * 2000,
    )
    result = compile_agent_prompt(p, agent="antigravity", force=True)
    assert "antigravity" in result.prompt.lower()
    assert result.quality is None or isinstance(result.quality.score_pct, int)
