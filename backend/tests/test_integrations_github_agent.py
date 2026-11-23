"""GitHub webhook + agent readiness gate integrations."""

from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.integrations.agent_gate import build_gate_status, plugin_manifest
from app.integrations.github_app import (
    extract_pr_review_brief,
    format_check_conclusion,
    verify_github_signature,
)
from app.main import create_app
from app.projects.models import Finding, FindingStatus, ProjectState


def test_verify_github_signature():
    secret = "whsec_test"
    body = b'{"action":"opened"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_github_signature(
        payload=body, signature_header=sig, secret=secret
    )
    assert not verify_github_signature(
        payload=body, signature_header="sha256=dead", secret=secret
    )


def test_extract_pr_brief_and_check():
    event = {
        "action": "opened",
        "repository": {"full_name": "acme/app"},
        "pull_request": {
            "number": 7,
            "title": "Add billing",
            "body": "We will use SQLite on Vercel serverless.",
            "html_url": "https://github.com/acme/app/pull/7",
            "user": {"login": "dev"},
        },
    }
    brief = extract_pr_review_brief(event)
    assert brief is not None
    assert "acme/app#7" in brief["name"]
    assert "SQLite" in brief["initial_message"]

    check = format_check_conclusion(
        {"implementation_ready": False, "ready": False, "score_pct": 20, "blockers": ["x"]}
    )
    assert check["conclusion"] == "failure"
    assert check["ready"] is False


def test_agent_gate_blocks_on_open_blocking():
    project = ProjectState(name="P", objective="o")
    project.findings.append(
        Finding(
            id="f1",
            title="Contradiction",
            challenged_claim="claim",
            reasoning="r",
            severity="critical",
            kind="blocking_contradiction",
            status=FindingStatus.OPEN,
        )
    )
    gate = build_gate_status(project)
    assert gate["allow_implementation"] is False
    assert len(gate["blocking_findings"]) == 1
    assert plugin_manifest()["agents"] == ["cursor", "codex", "antigravity"]


def test_github_webhook_ping_and_pr(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "t.db"
        settings = Settings(
            app_env="development",
            database_path=str(db),
            database_backend="sqlite",
            jwt_secret="integration-test-jwt-secret-32chars!",
            credentials_encryption_key="integration-test-creds-secret-32c!",
            free_tier_enabled=False,
            demo_mode=True,
            api_secret="",
            github_webhook_secret="gh_secret",
        )

        def _gs():
            return settings

        monkeypatch.setattr("app.api.deps.get_settings", _gs)
        monkeypatch.setattr("app.config.get_settings", _gs)
        monkeypatch.setattr("app.main.get_settings", _gs)
        from app.api import deps

        deps.get_repository.cache_clear()
        deps.get_user_store.cache_clear()
        deps.get_knowledge_store.cache_clear()
        deps.get_skill_registry.cache_clear()
        deps.get_provider_bundle.cache_clear()

        app = create_app(settings)
        client = TestClient(app)

        ping = client.post(
            "/api/v1/integrations/github/webhook",
            content=b"{}",
            headers={
                "X-GitHub-Event": "ping",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(b"gh_secret", b"{}", hashlib.sha256).hexdigest(),
            },
        )
        assert ping.status_code == 200
        assert ping.json().get("pong") is True

        event = {
            "action": "opened",
            "repository": {"full_name": "acme/app"},
            "pull_request": {
                "number": 1,
                "title": "Spec",
                "body": "Ship SQLite on serverless edge.",
                "html_url": "https://github.com/acme/app/pull/1",
                "user": {"login": "dev"},
            },
        }
        raw = json.dumps(event).encode()
        resp = client.post(
            "/api/v1/integrations/github/webhook",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(b"gh_secret", raw, hashlib.sha256).hexdigest(),
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["project_id"]
        assert "check" in body

        gate = client.get(f"/api/v1/integrations/agent-gate/{body['project_id']}")
        assert gate.status_code == 200
        assert "allow_implementation" in gate.json()
