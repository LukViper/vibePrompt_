"""Phase 2: ROI metrics, org rejected library, vertical skills, CLI review."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.persistence.user_store import UserStore
from app.skills.verticals import playbook_to_skill, vertical_skill_packs


def test_roi_snapshot_estimates_tokens():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "t.db"
        store = UserStore(str(db))
        user = store.create_user(email="roi@example.com", password_hash="x")
        org_id = store.ensure_user_org(user.id, user.email)
        store.record_roi_event(
            org_id=org_id,
            event_type="finding_blocked_from_impl",
            project_id="p1",
            user_id=user.id,
            payload={"project_id": "p1"},
        )
        store.record_roi_event(
            org_id=org_id,
            event_type="readiness_pass",
            project_id="p1",
            payload={"project_id": "p1"},
        )
        store.report_agent_runs(
            org_id=org_id,
            project_id="p1",
            user_id=user.id,
            runs_before=5,
            runs_after=1,
        )
        dash = store.org_roi_dashboard(org_id)
        assert dash["findings_blocked_from_implementation"] == 1
        assert dash["readiness_gate_passes"] == 1
        assert dash["estimated_tokens_saved"] > 0
        assert dash["agent_runs_before"] == 5
        assert dash["agent_runs_after"] == 1


def test_org_rejected_and_comments():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "t.db"
        store = UserStore(str(db))
        user = store.create_user(email="collab@example.com", password_hash="x")
        org_id = store.ensure_user_org(user.id, user.email)
        store.upsert_org_rejected_approach(
            org_id=org_id,
            approach="Vercel serverless API",
            reason="multi-writer SQLite",
            created_by=user.id,
        )
        items = store.list_org_rejected_approaches(org_id)
        assert len(items) == 1
        assert "Vercel" in items[0]["approach"]

        c = store.add_finding_comment(
            org_id=org_id,
            project_id="p1",
            finding_id="f1",
            user_id=user.id,
            body="Need evidence for @peer",
            mention_user_ids=[user.id],
        )
        assert c["id"]
        comments = store.list_finding_comments(project_id="p1", finding_id="f1")
        assert len(comments) == 1
        notes = store.list_notifications(user.id)
        assert any(n["kind"] == "mention" for n in notes)


def test_vertical_packs_and_playbook_skill():
    packs = vertical_skill_packs()
    assert {p.slug for p in packs} >= {
        "vertical_healthtech_compliance",
        "vertical_fintech_controls",
        "vertical_saas_tenancy",
    }
    skill = playbook_to_skill(
        org_id="org_abc",
        title="Internal security playbook",
        content="- Encrypt PII at rest\n- Require MFA for admins\n",
        vertical="saas",
    )
    assert skill.slug.startswith("org_")
    assert len(skill.principles) >= 2


def test_cli_review_offline(tmp_path: Path):
    from app.cli import main

    proj = tmp_path / "demo"
    proj.mkdir()
    (proj / "README.md").write_text("# Demo\nShip faster with care.\n", encoding="utf-8")
    code = main(["review", "--project", str(proj)])
    assert code == 0
