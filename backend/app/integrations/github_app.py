"""GitHub App webhook — Grill review on PR description / spec docs."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

logger = logging.getLogger("vibeprompt.github")


def verify_github_signature(
    *,
    payload: bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    """Validate X-Hub-Signature-256 (sha256=...). Empty secret skips verify in dev only."""
    if not (secret or "").strip():
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = signature_header.split("=", 1)[1].strip()
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected)


def extract_pr_review_brief(event: dict[str, Any]) -> dict[str, Any] | None:
    """
    Build a Grill project brief from a pull_request webhook payload.

    Returns None when the event should be ignored.
    """
    action = event.get("action")
    if action not in {"opened", "edited", "reopened", "synchronize"}:
        return None
    pr = event.get("pull_request") or {}
    if not pr:
        return None
    repo = (event.get("repository") or {}).get("full_name") or "unknown/repo"
    number = pr.get("number")
    title = (pr.get("title") or "").strip() or f"PR #{number}"
    body = (pr.get("body") or "").strip()
    html_url = pr.get("html_url") or ""
    user = ((pr.get("user") or {}).get("login")) or "unknown"

    initial = "\n\n".join(
        [
            f"GitHub PR review request for {repo}#{number} by @{user}.",
            f"Title: {title}",
            f"URL: {html_url}",
            "PR description / spec:",
            body or "(empty PR body — challenge missing evidence and scope)",
            "Run an adversarial Grill review. Flag blocking contradictions and "
            "readiness gaps before merge/implementation.",
        ]
    )
    return {
        "name": f"{repo}#{number}: {title}"[:120],
        "objective": f"Gate merge for {repo}#{number}",
        "initial_message": initial[:16_000],
        "meta": {
            "repo": repo,
            "pr_number": number,
            "html_url": html_url,
            "action": action,
            "sender": user,
        },
    }


def format_check_conclusion(readiness: dict[str, Any]) -> dict[str, Any]:
    """Map readiness → GitHub Check Run-like conclusion payload (for app to post)."""
    ready = bool(
        readiness.get("implementation_ready") or readiness.get("ready")
    )
    blockers = readiness.get("blockers") or []
    score = readiness.get("score_pct")
    summary = (
        f"VibePrompt Grill readiness: {'PASS' if ready else 'BLOCKED'}"
        f" (score={score})"
    )
    text_lines = [summary, ""]
    if blockers:
        text_lines.append("Blockers:")
        text_lines.extend(f"- {b}" for b in blockers[:20])
    else:
        text_lines.append("No hard blockers listed.")
    return {
        "conclusion": "success" if ready else "failure",
        "title": "VibePrompt Grill",
        "summary": summary,
        "text": "\n".join(text_lines),
        "ready": ready,
        "score_pct": score,
        "blockers": blockers,
    }


def parse_event(payload: bytes) -> dict[str, Any]:
    return json.loads(payload.decode("utf-8"))
