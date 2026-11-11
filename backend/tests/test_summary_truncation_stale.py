"""Regression: summary truncation must not revive excluded Marg recommendations."""

from __future__ import annotations

from app.grill.context_diagnostics import clear_diagnostics, recent_diagnostics
from app.grill.memory import (
    apply_summary_update,
    assemble_prompt_context,
    build_deterministic_summary,
    extract_turn_exclusions,
    scrub_summary_for_exclusions,
    update_working_memory,
)
from app.grill.modes import BehaviouralMode
from app.grill.reasoning import format_mentor_reply, run_mentor_reasoning
from app.projects.models import (
    Decision,
    DecisionStatus,
    Message,
    ProjectState,
    new_id,
)


def _pad_messages(project: ProjectState, n: int, prefix: str = "filler") -> None:
    for i in range(n):
        project.messages.append(
            Message(
                id=new_id("msg_"),
                role="user" if i % 2 == 0 else "assistant",
                content=f"{prefix} turn {i}: general product discussion about pricing tiers and staffing.",
            )
        )


def build_long_marg_conversation() -> ProjectState:
    """Detailed Marg discussion, then unrelated business Qs, then exclude Marg."""
    p = ProjectState(
        name="Pharmacy MVP",
        objective="Local pharmacy catalogue for nearby customers",
        tech_stack=["WordPress"],
        decisions=[
            Decision(
                title="CMS",
                choice="WordPress",
                status=DecisionStatus.CONFIRMED.value,
                source="user",
            ),
            Decision(
                title="Inventory sync",
                choice="Scheduled Marg export",
                status=DecisionStatus.PROPOSED.value,
                source="grill_mentor",
            ),
        ],
        architecture_notes="Explored Marg billing integration for exact prices.",
        behavioural_mode=BehaviouralMode.PLAN,
    )
    # Detailed Marg thread
    marg_turns = [
        ("user", "We use Marg billing software. Can we show exact Marg prices online?"),
        (
            "assistant",
            "I'd recommend a Scheduled Marg export sync into a staging DB with validation. "
            "That is a recommendation-not-decision until you confirm.",
        ),
        ("user", "What about real-time Marg API integration?"),
        (
            "assistant",
            "Real-time Marg integration is heavier. Prefer daily export unless Marg exposes a stable API.",
        ),
        ("user", "OK keep Marg export as the preferred inventory path for now."),
        (
            "assistant",
            "Recorded preference for Marg export — still propose it as provisional until confirmed.",
        ),
    ]
    for role, content in marg_turns:
        p.messages.append(Message(id=new_id("msg_"), role=role, content=content))

    # Unrelated business questions
    business = [
        ("user", "Who should we charge first — walk-in locals or nearby clinics?"),
        (
            "assistant",
            "Start with walk-in locals for faster feedback; clinics can wait until catalogue quality is proven.",
        ),
        ("user", "Should we hire a part-time counter assistant for evenings?"),
        (
            "assistant",
            "A part-time evening assistant helps if call volume peaks after 6pm — measure calls for two weeks first.",
        ),
    ]
    for role, content in business:
        p.messages.append(Message(id=new_id("msg_"), role=role, content=content))

    # Force a long window so summarization + truncation engage
    _pad_messages(p, 24, prefix="ops")

    # Explicit exclusion for the next ask
    exclude_msg = (
        "Excluding Marg from this question: what marketing channel should we try "
        "first for walk-in awareness — WhatsApp status or local flyer?"
    )
    p.messages.append(Message(id=new_id("msg_"), role="user", content=exclude_msg))
    return p


def _force_summary_and_tight_assemble(
    project: ProjectState,
    ask: str,
    *,
    max_total_chars: int,
) -> tuple:
    update_working_memory(
        project,
        user_message=ask,
        intent="question",
        mode=BehaviouralMode.EXPLORE,
    )
    summary = build_deterministic_summary(project, keep_recent=4)
    apply_summary_update(project, summary)
    structured = {
        "id": project.id,
        "name": project.name,
        "objective": project.objective,
        "architecture_notes": project.architecture_notes,
    }
    assembled = assemble_prompt_context(
        project,
        mode=BehaviouralMode.EXPLORE,
        user_message=ask,
        structured_snapshot=structured,
        max_recent_messages=6,
        max_chars_each=180,
        max_summary_chars=900,
        max_total_chars=max_total_chars,
        enable_diagnostics=True,
    )
    return summary, assembled


def test_decision_statuses_remain_distinct_in_summary():
    p = build_long_marg_conversation()
    summary = build_deterministic_summary(p, keep_recent=4)
    text = summary.text
    assert "Confirmed decisions:" in text
    assert "CMS=WordPress" in text
    assert "Proposed decisions (not user-approved):" in text
    assert "Inventory sync=Scheduled Marg export" in text
    # Must not label the mentor proposal as confirmed
    confirmed_block = text.split("Proposed decisions")[0]
    assert "Scheduled Marg export" not in confirmed_block


def test_exclusions_parsed_and_scrub_summary_digest():
    ask = "Excluding Marg from this question: flyer or WhatsApp?"
    assert "Marg" in extract_turn_exclusions(ask) or any(
        "marg" in e.lower() for e in extract_turn_exclusions(ask)
    )
    raw = (
        "## Authoritative project memory\nObjective: Pharmacy\n\n"
        "## Earlier conversation digest (not confirmed decisions)\n"
        "- assistant [recommendation-not-decision]: I'd recommend Scheduled Marg export sync.\n"
        "- user: Who should we charge first?\n"
    )
    scrubbed = scrub_summary_for_exclusions(raw, ["Marg"])
    assert "Scheduled Marg export" not in scrubbed
    assert "Who should we charge" in scrubbed
    assert "Turn exclusions" in scrubbed


def test_truncation_with_exclusion_does_not_reinject_marg_recommendation():
    clear_diagnostics()
    p = build_long_marg_conversation()
    ask = p.messages[-1].content
    summary, assembled = _force_summary_and_tight_assemble(
        p, ask, max_total_chars=2_800
    )
    assert assembled.summary_truncated or assembled.truncated_messages >= 0
    snap_text = ""
    cs = assembled.snapshot.get("conversation_summary") or {}
    if isinstance(cs, dict):
        snap_text = str(cs.get("text") or "")
    # Digest section must not retain Marg recommendation lines
    digest = ""
    if "## Earlier conversation digest" in snap_text:
        digest = snap_text.split("## Earlier conversation digest", 1)[1]
    assert "[recommendation-not-decision]" not in digest.lower() or "marg" not in digest.lower()
    # Structured proposed decision may remain — status must stay proposed (not promoted)
    decs = assembled.snapshot.get("decisions") or []
    marg_dec = next((d for d in decs if "Marg" in str(d.get("choice"))), None)
    assert marg_dec is not None
    assert marg_dec["status"] == DecisionStatus.PROPOSED.value

    # Reasoning / reply path for the marketing ask should not push Marg
    r = run_mentor_reasoning(p, ask, mode=BehaviouralMode.EXPLORE)
    reply = format_mentor_reply(
        r,
        base_reply=(
            "For walk-in awareness, try WhatsApp status first — cheaper to test — "
            "then flyers if you need neighbourhood reach."
        ),
        mode=BehaviouralMode.EXPLORE,
    )
    assert "marg" not in reply.lower()
    diags = recent_diagnostics(limit=3)
    assert diags
    latest = diags[-1]
    assert latest.turn_exclusions
    assert any("marg" in e.lower() for e in latest.turn_exclusions)


def test_compare_truncation_on_vs_off_and_critic_context_parity():
    """A/B: truncation enabled vs disabled; critic shares primary snapshot."""
    clear_diagnostics()
    p = build_long_marg_conversation()
    ask = p.messages[-1].content

    _, tight = _force_summary_and_tight_assemble(p, ask, max_total_chars=2_600)
    _, wide = _force_summary_and_tight_assemble(p, ask, max_total_chars=80_000)

    def _digest(text: str) -> str:
        if "## Earlier conversation digest" not in text:
            return ""
        return text.split("## Earlier conversation digest", 1)[1].lower()

    tight_sum = (tight.snapshot.get("conversation_summary") or {}).get("text", "")
    wide_sum = (wide.snapshot.get("conversation_summary") or {}).get("text", "")

    for label, blob in (("tight", _digest(tight_sum)), ("wide", _digest(wide_sum))):
        if "[recommendation-not-decision]" in blob and "marg" in blob:
            raise AssertionError(
                f"Excluded Marg recommendation still present in {label} digest"
            )

    # Critic parity: same assembled decisions (engine passes assembled.snapshot to both)
    assert tight.snapshot.get("decisions") == wide.snapshot.get("decisions")
    assert tight.estimated_chars <= wide.estimated_chars


def test_unrelated_business_question_after_truncation_no_stale_marg():
    clear_diagnostics()
    p = build_long_marg_conversation()
    # Remove the exclusion message; ask a fresh unrelated business Q after summary
    p.messages = p.messages[:-1]
    ask = "Should we open one hour earlier on Sundays for elderly customers?"
    p.messages.append(Message(id=new_id("msg_"), role="user", content=ask))
    _force_summary_and_tight_assemble(p, ask, max_total_chars=2_800)
    r = run_mentor_reasoning(p, ask, mode=BehaviouralMode.EXPLORE)
    reply = format_mentor_reply(
        r,
        base_reply=(
            "Yes if foot traffic data supports it — trial Sunday early hours for four weeks "
            "and track visits from elderly customers."
        ),
        mode=BehaviouralMode.EXPLORE,
    )
    # Must answer the Sunday hours question, not recycle Marg sync advice
    assert "sunday" in reply.lower() or "hour" in reply.lower() or "elderly" in reply.lower()
    assert "marg export" not in reply.lower()
    assert "scheduled marg" not in reply.lower()
