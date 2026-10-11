"""Application entrypoint and factory.

``create_app`` assembles the FastAPI application: configuration, structured
logging, middleware, exception handlers, routers, and OpenAPI customization. The
factory pattern keeps construction explicit and testable (tests build their own
app instance rather than importing a module-level singleton with side effects).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import BlockingConnectionPool, Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.endpoints.earth_observation.composition import build_earth_observation_api
from app.api.v1.router import api_router
from app.core.auth import AuthRuntime, build_auth_runtime
from app.core.authz import AccessStore
from app.core.config import Environment, Settings, get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.openapi import build_custom_openapi
from app.core.proxy_trust import verify_forwarded_allow_ips
from app.core.ratelimit import InMemoryRateLimiter, RateLimiter, RedisRateLimiter
from app.core.security_audit import SecurityAuditLog
from app.core.security_middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from app.db.access_store import SqlAccessStore
from app.db.role_check import UnsafeDatabaseRoleError, inspect_application_role
from app.db.security_audit_store import SqlSecurityAuditLog
from app.db.session import dispose_engine, get_engine, get_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks."""
    logger = get_logger("api.lifecycle")
    logger.info("api_startup", environment=str(app.state.settings.environment))
    if not app.state.settings.auth.enabled:
        logger.warning("authentication_disabled", environment=str(app.state.settings.environment))
    try:
        settings = app.state.settings
        production_like = settings.environment in (Environment.STAGING, Environment.PRODUCTION)
        verify_forwarded_allow_ips(os.environ, enforce=production_like)
        await _verify_database_role(app, logger)
        if settings.network_topology == "direct" and production_like:
            # An exception to the intended topology, allowed only with a recorded reference.
            logger.warning(
                "direct_exposure_acknowledged",
                reference=settings.direct_exposure_acknowledgement,
                hint="client addresses are TCP peers; X-Forwarded-For is never believed",
            )
        yield
    finally:  # also runs when startup validation refuses to serve
        if app.state.auth is not None:
            await app.state.auth.aclose()
        if app.state.redis_client is not None:
            await app.state.redis_client.aclose()
        await dispose_engine()
        logger.info("api_shutdown")


async def _verify_database_role(app: FastAPI, logger: Any) -> None:
    """Refuse to start on a database role that would bypass row-level security."""
    settings: Settings = app.state.settings
    if settings.database_url is None or app.state.access is None:
        return  # no database: every authorization path already fails closed
    strict = settings.database_role_check == "enforce"
    production_like = settings.environment in (Environment.STAGING, Environment.PRODUCTION)
    try:
        report = await inspect_application_role(get_engine())
    except Exception as exc:
        if production_like:  # cannot prove the role is safe: do not serve traffic
            raise UnsafeDatabaseRoleError("could not verify the database role") from exc
        logger.warning("database_role_unverified", cause=str(exc))
        return
    if report.safe:
        logger.info("database_role_verified", role=report.role)
    elif strict:
        raise UnsafeDatabaseRoleError(
            f"unsafe database role {report.role!r}: " + "; ".join(report.problems)
        )
    else:
        logger.warning("database_role_unsafe", role=report.role, problems=list(report.problems))


def _default_access_store(settings: Settings) -> AccessStore | None:
    """PostgreSQL-backed store, or ``None`` (fail closed) when no database is configured."""
    if settings.database_url is None:
        return None
    return SqlAccessStore(get_sessionmaker)


def _default_security_audit(settings: Settings) -> SecurityAuditLog | None:
    if settings.database_url is None:
        return None
    return SqlSecurityAuditLog(get_sessionmaker)


def _default_rate_limiter(settings: Settings) -> tuple[RateLimiter | None, Redis | None]:
    if not settings.rate_limit.enabled:
        return None, None
    if settings.redis_url is None:
        # Single-process limiter: acceptable for local development only (staging/production
        # settings validation requires Redis, since per-process state is not enough).
        get_logger("api.lifecycle").warning("rate_limiter_process_local")
        return InMemoryRateLimiter(), None
    pool = BlockingConnectionPool.from_url(
        str(settings.redis_url),
        max_connections=settings.rate_limit.redis_max_connections,
        timeout=1.0,  # wait briefly for a free connection instead of failing at the cap
        socket_timeout=1.0,
        socket_connect_timeout=1.0,
        decode_responses=False,
    )
    client = Redis.from_pool(pool)
    return RedisRateLimiter(client), client


def create_app(
    settings: Settings | None = None,
    *,
    auth: AuthRuntime | None = None,
    access: AccessStore | None = None,
    audit: SecurityAuditLog | None = None,
    rate_limiter: RateLimiter | None = None,
    sessions: Callable[[], async_sessionmaker[AsyncSession]] | None = None,
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
    # Session factory for the compliance workflow (tenant-scoped transactions). ``None`` without
    # a database, in which case those routes answer 503 instead of guessing.
    app.state.sessions = (
        sessions
        if sessions is not None
        else (get_sessionmaker if settings.database_url is not None else None)
    )
    # Durable security audit log (append-only, hash-chained). ``None`` fails closed.
    app.state.audit = audit if audit is not None else _default_security_audit(settings)
    # Shared rate-limit state (Redis) with a strict process-local fallback for outages.
    default_limiter, redis_client = (
        (None, None) if rate_limiter is not None else _default_rate_limiter(settings)
    )
    app.state.rate_limiter = rate_limiter if rate_limiter is not None else default_limiter
    app.state.rate_fallback = InMemoryRateLimiter()
    app.state.redis_client = redis_client
    # Earth Observation API dependencies (in-memory backend today; swapped for the
    # SQLAlchemy/PostGIS adapter without endpoint changes when persistence lands).
    app.state.earth_observation = build_earth_observation_api()

    # --- Middleware (added last = outermost; request context is outermost of all) ----
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,  # explicit origins only ("*" is rejected at startup)
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "If-None-Match", "X-Request-ID"],
        expose_headers=["Retry-After", "X-Request-ID", "ETag"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(RequestContextMiddleware)

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
