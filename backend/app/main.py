"""VibePrompt Invisible Grill — FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.knowledge_routes import router as knowledge_router
from app.api.routes import router
from app.config import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    # Refuse insecure production configuration before serving traffic
    settings.assert_secure_for_runtime()
    # Touch repository / knowledge store so DB + builtin skills exist at startup
    from app.api.deps import get_knowledge_store, get_repository, get_skill_registry

    get_repository()
    get_knowledge_store()
    get_skill_registry()
    status = settings.provider_status()
    order = ",".join(status.get("provider_order") or [])  # type: ignore[arg-type]
    print(
        "VibePrompt ready | "
        f"env={settings.app_env} | "
        f"chain={order or 'none'} | "
        f"external={'yes' if status['primary_available'] else 'offline-heuristic'} | "
        f"critic={'yes' if status['critic_available'] else 'off'} | "
        "knowledge-library=on"
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
    app.include_router(knowledge_router, prefix="/api")
    return app


app = create_app()
