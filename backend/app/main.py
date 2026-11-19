"""VibePrompt Invisible Grill — FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.knowledge_routes import router as knowledge_router
from app.api.routes import router
from app.config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        return response


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
    demo = "DEMO (offline heuristic only) | " if settings.demo_mode else ""
    print(
        "VibePrompt ready | "
        f"{demo}"
        f"env={settings.app_env} | "
        f"chain={order or 'none'} | "
        f"external={'yes' if status['primary_available'] else 'offline-heuristic'} | "
        f"critic={'yes' if status['critic_available'] else 'off'} | "
        "knowledge-library=on"
    )
    if settings.demo_mode:
        print(
            "NOTE: DEMO_MODE=true — not live adversarial LLM Grill. "
            "Unset DEMO_MODE and configure provider keys for production-quality review."
        )
    yield


def create_app(settings=None) -> FastAPI:
    settings = settings or get_settings()
    docs_kwargs: dict = {}
    if settings.is_production:
        docs_kwargs = {
            "docs_url": None,
            "redoc_url": None,
            "openapi_url": None,
        }
    app = FastAPI(
        title="VibePrompt — Invisible Grill",
        description=(
            "Evidence-driven adversarial project reviewer. "
            "Challenges weak assumptions before you spend coding-agent tokens."
        ),
        version="1.0.0",
        lifespan=lifespan,
        **docs_kwargs,
    )
    origins = settings.cors_origin_list or ["http://localhost:5173"]
    if settings.is_production and any(o.strip() == "*" for o in origins):
        raise RuntimeError("CORS_ORIGINS must not be '*' in production")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Secret"],
    )
    app.add_middleware(SecurityHeadersMiddleware)

    if settings.is_production:
        # HTTPException / RequestValidationError keep FastAPI's dedicated handlers.
        @app.exception_handler(Exception)
        async def _production_unhandled(
            _request: Request, _exc: Exception
        ) -> JSONResponse:
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )

    app.include_router(router, prefix="/api")
    app.include_router(knowledge_router, prefix="/api")
    return app


app = create_app()
