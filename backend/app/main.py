"""VibePrompt Invisible Grill — FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    # Touch repository so DB is created at startup
    from app.api.deps import get_repository

    get_repository()
    status = settings.provider_status()
    order = ",".join(status.get("provider_order") or [])  # type: ignore[arg-type]
    print(
        "VibePrompt ready | "
        f"chain={order or 'none'} | "
        f"external={'yes' if status['primary_available'] else 'offline-heuristic'} | "
        f"critic={'yes' if status['critic_available'] else 'off'}"
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="VibePrompt — Invisible Grill",
        description=(
            "Evidence-driven adversarial project reviewer. "
            "Challenges weak assumptions before you spend coding-agent tokens."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")
    return app


app = create_app()
