"""Allow `python -m app --demo` to launch uvicorn in demo (offline) mode."""

from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="VibePrompt API server")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Force offline-heuristic Grill (no live provider calls)",
    )
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    if args.demo:
        os.environ["DEMO_MODE"] = "true"

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
