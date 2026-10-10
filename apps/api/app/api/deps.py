"""Shared FastAPI dependencies (dependency-injection surface).

Endpoints depend on these callables rather than importing infrastructure
directly, so wiring stays centralized and is trivial to override in tests.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, cast

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ratelimit import client_ip, gate_source_ip, note_auth_failure
from app.core.auth import AuthRuntime, InvalidTokenError, JwksUnavailableError, Principal
from app.core.authz import AccessContext, AccessStore, AccessUser
from app.core.config import Settings
from app.core.exceptions import ForbiddenError, ServiceUnavailableError, UnauthorizedError
from app.core.security_audit import (
    USER_LOGGED_IN,
    USER_LOGIN_FAILED,
    SecurityAuditLog,
    SecurityEvent,
)
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


async def _verify_bearer_token(request: Request) -> Principal:
    """Validate the request's ``Authorization: Bearer`` access token (signature and claims).

    Fails closed: a missing, malformed, expired, mis-scoped or otherwise invalid token is
    a 401; inability to obtain signing keys is a 503, never an allow. Failure reasons are
    logged as codes only and never echoed to the caller; tokens are never logged.
    """
    await gate_source_ip(request)
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
        await note_auth_failure(request)
        raise UnauthorizedError(
            "The access token is invalid.",
            code="invalid_token",
            headers=_bearer_challenge(invalid=True),
        )
    try:
        principal = await runtime.verifier.verify(parts[1])
    except InvalidTokenError as exc:
        logger.info("auth_rejected", reason=exc.reason)
        await note_auth_failure(request)
        await best_effort_security_event(
            request,
            SecurityEvent(
                event_type=USER_LOGIN_FAILED,
                outcome="failure",
                ip=client_ip(request),
                request_id=_request_id(),
                details={"reason": exc.reason},
            ),
        )
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


async def get_current_principal(request: Request) -> Principal:
    """Authenticate the request: a valid token **and** current, non-revoked server-side state.

    Every authenticated route runs this (the router applies it by default), so revocation,
    disabled accounts and session tracking cannot be skipped by a route that needs no
    permission. The resolved local user is cached on ``request.state.user``.
    """
    principal = await _verify_bearer_token(request)
    if not request.app.state.settings.auth.enabled:
        return principal  # explicit dev mode: no identities, no sessions
    request.state.user = await _resolve_user(request, principal, get_access_store(request))
    return principal


PrincipalDep = Annotated[Principal, Depends(get_current_principal)]


def get_security_audit(request: Request) -> SecurityAuditLog:
    log = getattr(request.app.state, "audit", None)
    if log is None:
        # Fail closed: security decisions that must be recorded cannot proceed unrecorded.
        raise ServiceUnavailableError("Auditing is not available.", code="audit_unavailable")
    return cast(SecurityAuditLog, log)


SecurityAuditDep = Annotated[SecurityAuditLog, Depends(get_security_audit)]


def _request_id() -> str | None:
    return cast("str | None", structlog.contextvars.get_contextvars().get("request_id"))


async def record_security_event(log: SecurityAuditLog, event: SecurityEvent) -> None:
    """Append ``event``; any failure surfaces as 503 (the caller must not proceed)."""
    try:
        await log.record(event)
    except Exception as exc:
        logger.error("audit_write_failed", event_type=event.event_type, error=type(exc).__name__)
        raise ServiceUnavailableError(
            "Auditing is temporarily unavailable.", code="audit_unavailable"
        ) from exc


async def best_effort_security_event(request: Request, event: SecurityEvent) -> None:
    """Record a *denial*: the request is refused regardless, so an audit outage is logged loudly
    (and visible to operators) but cannot turn a refusal into an allow."""
    log = getattr(request.app.state, "audit", None)
    try:
        if log is None:
            raise RuntimeError("no audit log configured")
        await log.record(event)
    except Exception as exc:
        logger.error("audit_write_failed", event_type=event.event_type, error=type(exc).__name__)


def get_access_store(request: Request) -> AccessStore:
    store = getattr(request.app.state, "access", None)
    if store is None:
        # Fail closed: without an authorization store nothing can be allowed.
        raise ServiceUnavailableError("Authorization is not available.", code="authz_unavailable")
    return cast(AccessStore, store)


AccessStoreDep = Annotated[AccessStore, Depends(get_access_store)]


async def _resolve_user(request: Request, principal: Principal, store: AccessStore) -> AccessUser:
    """Resolve the token's identity to a local user and apply revocation state.

    Revocation is evaluated against the authoritative store on **every** request (ADR-0013 E),
    so a revoked user/session is rejected on its very next request on any instance.
    """
    try:
        user = await store.get_or_create_user(issuer=principal.issuer, subject=principal.subject)
    except Exception as exc:  # fail closed on any store failure
        logger.error("authz_user_lookup_failed", error=type(exc).__name__)
        raise ServiceUnavailableError(
            "Authorization is temporarily unavailable.", code="authz_unavailable"
        ) from exc
    if user.is_disabled:
        raise ForbiddenError("The account is disabled.", code="account_disabled")
    if user.revoked_before is not None and principal.issued_at <= user.revoked_before:
        await _reject_revoked(request, user, "user_revoked")
    session_key = principal.session_key
    if session_key is not None:
        await _check_session(request, principal, user, store, session_key)
    return user


async def _reject_revoked(request: Request, user: AccessUser, reason: str) -> None:
    logger.info("auth_rejected", reason=reason)
    await note_auth_failure(request)
    await best_effort_security_event(
        request,
        SecurityEvent(
            event_type=USER_LOGIN_FAILED,
            outcome="failure",
            actor_user_id=user.id,
            ip=client_ip(request),
            request_id=_request_id(),
            details={"reason": reason},
        ),
    )
    raise UnauthorizedError(
        "The access token is invalid.",
        code="invalid_token",
        headers=_bearer_challenge(invalid=True),
    )


async def _check_session(
    request: Request,
    principal: Principal,
    user: AccessUser,
    store: AccessStore,
    session_key: str,
) -> None:
    async def audit_first_use() -> None:
        await record_security_event(
            get_security_audit(request),
            SecurityEvent(
                event_type=USER_LOGGED_IN,
                outcome="success",
                actor_user_id=user.id,
                ip=client_ip(request),
                request_id=_request_id(),
            ),
        )

    try:
        state = await store.register_session(
            user_id=user.id,
            issuer=principal.issuer,
            session_key=session_key,
            expires_at=principal.expires_at,
            at=datetime.now(UTC),
            on_first_seen=audit_first_use,
        )
    except ServiceUnavailableError:
        raise
    except Exception as exc:  # fail closed
        logger.error("authz_session_check_failed", error=type(exc).__name__)
        raise ServiceUnavailableError(
            "Authorization is temporarily unavailable.", code="authz_unavailable"
        ) from exc
    if state.revoked:
        await _reject_revoked(request, user, "session_revoked")


async def get_current_user(request: Request, _principal: PrincipalDep) -> AccessUser:
    """The local user behind the (already authenticated and revocation-checked) principal."""
    user = getattr(request.state, "user", None)
    if user is None:  # authentication is disabled (dev only): no identity to resolve
        raise ForbiddenError("No identity is available.", code="no_identity")
    return cast(AccessUser, user)


CurrentUserDep = Annotated[AccessUser, Depends(get_current_user)]


def require_permission(permission: str) -> Callable[..., Awaitable[AccessContext]]:
    """Dependency factory: authenticate, then require ``permission`` somewhere.

    Returns the :class:`AccessContext` listing the jurisdictions in which it holds. A caller
    with the permission nowhere is rejected here (403); endpoints then restrict lists to the
    context and check object access with ``ctx.require(jurisdiction_id)``.
    """

    async def dependency(
        request: Request, user: CurrentUserDep, store: AccessStoreDep
    ) -> AccessContext:
        try:
            jurisdictions = await store.permitted_jurisdictions(
                user_id=user.id, permission=permission, at=datetime.now(UTC)
            )
        except Exception as exc:  # fail closed
            logger.error("authz_check_failed", permission=permission, error=type(exc).__name__)
            raise ServiceUnavailableError(
                "Authorization is temporarily unavailable.", code="authz_unavailable"
            ) from exc
        context = AccessContext(user.id, permission, jurisdictions)
        if not jurisdictions:
            logger.info("access_denied", permission=permission, reason="no_grant")
            denial = context.denial()
            denial.security_event = SecurityEvent(
                event_type=denial.security_event.event_type,
                outcome="denied",
                actor_user_id=user.id,
                permission=permission,
                ip=client_ip(request),
                request_id=_request_id(),
                details={"reason": "no_grant"},
            )
            raise denial
        return context

    return dependency
