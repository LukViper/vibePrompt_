"""
Fixed evaluation set comparing primary-only vs two-model behavior.

Run: pytest tests/evaluation/test_eval_set.py -v
Does not claim multi-model is better without recorded metrics.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest

from app.config import Settings
from app.persistence.repository import InMemoryProjectRepository
from app.projects.models import FindingStatus, ProjectState
from app.providers.base import (
    CandidateFinding,
    CriticFindingAction,
    CriticReview,
    PrimaryAnalysis,
    StatePatch,
)
from app.providers.mock import MockProvider
from tests.conftest import build_engine, make_finding


@dataclass
class EvalCase:
    id: str
    message: str
    primary_findings: list[CandidateFinding]
    critic: CriticReview
    expected_valid_titles: list[str] = field(default_factory=list)
    expected_false_positive_titles: list[str] = field(default_factory=list)
    overlooked_if_primary_only: list[str] = field(default_factory=list)


CASES: list[EvalCase] = [
    EvalCase(
        id="scope_deadline",
        message=(
            "I want to build a full multi-vendor marketplace platform "
            "with payments and chat, launching by tomorrow."
        ),
        primary_findings=[
            make_finding(
                title="Unrealistic deadline",
                claim="Ship marketplace tomorrow",
                severity="critical",
            )
        ],
        critic=CriticReview(
            actions=[CriticFindingAction(finding_index=0, action="agree", notes="valid")]
        ),
        expected_valid_titles=["Unrealistic deadline"],
    ),
    EvalCase(
        id="weak_false_positive",
        message=(
            "For the architecture decision we will use TypeScript on a small MVP notes app."
        ),
        primary_findings=[
            make_finding(
                title="TypeScript is bad",
                claim="TS is always wrong",
                severity="medium",
                confidence=0.3,
            )
        ],
        critic=CriticReview(
            actions=[
                CriticFindingAction(
                    finding_index=0, action="disagree", notes="unsupported"
                )
            ]
        ),
        expected_false_positive_titles=["TypeScript is bad"],
    ),
    EvalCase(
        id="missed_privacy",
        message=(
            "I want to build a platform storing medical patient records "
            "with a simple CRUD UI for clinics."
        ),
        primary_findings=[
            make_finding(title="CRUD is fine", claim="CRUD enough", severity="low")
        ],
        critic=CriticReview(
            actions=[
                CriticFindingAction(finding_index=0, action="agree", notes="ok"),
                CriticFindingAction(
                    finding_index=None,
                    action="add_risk",
                    revised=make_finding(
                        title="Privacy design missing",
                        claim="Medical data without privacy plan",
                        severity="critical",
                    ),
                    notes="overlooked",
                ),
            ]
        ),
        overlooked_if_primary_only=["Privacy design missing"],
        expected_valid_titles=["Privacy design missing"],
    ),
]


@dataclass
class EvalMetrics:
    case_id: str
    mode: str
    valid_found: int
    false_positives_open: int
    overlooked: int
    primary_calls: int
    critic_calls: int
    open_titles: list[str]


@pytest.mark.asyncio
async def test_evaluation_primary_vs_two_model(tmp_path: Path):
    settings = Settings(critic_enabled=True, review_intensity="normal")
    results: list[EvalMetrics] = []

    for case in CASES:
        for mode in ("primary_only", "two_model"):
            repo = InMemoryProjectRepository()
            project = repo.create(ProjectState(name=case.id, objective=""))
            call_log: list[str] = []

            findings = list(case.primary_findings)
            review = case.critic

            def primary_handler(
                project_snapshot=None,
                user_message=None,
                conversation_tail=None,
                _findings=findings,
            ):
                return PrimaryAnalysis(
                    reply="eval",
                    intent="initial_idea",
                    findings=list(_findings),
                    state_patch=StatePatch(),
                )

            def critic_handler(
                project_snapshot=None,
                user_message=None,
                candidate_findings=None,
                primary_reply=None,
                _review=review,
            ):
                return _review

            critic = (
                None
                if mode == "primary_only"
                else MockProvider(critic_handler=critic_handler, call_log=call_log)
            )
            s = settings.model_copy(update={"critic_enabled": mode == "two_model"})
            engine = build_engine(
                repo,
                s,
                primary=MockProvider(primary_handler=primary_handler, call_log=call_log),
                critic=critic,
                offline=False,
            )
            if mode == "primary_only":
                engine.settings = s.model_copy(update={"critic_enabled": False})
                engine.critic = None

            res = await engine.handle_message(project.id, case.message)
            open_titles = [
                f.title for f in res.findings if f.status == FindingStatus.OPEN
            ]

            valid_found = sum(1 for t in case.expected_valid_titles if t in open_titles)
            fps = 0
            for t in case.expected_false_positive_titles:
                match = next((f for f in res.findings if f.title == t), None)
                if (
                    match
                    and match.status == FindingStatus.OPEN
                    and match.severity.value != "low"
                ):
                    fps += 1

            overlooked = 0
            if mode == "primary_only":
                overlooked = sum(
                    1 for t in case.overlooked_if_primary_only if t not in open_titles
                )

            results.append(
                EvalMetrics(
                    case_id=case.id,
                    mode=mode,
                    valid_found=valid_found,
                    false_positives_open=fps,
                    overlooked=overlooked,
                    primary_calls=call_log.count("primary"),
                    critic_calls=call_log.count("critic"),
                    open_titles=open_titles,
                )
            )

    out = tmp_path / "eval_results.json"
    out.write_text(json.dumps([asdict(r) for r in results], indent=2))

    two = {r.case_id: r for r in results if r.mode == "two_model"}
    one = {r.case_id: r for r in results if r.mode == "primary_only"}

    assert two["missed_privacy"].valid_found >= 1
    assert one["missed_privacy"].overlooked >= 1
    assert (
        two["weak_false_positive"].false_positives_open
        <= one["weak_false_positive"].false_positives_open
    )
    assert two["scope_deadline"].critic_calls == 1
    assert one["scope_deadline"].critic_calls == 0

    dest = Path(__file__).parent / "results"
    dest.mkdir(exist_ok=True)
    (dest / "latest.json").write_text(out.read_text())
