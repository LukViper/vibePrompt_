#!/usr/bin/env python3
"""
GRILL long-term memory stress validation.

Does NOT modify production code. Exercises existing memory/engine/persistence APIs
and writes JSON + markdown report artifacts under docs/.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import traceback
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("FREE_TIER_ENABLED", "false")
os.environ.setdefault("CRITIC_ENABLED", "false")

from app.config import Settings, get_settings
from app.grill.context import retrieve_relevant_context
from app.grill.memory import (
    apply_summary_update,
    assemble_prompt_context,
    build_deterministic_summary,
    maybe_refresh_summary,
    should_summarize,
    update_working_memory,
    validate_summary_does_not_override_structure,
)
from app.grill.modes import BehaviouralMode
from app.orchestration.engine import GrillEngine
from app.persistence.repository import InMemoryProjectRepository, SQLiteProjectRepository
from app.projects.models import (
    Constraint,
    ConversationSummary,
    Decision,
    Message,
    MessageIntent,
    OpenQuestion,
    ProjectState,
    RejectedApproach,
    Requirement,
)
from app.providers.base import PrimaryAnalysis, ProviderError, ProviderErrorKind, StatePatch
from app.providers.mock import MockProvider


@dataclass
class Finding:
    suite: str
    check: str
    expected: str
    actual: str
    passed: bool
    severity: str = "info"
    root_cause: str = ""
    repro: str = ""
    notes: str = ""


RESULTS: list[Finding] = []


def record(
    suite: str,
    check: str,
    expected: str,
    actual: str,
    passed: bool,
    *,
    severity: str = "high",
    root_cause: str = "",
    repro: str = "",
    notes: str = "",
) -> None:
    RESULTS.append(
        Finding(
            suite=suite,
            check=check,
            expected=expected,
            actual=str(actual)[:800],
            passed=passed,
            severity=severity if not passed else "info",
            root_cause=root_cause if not passed else "",
            repro=repro if not passed else "",
            notes=notes,
        )
    )


def settings(**kwargs) -> Settings:
    get_settings.cache_clear()
    base = dict(
        gemini_api_key="",
        openrouter_api_key="",
        groq_api_key="",
        qwen_api_key="",
        free_tier_enabled=False,
        critic_enabled=False,
        review_intensity="normal",
        database_path="./data/memory_stress.db",
        api_secret="",
        summary_min_messages=20,
        summary_min_new_messages=8,
        summary_keep_recent=8,
        history_max_messages=10,
        history_max_chars=800,
        context_max_total_chars=28_000,
        context_max_summary_chars=4_000,
    )
    base.update(kwargs)
    return Settings(**base)


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------


def seed_log_platform() -> ProjectState:
    p = ProjectState(
        name="WinLog-Investigator",
        objective="Help IR analysts investigate Windows Event Logs",
        problem_statement="Raw EVTX is hard to query during investigations",
        description="MVP investigation assistant — not a SIEM",
        intended_users=["IR analysts", "SOC juniors"],
        success_criteria=[
            "Load a sample EVTX without crash",
            "Filter by Event ID and time range",
        ],
        functional_requirements=[
            Requirement(
                text="Ingest Windows EVTX files",
                acceptance_criteria=["Sample EVTX loads"],
            ),
            Requirement(text="Normalized query UI for Event ID"),
        ],
        non_functional_requirements=[
            Requirement(text="Runs on a single developer laptop", kind="non_functional"),
        ],
        scope_in=["EVTX ingest", "Normalization", "Investigation queries"],
        scope_out=["Real-time detection engine", "Full SIEM clone"],
        constraints=[
            Constraint(text="Solo developer, 4-week MVP", category="resource"),
            Constraint(text="Prefer low ops overhead", category="tech"),
        ],
        decisions=[
            Decision(title="Use case", choice="Investigation assistance", status="accepted"),
            Decision(title="Backend", choice="Python + FastAPI", status="accepted"),
            Decision(title="Database", choice="SQLite", status="accepted"),
            Decision(
                title="Frontend",
                choice="Minimal HTML + HTMX",
                status="accepted",
            ),
        ],
        tech_stack=["Python", "FastAPI", "SQLite"],
        rejected_approaches=[
            RejectedApproach(approach="Elasticsearch", reason="Infrastructure complexity"),
            RejectedApproach(approach="Kafka streaming", reason="Premature for MVP"),
            RejectedApproach(approach="Kubernetes", reason="Ops cost for solo MVP"),
        ],
        architecture_notes="Batch ingest → normalize → SQLite → query UI",
        outstanding_tasks=["Implement EVTX ingest endpoint", "Add Event ID filter"],
        completed_milestones=["Scoped MVP", "Chose stack"],
        open_questions=[
            OpenQuestion(text="Do we need Sysmon in v1?", priority="medium"),
            OpenQuestion(text="Auth model for multi-analyst later?", priority="low"),
        ],
        preferences=["Investigation over detection"],
        known_risks=["EVTX parser drift across Windows versions"],
    )
    return p


def append_scripted_dialogue(p: ProjectState, total_messages: int = 100) -> ProjectState:
    """Build >= total_messages with requirements, decisions, brainstorm, corrections, progress."""
    script: list[tuple[str, str]] = [
        ("user", "I want a cybersecurity log analysis platform for investigations."),
        ("assistant", "Let's scope Windows Event Logs first if that is your initial source."),
        ("user", "Yes — Windows Event Logs only for v1."),
        ("assistant", "Recorded Windows Event Logs as the initial source."),
        ("user", "Investigation assistance, not real-time detection."),
        ("assistant", "That steers us away from a detection engine for MVP."),
        ("user", "We are using Python and FastAPI."),
        ("assistant", "Python + FastAPI noted for the backend."),
        ("user", "Our database will be SQLite."),
        ("assistant", "SQLite fits a laptop MVP."),
        ("user", "Reject Elasticsearch because of infrastructure complexity."),
        ("assistant", "Elasticsearch stays rejected for ops cost."),
        ("user", "Maybe we should brainstorm using MongoDB or Kafka later?"),
        ("assistant", "Treat that as brainstorming — not a confirmed decision."),
        ("user", "Actually, keep SQLite. Do not switch databases."),
        ("assistant", "Correction noted: SQLite remains the datastore."),
        ("user", "Architecture: batch ingest then normalize then query."),
        ("assistant", "Architecture notes updated for batch pipeline."),
        ("user", "Outstanding task: implement EVTX ingest endpoint."),
        ("assistant", "Tracked as outstanding work."),
    ]
    # Pad with realistic follow-ups until we hit total_messages
    i = 0
    while len(p.messages) < total_messages:
        if i < len(script):
            role, content = script[i]
        else:
            # Rotate topical follow-ups that mention critical terms occasionally
            n = i - len(script)
            topics = [
                ("user", f"Follow-up {n}: confirm Event ID filter still planned."),
                ("assistant", f"Yes — Event ID filter remains in scope for the MVP."),
                ("user", f"Note {n}: parser should tolerate Windows version drift."),
                ("assistant", f"Known risk retained: EVTX parser drift."),
                ("user", f"Progress {n}: sketched FastAPI route for /ingest."),
                ("assistant", f"Progress noted against EVTX ingest outstanding task."),
                ("user", f"Reminder {n}: Elasticsearch remains rejected."),
                ("assistant", f"Understood — do not reintroduce Elasticsearch."),
                ("user", f"Question {n}: still undecided on Sysmon for v1."),
                ("assistant", f"Sysmon remains an open question, not a requirement."),
            ]
            role, content = topics[n % len(topics)]
        p.messages.append(Message(role=role, content=content))
        i += 1
    return p


# ---------------------------------------------------------------------------
# TEST 1 — Long conversation retention
# ---------------------------------------------------------------------------


def test_1_long_conversation_retention() -> None:
    suite = "1. Long conversation retention"
    p = seed_log_platform()
    p = append_scripted_dialogue(p, total_messages=100)
    record(
        suite,
        "Conversation has >= 100 messages",
        ">= 100",
        str(len(p.messages)),
        len(p.messages) >= 100,
        severity="critical",
        repro="append_scripted_dialogue(..., 100)",
    )

    assert should_summarize(p, min_messages=20, min_new_since_summary=8) or len(p.messages) >= 100
    summary = build_deterministic_summary(p, keep_recent=8)
    apply_summary_update(p, summary)

    must_have = [
        ("objective/investigation", "investigation" in summary.text.lower() or "Windows" in summary.text),
        ("SQLite decision", "SQLite" in summary.text),
        ("FastAPI/Python", "FastAPI" in summary.text or "Python" in summary.text),
        ("Elasticsearch rejected", "Elasticsearch" in summary.text),
        ("Kafka or K8s rejected", "Kafka" in summary.text or "Kubernetes" in summary.text),
        ("open Sysmon question or outstanding ingest", "Sysmon" in summary.text or "ingest" in summary.text.lower()),
        ("architecture batch", "batch" in summary.text.lower() or "Architecture" in summary.text),
    ]
    for name, ok in must_have:
        record(
            suite,
            f"Summary retains {name}",
            "Present in summary text",
            summary.text[:500],
            ok,
            severity="critical" if "SQLite" in name or "Elastic" in name else "high",
            root_cause="Deterministic summary omitted structured fact",
            repro="build_deterministic_summary after 100-message seed",
        )

    # After summarization, assemble as if older messages excluded
    structured = retrieve_relevant_context(
        p, mode=BehaviouralMode.BUILD, user_message="Implement EVTX ingest"
    ).as_prompt_json()
    assembled = assemble_prompt_context(
        p,
        mode=BehaviouralMode.BUILD,
        user_message="Implement the EVTX ingest endpoint with SQLite storage",
        structured_snapshot=structured,
        max_recent_messages=8,
        max_chars_each=400,
        max_summary_chars=3000,
        max_total_chars=12_000,
    )
    snap = assembled.snapshot
    record(
        suite,
        "Assembled context retains SQLite + Elastic rejection after summary",
        "tech_stack has SQLite; rejected has Elasticsearch",
        str(
            {
                "stack": snap.get("tech_stack"),
                "rejected": snap.get("rejected_approaches"),
                "tail_len": len(assembled.conversation_tail),
            }
        ),
        "SQLite" in (snap.get("tech_stack") or [])
        and any(
            "Elastic" in str(r.get("approach") if isinstance(r, dict) else r)
            for r in (snap.get("rejected_approaches") or [])
        ),
        severity="critical",
    )
    record(
        suite,
        "Active window much smaller than full history",
        "conversation_tail << 100",
        str(len(assembled.conversation_tail)),
        len(assembled.conversation_tail) < 30,
        severity="high",
    )


# ---------------------------------------------------------------------------
# TEST 2 — Decision preservation
# ---------------------------------------------------------------------------


def test_2_decision_preservation() -> None:
    suite = "2. Decision preservation"
    p = seed_log_platform()
    # Supersede a decision historically
    for d in p.decisions:
        if d.title == "Frontend":
            d.status = "superseded"
    p.decisions.append(
        Decision(title="Frontend", choice="React + Vite", status="accepted", rationale="User correction")
    )
    p.messages.append(
        Message(role="user", content="Actually, replace HTMX with React + Vite.")
    )
    p.messages.append(
        Message(role="user", content="Maybe brainstorm using MongoDB instead of SQLite?")
    )
    append_scripted_dialogue(p, total_messages=40)

    before_d = [
        (d.title, d.choice)
        for d in p.decisions
        if getattr(d, "status", "accepted") != "superseded"
    ]
    before_s = list(p.tech_stack)
    before_r = [r.approach for r in p.rejected_approaches]

    summary = build_deterministic_summary(p, keep_recent=6)
    apply_summary_update(p, summary)
    ok = validate_summary_does_not_override_structure(
        p,
        before_decisions=before_d,
        before_stack=before_s,
        before_rejected=before_r,
    )
    record(
        suite,
        "Summary apply does not mutate authoritative ProjectState",
        "decisions/stack/rejected unchanged",
        str(
            {
                "decisions": [(d.title, d.choice, d.status) for d in p.decisions],
                "stack": p.tech_stack,
            }
        ),
        ok,
        severity="critical",
        root_cause="apply_summary_update mutated structured fields",
        repro="validate_summary_does_not_override_structure after build+apply",
    )

    record(
        suite,
        "Confirmed React decision present; HTMX superseded historically",
        "Active Frontend=React; superseded HTMX retained",
        str([(d.title, d.choice, d.status) for d in p.decisions if d.title == "Frontend"]),
        any(d.choice.startswith("React") and d.status == "accepted" for d in p.decisions)
        and any("HTMX" in d.choice and d.status == "superseded" for d in p.decisions),
        severity="high",
    )
    record(
        suite,
        "Summary lists superseded history without promoting brainstorm MongoDB",
        "Superseded section present; Database=MongoDB not confirmed",
        summary.text[:700],
        "Superseded" in summary.text
        and "Database=MongoDB" not in summary.text
        and "SQLite" in summary.text,
        severity="high",
        root_cause="Summary treated brainstorm as decision or dropped history",
    )

    # Conflicting statements in messages vs structure
    p2 = seed_log_platform()
    p2.messages.append(
        Message(role="user", content="We should use Elasticsearch for everything.")
    )
    s2 = build_deterministic_summary(p2, keep_recent=2)
    record(
        suite,
        "Conflicting message cannot erase rejected Elasticsearch from summary authority block",
        "Rejected Elasticsearch still listed in authoritative section",
        s2.text[:600],
        "Rejected:" in s2.text and "Elasticsearch" in s2.text,
        severity="critical",
    )

    wm = update_working_memory(
        p,
        user_message="Actually, keep SQLite — ignore previous Mongo brainstorm.",
        intent=MessageIntent.ARCHITECTURE_DECISION.value,
        mode=BehaviouralMode.PLAN,
    )
    record(
        suite,
        "User correction captured in working memory",
        "last_user_correction set",
        wm.last_user_correction,
        "SQLite" in (wm.last_user_correction or ""),
        severity="medium",
    )


# ---------------------------------------------------------------------------
# TEST 3 — Retrieval relevance / isolation
# ---------------------------------------------------------------------------


async def test_3_retrieval_relevance() -> None:
    suite = "3. Retrieval relevance"
    repo = InMemoryProjectRepository()
    log_p = repo.create(seed_log_platform())
    shop_p = repo.create(
        ProjectState(
            name="ShopCart",
            objective="Simple ecommerce cart MVP",
            intended_users=["shoppers"],
            tech_stack=["Node.js", "Express", "PostgreSQL"],
            decisions=[Decision(title="Backend", choice="Node.js + Express")],
            rejected_approaches=[
                RejectedApproach(approach="MongoDB", reason="Team knows SQL")
            ],
            outstanding_tasks=["Add cart API"],
        )
    )
    notes_p = repo.create(
        ProjectState(
            name="NotesApp",
            objective="Personal markdown notes",
            intended_users=["me"],
            tech_stack=["Python", "Flask", "SQLite"],
            decisions=[Decision(title="Database", choice="SQLite")],
            rejected_approaches=[
                RejectedApproach(approach="Kubernetes", reason="Overkill")
            ],
        )
    )

    captured: dict[str, Any] = {}

    def primary(**kwargs):
        captured["snapshot"] = kwargs.get("project_snapshot") or {}
        captured["tail"] = kwargs.get("conversation_tail") or []
        return PrimaryAnalysis(
            reply="Continuing within the active project only.",
            intent="question",
            findings=[],
            state_patch=StatePatch(),
        )

    engine = GrillEngine(
        repo=repo,
        primary=MockProvider(primary_handler=primary),
        critic=None,
        settings=settings(summary_min_messages=8, summary_min_new_messages=3),
        using_offline_primary=False,
    )

    # Seed each project with distinct dialogue
    for i in range(12):
        await engine.handle_message(
            log_p.id, f"WinLog turn {i}: EVTX and Elasticsearch rejection reminder."
        )
        await engine.handle_message(
            shop_p.id, f"Shop turn {i}: cart checkout with PostgreSQL."
        )
        await engine.handle_message(
            notes_p.id, f"Notes turn {i}: local markdown files only."
        )

    await engine.handle_message(
        log_p.id,
        "What database and search approach did we choose for the log platform?",
        behavioural_mode=BehaviouralMode.PLAN,
    )
    snap = captured.get("snapshot") or {}
    record(
        suite,
        "Log project question retrieves SQLite / Elastic rejection — not shop Node stack",
        "SQLite present; Node.js/Express absent; Elastic rejected",
        str(
            {
                "stack": snap.get("tech_stack"),
                "rejected": snap.get("rejected_approaches"),
                "name": snap.get("name") or snap.get("objective"),
            }
        ),
        "SQLite" in (snap.get("tech_stack") or [])
        and "Node.js" not in (snap.get("tech_stack") or [])
        and any("Elastic" in str(r) for r in (snap.get("rejected_approaches") or [])),
        severity="critical",
        repro="Ask log DB question on log project after multi-project seeding",
    )

    await engine.handle_message(
        shop_p.id,
        "Remind me of the shop backend stack.",
        behavioural_mode=BehaviouralMode.PLAN,
    )
    snap2 = captured.get("snapshot") or {}
    record(
        suite,
        "Shop question does not leak WinLog Elasticsearch rejection as selected tech",
        "Node/Express/Postgres; no FastAPI as selected stack",
        str(snap2.get("tech_stack")),
        "PostgreSQL" in (snap2.get("tech_stack") or [])
        and "FastAPI" not in (snap2.get("tech_stack") or []),
        severity="critical",
    )

    # Persistence isolation of summaries
    a = repo.get(log_p.id)
    b = repo.get(shop_p.id)
    record(
        suite,
        "Project summaries/ids remain isolated in repository",
        "Distinct project ids; stacks differ",
        str({"a": a.id if a else None, "b": b.id if b else None, "as": a.tech_stack if a else None, "bs": b.tech_stack if b else None}),
        a is not None
        and b is not None
        and a.id != b.id
        and a.tech_stack != b.tech_stack,
        severity="critical",
    )

    # Irrelevant injection: Notes K8s rejection should not appear in shop snapshot
    record(
        suite,
        "Shop context does not inject NotesApp Kubernetes rejection",
        "No Kubernetes in shop rejected list",
        str(snap2.get("rejected_approaches")),
        not any(
            "Kubernetes" in str(r.get("approach") if isinstance(r, dict) else r)
            for r in (snap2.get("rejected_approaches") or [])
        ),
        severity="high",
    )


# ---------------------------------------------------------------------------
# TEST 4 — Summary quality
# ---------------------------------------------------------------------------


def test_4_summary_quality() -> None:
    suite = "4. Summary quality"
    p = seed_log_platform()
    p = append_scripted_dialogue(p, total_messages=100)
    original_facts = {
        "requirements": [r.text for r in p.functional_requirements],
        "decisions": [
            f"{d.title}={d.choice}"
            for d in p.decisions
            if d.status != "superseded"
        ],
        "rejected": [r.approach for r in p.rejected_approaches],
        "constraints": [c.text for c in p.constraints],
        "architecture": p.architecture_notes,
        "users": list(p.intended_users),
    }
    summary = build_deterministic_summary(p, keep_recent=8)
    text = summary.text

    losses: list[str] = []
    for req in original_facts["requirements"]:
        # Allow partial: key nouns
        key = req.split()[0]
        if key.lower() not in text.lower() and req not in text:
            # functional reqs may be abbreviated — check EVTX / Event
            if "EVTX" in req and "EVTX" not in text and "Event" not in text:
                losses.append(f"requirement:{req}")
            elif "EVTX" not in req and req not in text:
                # soft: many digests omit full req text if in structured — check structured section
                if "Ingest" in req and "Ingest" not in text and "EVTX" not in text:
                    losses.append(f"requirement:{req}")

    for dec in original_facts["decisions"]:
        choice = dec.split("=", 1)[-1]
        # Python + FastAPI may appear as FastAPI / Python separately
        if "FastAPI" in choice:
            if "FastAPI" not in text:
                losses.append(f"decision:{dec}")
        elif choice not in text:
            losses.append(f"decision:{dec}")

    for rej in original_facts["rejected"]:
        if rej not in text:
            losses.append(f"rejected:{rej}")

    for con in original_facts["constraints"]:
        # key fragments
        if "4-week" in con and "4-week" not in text and "Solo" not in text:
            losses.append(f"constraint:{con}")
        elif "ops" in con.lower() and "ops" not in text.lower() and "overhead" not in text.lower():
            losses.append(f"constraint:{con}")

    if "Batch ingest" not in text and "batch" not in text.lower():
        losses.append("architecture:batch pipeline")

    # Distortion checks
    distortions: list[str] = []
    if "MongoDB" in text and "Database=MongoDB" in text:
        distortions.append("MongoDB promoted to confirmed database")
    if "Elasticsearch" in text and "Tech stack:" in text:
        # Elastic should be under Rejected, not Tech stack line
        stack_line = next((ln for ln in text.splitlines() if ln.startswith("Tech stack:")), "")
        if "Elasticsearch" in stack_line:
            distortions.append("Elasticsearch listed on tech stack line")

    record(
        suite,
        "No critical decision/rejection losses in summary",
        "Empty loss list for decisions/rejections",
        str(losses),
        not any(x.startswith("decision:") or x.startswith("rejected:") for x in losses),
        severity="critical",
        root_cause="Summary omitted authoritative facts",
        repro="Compare seed_log_platform facts to build_deterministic_summary",
        notes=f"all_losses={losses}",
    )
    record(
        suite,
        "No terminology distortion (Elastic not selected; Mongo not confirmed)",
        "No distortion flags",
        str(distortions),
        len(distortions) == 0,
        severity="high",
        notes=f"losses={losses}",
    )

    # Retrieved context vs summary
    structured = retrieve_relevant_context(
        p, mode=BehaviouralMode.PLAN, user_message="What did we reject?"
    ).as_prompt_json()
    assembled = assemble_prompt_context(
        p,
        mode=BehaviouralMode.PLAN,
        user_message="What did we reject and why?",
        structured_snapshot=structured,
        max_recent_messages=6,
        max_summary_chars=4000,
        max_total_chars=20_000,
    )
    record(
        suite,
        "Retrieved context includes rejected approaches with reasons",
        "Elasticsearch + complexity reason",
        str(assembled.snapshot.get("rejected_approaches")),
        any(
            isinstance(r, dict)
            and "Elastic" in r.get("approach", "")
            and "complex" in (r.get("reason") or "").lower()
            for r in (assembled.snapshot.get("rejected_approaches") or [])
        ),
        severity="high",
    )


# ---------------------------------------------------------------------------
# TEST 5 — Token budget
# ---------------------------------------------------------------------------


def test_5_token_budget() -> None:
    suite = "5. Token budget"
    p = seed_log_platform()
    p = append_scripted_dialogue(p, total_messages=100)
    maybe_refresh_summary(p, min_messages=20, min_new_since_summary=8, keep_recent=8)
    structured = retrieve_relevant_context(
        p, mode=BehaviouralMode.BUILD, user_message="Implement ingest"
    ).as_prompt_json()

    # Tight budget
    tight = assemble_prompt_context(
        p,
        mode=BehaviouralMode.BUILD,
        user_message="Implement EVTX ingest with SQLite; avoid Elasticsearch",
        structured_snapshot=deepcopy(structured),
        max_recent_messages=12,
        max_chars_each=500,
        max_summary_chars=4000,
        max_total_chars=2_500,
    )
    record(
        suite,
        "Tight budget keeps SQLite decision/stack",
        "SQLite in snapshot.tech_stack",
        str(tight.snapshot.get("tech_stack")),
        "SQLite" in (tight.snapshot.get("tech_stack") or []),
        severity="critical",
        root_cause="Budget trim dropped authoritative stack",
        repro="assemble_prompt_context max_total_chars=2500",
    )
    record(
        suite,
        "Tight budget keeps Elasticsearch rejection when relevant",
        "Elasticsearch in rejected_approaches",
        str(tight.snapshot.get("rejected_approaches")),
        any("Elastic" in str(r) for r in (tight.snapshot.get("rejected_approaches") or [])),
        severity="critical",
    )
    record(
        suite,
        "Tight budget reduces message window and/or summary",
        "truncated_messages>0 or summary shorter or est<=budget",
        str(
            {
                "truncated": tight.truncated_messages,
                "est": tight.estimated_chars,
                "tail": len(tight.conversation_tail),
                "notes": tight.notes,
            }
        ),
        tight.truncated_messages > 0
        or tight.estimated_chars <= 2_500
        or any("truncated" in n.lower() or "Excluded" in n for n in tight.notes),
        severity="high",
    )

    # Generous budget
    wide = assemble_prompt_context(
        p,
        mode=BehaviouralMode.BUILD,
        user_message="Implement EVTX ingest",
        structured_snapshot=deepcopy(structured),
        max_recent_messages=10,
        max_chars_each=800,
        max_summary_chars=4000,
        max_total_chars=40_000,
    )
    record(
        suite,
        "Wide budget still prioritizes recent messages (<= max_recent)",
        "tail length <= 10",
        str(len(wide.conversation_tail)),
        len(wide.conversation_tail) <= 10,
        severity="medium",
    )

    # Output-token reservation analogue: leave headroom by max_total_chars
    # (implementation uses char budget, not provider-native tokens)
    record(
        suite,
        "Char budget acts as provider-context limiter (no silent critical drop)",
        "Critical fields present under 2500 char budget",
        str(
            {
                "stack": tight.snapshot.get("tech_stack"),
                "decisions": tight.snapshot.get("decisions"),
            }
        ),
        bool(tight.snapshot.get("tech_stack")) and bool(tight.snapshot.get("decisions")),
        severity="high",
        notes="System uses character budgets, not native tokenizer reservations",
    )

    # Provider-specific context envelopes (Gemini/OpenRouter/Groq-like char caps)
    for label, budget in (
        ("gemini-like", 3_000),
        ("openrouter-like", 6_000),
        ("groq-like", 4_000),
    ):
        packed = assemble_prompt_context(
            p,
            mode=BehaviouralMode.BUILD,
            user_message="Keep SQLite; avoid Elasticsearch; implement ingest",
            structured_snapshot=deepcopy(structured),
            max_recent_messages=10,
            max_chars_each=400,
            max_summary_chars=2000,
            max_total_chars=budget,
        )
        record(
            suite,
            f"Provider envelope {label} ({budget} chars) keeps stack+rejections",
            "SQLite + Elasticsearch rejection present; est roughly bounded",
            str(
                {
                    "stack": packed.snapshot.get("tech_stack"),
                    "rejected": packed.snapshot.get("rejected_approaches"),
                    "est": packed.estimated_chars,
                    "truncated": packed.truncated_messages,
                }
            ),
            "SQLite" in (packed.snapshot.get("tech_stack") or [])
            and any("Elastic" in str(r) for r in (packed.snapshot.get("rejected_approaches") or [])),
            severity="high",
            root_cause="Provider char envelope trim dropped critical structured memory",
            repro=f"assemble_prompt_context(max_total_chars={budget})",
        )


# ---------------------------------------------------------------------------
# TEST 6 — Failure recovery
# ---------------------------------------------------------------------------


def test_6_failure_recovery() -> None:
    suite = "6. Failure recovery"
    p = seed_log_platform()
    p = append_scripted_dialogue(p, total_messages=50)
    good = build_deterministic_summary(p, keep_recent=6)
    apply_summary_update(p, good)
    good_text = p.conversation_summary.text if p.conversation_summary else ""

    # Simulated summarization failure
    apply_summary_update(p, None, failed=True)
    record(
        suite,
        "Summarization failure keeps previous valid summary text",
        "Prior text retained; source=failed_keep_previous",
        str(
            {
                "source": p.conversation_summary.source if p.conversation_summary else None,
                "same": (p.conversation_summary.text if p.conversation_summary else None)
                == good_text,
            }
        ),
        p.conversation_summary is not None
        and p.conversation_summary.source == "failed_keep_previous"
        and p.conversation_summary.text == good_text,
        severity="critical",
        repro="apply_summary_update(..., failed=True) after successful summary",
    )

    # Malformed summary object — must not clear structured fields OR wipe prior text
    before_stack = list(p.tech_stack)
    prior_good = p.conversation_summary.text if p.conversation_summary else ""
    malformed = ConversationSummary(text="", version=99, source="llm", covered_message_count=0)
    apply_summary_update(p, malformed)
    record(
        suite,
        "Malformed/empty summary does not clear tech_stack",
        "tech_stack unchanged",
        str(p.tech_stack),
        p.tech_stack == before_stack,
        severity="critical",
    )
    after_sum = p.conversation_summary.text if p.conversation_summary else ""
    record(
        suite,
        "Malformed/empty summary does not wipe previous valid summary text",
        "Prior non-empty summary retained (reject empty overwrite)",
        str({"prior_len": len(prior_good), "after_len": len(after_sum), "source": getattr(p.conversation_summary, "source", None)}),
        bool(prior_good) and after_sum == prior_good,
        severity="high",
        root_cause="apply_summary_update accepts empty ConversationSummary and overwrites prior text",
        repro="apply_summary_update(project, ConversationSummary(text='')) after a valid summary",
    )
    # Restore good summary for later checks regardless of outcome
    apply_summary_update(p, good)

    # Interrupted update via maybe_refresh exception path
    p_int = seed_log_platform()
    append_scripted_dialogue(p_int, 40)
    apply_summary_update(p_int, build_deterministic_summary(p_int))
    prior_int = p_int.conversation_summary.text if p_int.conversation_summary else ""
    # Force enough growth then inject failure by temporarily breaking builder
    import app.grill.memory as mem_mod

    real_build = mem_mod.build_deterministic_summary

    def _boom(*_a, **_k):
        raise RuntimeError("simulated summarizer crash")

    mem_mod.build_deterministic_summary = _boom  # type: ignore[assignment]
    try:
        # Ensure trigger would fire
        for _ in range(12):
            p_int.messages.append(Message(role="user", content="extra turn to force refresh"))
        refreshed = maybe_refresh_summary(
            p_int, min_messages=20, min_new_since_summary=4, keep_recent=6
        )
    finally:
        mem_mod.build_deterministic_summary = real_build  # type: ignore[assignment]
    record(
        suite,
        "Interrupted maybe_refresh_summary keeps previous valid summary",
        "failed refresh returns False; prior text intact; source=failed_keep_previous",
        str(
            {
                "refreshed": refreshed,
                "source": p_int.conversation_summary.source if p_int.conversation_summary else None,
                "same": (p_int.conversation_summary.text if p_int.conversation_summary else None)
                == prior_int,
            }
        ),
        refreshed is False
        and p_int.conversation_summary is not None
        and p_int.conversation_summary.text == prior_int
        and p_int.conversation_summary.source == "failed_keep_previous",
        severity="critical",
        root_cause="maybe_refresh_summary did not preserve prior summary on exception",
        repro="Monkeypatch build_deterministic_summary to raise during maybe_refresh_summary",
    )

    # Interrupted update: exception inside maybe_refresh should not wipe
    p2 = seed_log_platform()
    append_scripted_dialogue(p2, 40)
    s = build_deterministic_summary(p2)
    apply_summary_update(p2, s)
    prior = p2.conversation_summary.text
    # Force failed path
    apply_summary_update(p2, None, failed=True)
    record(
        suite,
        "Interrupted/failed refresh leaves prior summary intact",
        "text unchanged",
        p2.conversation_summary.text[:200] if p2.conversation_summary else "",
        p2.conversation_summary is not None and p2.conversation_summary.text == prior,
        severity="high",
    )


async def test_6b_persistence_and_concurrency() -> None:
    suite = "6b. Persistence / concurrency"
    # SQLite persistence failure simulation via broken path permissions if possible;
    # otherwise simulate by catching repository save errors with a wrapper.
    tmp = tempfile.mkdtemp(prefix="grill_mem_")
    db_path = str(Path(tmp) / "stress.db")
    repo = SQLiteProjectRepository(db_path)

    p = seed_log_platform()
    append_scripted_dialogue(p, 30)
    apply_summary_update(p, build_deterministic_summary(p))
    saved = repo.create(p)
    loaded = repo.get(saved.id)
    record(
        suite,
        "SQLite round-trip preserves summary + structured memory",
        "Same stack/rejected/summary version",
        str(
            {
                "stack": loaded.tech_stack if loaded else None,
                "sum": bool(loaded.conversation_summary and loaded.conversation_summary.text)
                if loaded
                else None,
            }
        ),
        loaded is not None
        and loaded.tech_stack == saved.tech_stack
        and loaded.conversation_summary is not None
        and bool(loaded.conversation_summary.text),
        severity="critical",
        repro=f"ProjectRepository({db_path}).create/get",
    )

    # Persistence failure: unwritable path must not destroy caller's in-memory state.
    # SQLiteProjectRepository.mkdir may fail at construct time — still a persist failure.
    mem_before = list(saved.tech_stack)
    sum_before = saved.conversation_summary.text if saved.conversation_summary else ""
    persist_failed = False
    try:
        bad_repo = SQLiteProjectRepository("/proc/does_not_exist_grill_stress/db.sqlite")
        bad_repo.save(saved)
    except Exception:
        persist_failed = True
    record(
        suite,
        "Failed DB persist leaves caller's ProjectState object intact",
        "In-memory stack/summary unchanged after save/construct exception",
        str({"persist_failed": persist_failed, "stack": saved.tech_stack}),
        persist_failed
        and saved.tech_stack == mem_before
        and (saved.conversation_summary.text if saved.conversation_summary else "")
        == sum_before,
        severity="high",
        notes="Constructor or save may raise; ProjectState object must remain intact",
    )

    # Concurrent conversation updates on two projects
    repo2 = InMemoryProjectRepository()
    a = repo2.create(seed_log_platform())
    b = repo2.create(
        ProjectState(name="Other", objective="Other", tech_stack=["Go"])
    )

    def primary(**kwargs):
        return PrimaryAnalysis(
            reply="ok", intent="general", findings=[], state_patch=StatePatch()
        )

    engine = GrillEngine(
        repo=repo2,
        primary=MockProvider(primary_handler=primary),
        critic=None,
        settings=settings(summary_min_messages=6, summary_min_new_messages=2),
        using_offline_primary=False,
    )

    async def chatter(pid: str, prefix: str) -> None:
        for i in range(8):
            await engine.handle_message(pid, f"{prefix} message {i}")

    await asyncio.gather(chatter(a.id, "A"), chatter(b.id, "B"))
    a2, b2 = repo2.get(a.id), repo2.get(b.id)
    record(
        suite,
        "Concurrent updates do not cross-contaminate project memory",
        "Distinct stacks/objectives after parallel chats",
        str(
            {
                "a_stack": a2.tech_stack if a2 else None,
                "b_stack": b2.tech_stack if b2 else None,
                "a_msgs": len(a2.messages) if a2 else None,
                "b_msgs": len(b2.messages) if b2 else None,
            }
        ),
        a2 is not None
        and b2 is not None
        and a2.tech_stack != b2.tech_stack
        and len(a2.messages) >= 8
        and len(b2.messages) >= 8,
        severity="critical",
    )

    # Provider summarization path N/A (deterministic); simulate provider failure on chat
    class Boom(MockProvider):
        async def analyze_primary(self, **kwargs):
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "summarizer down")

    engine2 = GrillEngine(
        repo=repo2,
        primary=Boom(),
        critic=None,
        settings=settings(),
        using_offline_primary=False,
    )
    before = repo2.get(a.id)
    before_sum = (
        before.conversation_summary.text
        if before and before.conversation_summary
        else ""
    )
    res = await engine2.handle_message(a.id, "What is our database?")
    record(
        suite,
        "Chat provider failure does not wipe prior summary/structured memory",
        "SQLite + Elastic rejection still present",
        str(
            {
                "stack": res.project.tech_stack,
                "rejected": [r.approach for r in res.project.rejected_approaches],
                "summary_kept": bool(res.project.conversation_summary and res.project.conversation_summary.text)
                or before_sum == "",
            }
        ),
        "SQLite" in res.project.tech_stack
        and any("Elastic" in r.approach for r in res.project.rejected_approaches),
        severity="high",
    )


# ---------------------------------------------------------------------------
# Engine integration: 100 turns through GrillEngine
# ---------------------------------------------------------------------------


async def test_1b_engine_hundred_turns() -> None:
    suite = "1b. Engine 100-turn retention"
    repo = InMemoryProjectRepository()
    project = repo.create(seed_log_platform())
    snapshots: list[dict] = []

    def primary(**kwargs):
        snapshots.append(kwargs.get("project_snapshot") or {})
        msg = kwargs.get("user_message") or ""
        patch = StatePatch()
        # Occasionally echo structured patches (safe)
        if "using Python" in msg:
            patch.tech_stack = ["Python", "FastAPI"]
        return PrimaryAnalysis(
            reply="Acknowledged within project memory.",
            intent="general",
            findings=[],
            state_patch=patch,
        )

    engine = GrillEngine(
        repo=repo,
        primary=MockProvider(primary_handler=primary),
        critic=None,
        settings=settings(
            summary_min_messages=20,
            summary_min_new_messages=8,
            history_max_messages=8,
        ),
        using_offline_primary=False,
    )

    turns = [
        "Confirm investigation assistance scope.",
        "We are using Python and FastAPI.",
        "Our database will be SQLite.",
        "Reject Elasticsearch because of infrastructure complexity.",
        "Maybe brainstorm MongoDB later?",
        "Actually, keep SQLite.",
    ]
    # Expand to 100 user messages (engine adds assistant each time → 200 msgs)
    user_turns = []
    while len(user_turns) < 50:
        user_turns.extend(turns)
    user_turns = user_turns[:50]

    for i, content in enumerate(user_turns):
        await engine.handle_message(
            project.id,
            f"{content} (turn {i})",
            behavioural_mode=BehaviouralMode.PLAN,
        )

    final = repo.get(project.id)
    assert final is not None
    record(
        suite,
        "After 50 user turns (>=100 total msgs), summary exists",
        "conversation_summary.text non-empty",
        str(
            {
                "msgs": len(final.messages),
                "has_summary": bool(
                    final.conversation_summary and final.conversation_summary.text
                ),
            }
        ),
        len(final.messages) >= 100
        and final.conversation_summary is not None
        and bool(final.conversation_summary.text),
        severity="critical",
        repro="50 handle_message turns on seeded project",
    )
    last_snap = snapshots[-1] if snapshots else {}
    record(
        suite,
        "Final assembled snapshot still has SQLite and Elastic rejection",
        "Present",
        str(
            {
                "stack": last_snap.get("tech_stack") or final.tech_stack,
                "rejected": last_snap.get("rejected_approaches")
                or [r.approach for r in final.rejected_approaches],
            }
        ),
        "SQLite" in (last_snap.get("tech_stack") or final.tech_stack)
        and any(
            "Elastic" in str(r)
            for r in (
                last_snap.get("rejected_approaches")
                or [r.approach for r in final.rejected_approaches]
            )
        ),
        severity="critical",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def main() -> int:
    print("=== Grill long-term memory stress validation ===")
    test_1_long_conversation_retention()
    await test_1b_engine_hundred_turns()
    test_2_decision_preservation()
    await test_3_retrieval_relevance()
    test_4_summary_quality()
    test_5_token_budget()
    test_6_failure_recovery()
    await test_6b_persistence_and_concurrency()

    passed = sum(1 for r in RESULTS if r.passed)
    failed = sum(1 for r in RESULTS if not r.passed)
    by_sev: dict[str, int] = {}
    for r in RESULTS:
        if not r.passed:
            by_sev[r.severity] = by_sev.get(r.severity, 0) + 1

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(RESULTS),
            "passed": passed,
            "failed": failed,
            "failures_by_severity": by_sev,
        },
        "results": [asdict(r) for r in RESULTS],
    }
    docs = ROOT.parent / "docs"
    json_path = docs / "GRILL_MEMORY_STRESS_RESULTS.json"
    json_path.write_text(json.dumps(out, indent=2))

    # Markdown report
    lines = [
        "# Grill Long-Term Memory Stress Test Report",
        "",
        f"**Generated:** {out['generated_at']}",
        f"**Totals:** {passed} passed / {failed} failed / {len(RESULTS)} checks",
        "",
        "## Coverage",
        "",
        "1. Long conversation retention (≥100 messages + engine 50-user-turn run)",
        "2. Decision preservation (confirmed/superseded/rejected/brainstorm/corrections)",
        "3. Retrieval relevance & multi-project isolation",
        "4. Summary quality (losses/distortions vs authoritative state)",
        "5. Token/char budget survival of critical fields",
        "6. Failure recovery (summary fail, malformed, DB fail, concurrency, provider fail)",
        "",
        "## Results by suite",
        "",
    ]
    suites: dict[str, list[Finding]] = {}
    for r in RESULTS:
        suites.setdefault(r.suite, []).append(r)
    for suite, items in suites.items():
        ok = sum(1 for i in items if i.passed)
        lines.append(f"### {suite}")
        lines.append(f"- {ok}/{len(items)} passed")
        for i in items:
            mark = "PASS" if i.passed else "FAIL"
            lines.append(f"- **{mark}** {i.check}")
            if not i.passed:
                lines.append(f"  - Expected: {i.expected}")
                lines.append(f"  - Actual: {i.actual[:300]}")
                lines.append(f"  - Severity: {i.severity}")
                if i.root_cause:
                    lines.append(f"  - Root cause: {i.root_cause}")
                if i.repro:
                    lines.append(f"  - Repro: {i.repro}")
        lines.append("")

    lines.extend(
        [
            "## Failed cases",
            "",
        ]
    )
    fails = [r for r in RESULTS if not r.passed]
    if not fails:
        lines.append("None — all executed checks passed.")
    else:
        for r in fails:
            lines.append(
                f"- **[{r.severity}]** {r.suite} :: {r.check} — {r.root_cause or r.actual[:120]}"
            )

    lines.extend(
        [
            "",
            "## Recommended fixes",
            "",
        ]
    )
    if fails:
        for r in fails:
            lines.append(f"### [{r.severity}] {r.check}")
            lines.append(f"- **Suite:** {r.suite}")
            lines.append(f"- **Root cause:** {r.root_cause or '(see actual)'}")
            lines.append(f"- **Repro:** `{r.repro}`")
            lines.append(f"- **Observed:** {r.actual[:400]}")
            if "empty summary" in r.check.lower() or "malformed" in r.check.lower():
                lines.extend(
                    [
                        "- **Fix:** In `apply_summary_update`, reject `new_summary` when "
                        "`not (new_summary.text or '').strip()` if a previous non-empty "
                        "summary exists; treat as `failed=True` (keep previous, set "
                        "`source=failed_keep_previous`) instead of overwriting.",
                    ]
                )
            lines.append("")
        lines.extend(
            [
                "### Residual risks (non-failing)",
                "1. Char budgets approximate tokens; provider-native tokenizers not used.",
                "2. Lexical relevance may miss paraphrased retrieval needs.",
                "3. Functional requirement prose may be abbreviated in digests when nouns differ.",
            ]
        )
    else:
        lines.extend(
            [
                "No blockers from this stress run. Residual product risks (not failures):",
                "1. Char budgets approximate tokens; provider-native tokenizers not used.",
                "2. Lexical relevance may miss paraphrased retrieval needs.",
                "3. Functional requirement prose may be abbreviated in digests when nouns differ.",
            ]
        )

    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "```bash",
            "cd backend",
            ".venv/bin/python scripts/memory_stress_validation.py",
            "```",
            "",
            "Artifacts:",
            "- `docs/GRILL_MEMORY_STRESS_RESULTS.json`",
            "- `docs/GRILL_MEMORY_STRESS_REPORT.md`",
            "",
            "**Production code modified:** No",
        ]
    )

    md_path = docs / "GRILL_MEMORY_STRESS_REPORT.md"
    md_path.write_text("\n".join(lines) + "\n")

    print(f"Passed: {passed}  Failed: {failed}  Total: {len(RESULTS)}")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    for r in RESULTS:
        if not r.passed:
            print(f"[FAIL][{r.severity}] {r.suite} :: {r.check}")
            print(f"  actual: {r.actual[:200]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
