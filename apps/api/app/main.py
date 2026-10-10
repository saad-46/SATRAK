"""Application entrypoint and factory.

``create_app`` assembles the FastAPI application: configuration, structured
logging, middleware, exception handlers, routers, and OpenAPI customization. The
factory pattern keeps construction explicit and testable (tests build their own
app instance rather than importing a module-level singleton with side effects).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints.earth_observation.composition import build_earth_observation_api
from app.api.v1.router import api_router
from app.core.auth import AuthRuntime, build_auth_runtime
from app.core.authz import AccessStore
from app.core.config import Settings, get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.openapi import build_custom_openapi
from app.db.access_store import SqlAccessStore
from app.db.session import dispose_engine, get_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks."""
    logger = get_logger("api.lifecycle")
    logger.info("api_startup", environment=str(app.state.settings.environment))
    if not app.state.settings.auth.enabled:
        logger.warning("authentication_disabled", environment=str(app.state.settings.environment))
    yield
    if app.state.auth is not None:
        await app.state.auth.aclose()
    await dispose_engine()
    logger.info("api_shutdown")


def _default_access_store(settings: Settings) -> AccessStore | None:
    """PostgreSQL-backed store, or ``None`` (fail closed) when no database is configured."""
    if settings.database_url is None:
        return None
    return SqlAccessStore(get_sessionmaker)


def create_app(
    settings: Settings | None = None,
    *,
    auth: AuthRuntime | None = None,
    access: AccessStore | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    # ``auth`` is injectable so tests supply a runtime backed by a fake key set.
    app.state.auth = auth if auth is not None else build_auth_runtime(settings.auth)
    # Authorization state (roles, assignments, jurisdictions). Defaults to PostgreSQL;
    # tests inject an in-memory store with identical semantics.
    app.state.access = access if access is not None else _default_access_store(settings)
    # Earth Observation API dependencies (in-memory backend today; swapped for the
    # SQLAlchemy/PostGIS adapter without endpoint changes when persistence lands).
    app.state.earth_observation = build_earth_observation_api()

    # --- Middleware (order matters: context binding is outermost) ------------
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Errors --------------------------------------------------------------
    register_exception_handlers(app)

    # --- Routes --------------------------------------------------------------
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", tags=["meta"], summary="Service root")
    async def root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "version": settings.version,
            "docs": "/docs" if settings.docs_enabled else "disabled",
        }

    # --- OpenAPI -------------------------------------------------------------
    app.openapi = build_custom_openapi(app, settings)  # type: ignore[method-assign]

    return app
