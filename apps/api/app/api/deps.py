"""Shared FastAPI dependencies (dependency-injection surface).

Endpoints depend on these callables rather than importing infrastructure
directly, so wiring stays centralized and is trivial to override in tests.
"""

from __future__ import annotations

from typing import Annotated, cast

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthRuntime, InvalidTokenError, JwksUnavailableError, Principal
from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError, UnauthorizedError
from app.db.session import get_db

logger = structlog.get_logger("api.auth")


def get_app_settings(request: Request) -> Settings:
    """Return the settings the running app was constructed with.

    Reads from ``app.state`` rather than the module-level ``get_settings()`` cache
    so a test (or an embedding process) that builds the app with custom settings
    gets those exact settings in every endpoint.
    """
    return cast(Settings, request.app.state.settings)


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]


def _bearer_challenge(*, invalid: bool) -> dict[str, str]:
    # RFC 6750 §3: no error attribute when the request simply lacked credentials.
    value = 'Bearer error="invalid_token"' if invalid else "Bearer"
    return {"WWW-Authenticate": value}


async def get_current_principal(request: Request) -> Principal:
    """Authenticate the request from its ``Authorization: Bearer`` access token.

    Fails closed: a missing, malformed, expired, mis-scoped or otherwise invalid token is
    a 401; inability to obtain signing keys is a 503, never an allow. Failure reasons are
    logged as codes only and never echoed to the caller; tokens are never logged.
    """
    settings = cast(Settings, request.app.state.settings)
    runtime = cast(AuthRuntime | None, getattr(request.app.state, "auth", None))
    if not settings.auth.enabled:
        principal = Principal.dev_authentication_disabled()
        request.state.principal = principal
        return principal
    if runtime is None:  # defence in depth: enabled but not wired
        raise ServiceUnavailableError("Authentication is not available.", code="auth_unavailable")

    values = request.headers.getlist("authorization")
    if not values:
        raise UnauthorizedError(
            "Authentication is required.",
            code="authentication_required",
            headers=_bearer_challenge(invalid=False),
        )
    parts = values[0].split(" ") if len(values) == 1 else []
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        logger.info("auth_rejected", reason="bad_authorization_header")
        raise UnauthorizedError(
            "The access token is invalid.",
            code="invalid_token",
            headers=_bearer_challenge(invalid=True),
        )
    try:
        principal = await runtime.verifier.verify(parts[1])
    except InvalidTokenError as exc:
        logger.info("auth_rejected", reason=exc.reason)
        raise UnauthorizedError(
            "The access token is invalid.",
            code="invalid_token",
            headers=_bearer_challenge(invalid=True),
        ) from exc
    except JwksUnavailableError as exc:
        logger.error("auth_keys_unavailable")
        raise ServiceUnavailableError(
            "Authentication is temporarily unavailable.", code="auth_unavailable"
        ) from exc
    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(get_current_principal)]
