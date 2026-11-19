"""CLI: python -m app.cli review --project ./path  (local pre-commit gating)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_brief(project_dir: Path) -> dict:
    for name in ("vibeprompt.json", "VIBEPROMPT.md", "SPEC.md", "README.md"):
        path = project_dir / name
        if not path.exists():
            continue
        if path.suffix.lower() == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        text = path.read_text(encoding="utf-8")
        return {
            "name": project_dir.name,
            "objective": text[:2000],
            "initial_message": text[:4000],
        }
    return {
        "name": project_dir.name,
        "objective": f"Review local project at {project_dir}",
        "initial_message": (
            f"Review this codebase/project directory named {project_dir.name}. "
            "Challenge weak assumptions and blocked readiness for agent implementation."
        ),
    }


def cmd_review(args: argparse.Namespace) -> int:
    """Run a Grill readiness check against a local folder via the API or offline gate."""
    project_dir = Path(args.project).resolve()
    if not project_dir.is_dir():
        print(f"error: not a directory: {project_dir}", file=sys.stderr)
        return 2

    brief = _load_brief(project_dir)
    api_base = (args.api_base or "").rstrip("/")
    token = args.token or ""

    if api_base:
        import urllib.error
        import urllib.request

        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        def post(path: str, body: dict) -> dict:
            req = urllib.request.Request(
                f"{api_base}{path}",
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))

        def get(path: str) -> dict:
            req = urllib.request.Request(f"{api_base}{path}", headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))

        try:
            project = post(
                "/projects",
                {
                    "name": brief.get("name") or project_dir.name,
                    "objective": brief.get("objective") or "",
                    "initial_message": brief.get("initial_message") or "",
                },
            )
            readiness = get(f"/projects/{project['id']}/readiness")
        except urllib.error.HTTPError as exc:
            print(f"error: API {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    else:
        # Offline local heuristic gate — no network.
        from app.compilation.readiness import assess_readiness
        from app.projects.models import ProjectState

        project_state = ProjectState(
            name=str(brief.get("name") or project_dir.name),
            objective=str(brief.get("objective") or ""),
        )
        readiness = assess_readiness(project_state).model_dump()
        print(
            "note: offline local gate (no API). Pass --api-base for live Grill review.",
            file=sys.stderr,
        )

    ready = bool(readiness.get("implementation_ready") or readiness.get("ready"))
    score = readiness.get("score_pct")
    blockers = readiness.get("blockers") or []
    print(json.dumps({"ready": ready, "score_pct": score, "blockers": blockers}, indent=2))
    if args.fail_on_block and not ready:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vibe-prompt",
        description="VibePrompt CLI — local Grill / readiness gating",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="Gate a local project before agent runs")
    review.add_argument("--project", "-p", default=".", help="Project directory")
    review.add_argument(
        "--api-base",
        default="",
        help="API base including /api or /api/v1 (empty = offline heuristic)",
    )
    review.add_argument("--token", default="", help="Bearer token")
    review.add_argument(
        "--fail-on-block",
        action="store_true",
        help="Exit 1 when readiness gate fails (for pre-commit)",
    )
    review.set_defaults(func=cmd_review)

    # Integration stubs (documented surface)
    gh = sub.add_parser(
        "github-app-info",
        help="Print how to wire the GitHub App Grill-on-PR integration",
    )
    gh.set_defaults(
        func=lambda _a: (
            print(
                json.dumps(
                    {
                        "status": "stub",
                        "hook": "pull_request.opened|edited",
                        "action": "POST /api/v1/projects with PR body as initial_message",
                        "gate": "require readiness.implementation_ready before merge",
                    },
                    indent=2,
                )
                or 0
            )
        )
    )

    agent = sub.add_parser(
        "agent-plugin-info",
        help="Print Cursor/Codex/Antigravity readiness injection contract",
    )
    agent.set_defaults(
        func=lambda _a: (
            print(
                json.dumps(
                    {
                        "status": "stub",
                        "inject": "Call GET /projects/{id}/readiness before agent implementation",
                        "export": "POST /projects/{id}/agent-prompt when implementation_ready",
                    },
                    indent=2,
                )
                or 0
            )
        )
    )

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
