"""Session revocation: self logout and administrator-initiated revocation (ADR-0013 E).

Revocations take effect on the target's very next request, on every instance, because the
authoritative state is read from the shared store per request. Every revocation is audited
(``session.revoked``). Administrative revocation requires ``session:revoke`` in a
jurisdiction where the target user holds an assignment; targets with no assignment cannot
be revoked this way (default deny) and must be revoked at the identity provider.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import (
    AccessStoreDep,
    CurrentUserDep,
    PrincipalDep,
    SecurityAuditDep,
    _request_id,
    record_security_event,
    require_permission,
)
from app.api.ratelimit import client_ip, limit_ip, limit_user
from app.core.authz import AccessContext
from app.core.exceptions import ServiceUnavailableError
from app.core.security_audit import SESSION_REVOKED, SecurityEvent

# Sensitive auth entry point: tight per-IP budget that fails closed if the limiter is down.
logout_router = APIRouter(
    tags=["auth"],
    dependencies=[
        Depends(limit_ip("auth_entry_ip", critical=True)),
        Depends(limit_user("api_user")),
    ],
)
admin_router = APIRouter(tags=["admin: sessions"], dependencies=[Depends(limit_user("admin_user"))])

REVOKE_PERMISSION = "session:revoke"
_ADMIN_REVOKE_TTL = timedelta(hours=1)  # ample: access tokens live 15 minutes (ADR-0013)


class RevokeUserRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


class RevokeSessionRequest(BaseModel):
    user_id: uuid.UUID
    session_key: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=3, max_length=200)


async def _audit_revocation(
    request: Request,
    log: SecurityAuditDep,
    *,
    actor: uuid.UUID,
    target: uuid.UUID,
    scope: str,
    reason: str,
) -> None:
    await record_security_event(
        log,
        SecurityEvent(
            event_type=SESSION_REVOKED,
            outcome="success",
            actor_user_id=actor,
            ip=client_ip(request),
            request_id=_request_id(),
            details={"target_user": str(target), "scope": scope, "reason": reason},
        ),
    )


@logout_router.post(
    "/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke the caller's session"
)
async def logout(
    request: Request,
    principal: PrincipalDep,
    user: CurrentUserDep,
    store: AccessStoreDep,
    log: SecurityAuditDep,
) -> Response:
    """Revoke the presented session, or every token issued so far when it has no session id."""
    now = datetime.now(UTC)
    try:
        if principal.session_key is not None:
            await store.revoke_session(
                user_id=user.id,
                issuer=principal.issuer,
                session_key=principal.session_key,
                expires_at=principal.expires_at,
                revoked_by=user.id,
                reason="logout",
                at=now,
            )
            scope = "session"
        else:
            await store.revoke_user_sessions(
                user_id=user.id, at=now, revoked_by=user.id, reason="logout"
            )
            scope = "user"
    except Exception as exc:
        raise ServiceUnavailableError(
            "Revocation is temporarily unavailable.", code="authz_unavailable"
        ) from exc
    await _audit_revocation(
        request, log, actor=user.id, target=user.id, scope=scope, reason="logout"
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _require_scope(ctx: AccessContext, store: AccessStoreDep, target: uuid.UUID) -> None:
    """The caller's permission must cover a jurisdiction the target is assigned to."""
    try:
        theirs = await store.assignment_jurisdictions(user_id=target)
    except Exception as exc:
        raise ServiceUnavailableError(
            "Authorization is temporarily unavailable.", code="authz_unavailable"
        ) from exc
    if not (theirs & ctx.jurisdictions):
        raise ctx.denial()


@admin_router.post(
    "/admin/users/{user_id}/revoke-sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke all of a user's tokens issued so far",
)
async def revoke_user_sessions(
    user_id: uuid.UUID,
    body: RevokeUserRequest,
    request: Request,
    actor: CurrentUserDep,
    store: AccessStoreDep,
    log: SecurityAuditDep,
    ctx: AccessContext = Depends(require_permission(REVOKE_PERMISSION)),
) -> Response:
    await _require_scope(ctx, store, user_id)
    try:
        await store.revoke_user_sessions(
            user_id=user_id, at=datetime.now(UTC), revoked_by=actor.id, reason=body.reason
        )
    except Exception as exc:
        raise ServiceUnavailableError(
            "Revocation is temporarily unavailable.", code="authz_unavailable"
        ) from exc
    await _audit_revocation(
        request, log, actor=actor.id, target=user_id, scope="user", reason=body.reason
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post(
    "/admin/sessions/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke one session",
)
async def revoke_session(
    body: RevokeSessionRequest,
    request: Request,
    actor: CurrentUserDep,
    principal: PrincipalDep,
    store: AccessStoreDep,
    log: SecurityAuditDep,
    ctx: AccessContext = Depends(require_permission(REVOKE_PERMISSION)),
) -> Response:
    await _require_scope(ctx, store, body.user_id)
    now = datetime.now(UTC)
    try:
        await store.revoke_session(
            user_id=body.user_id,
            issuer=principal.issuer,
            session_key=body.session_key,
            expires_at=now + _ADMIN_REVOKE_TTL,
            revoked_by=actor.id,
            reason=body.reason,
            at=now,
        )
    except Exception as exc:
        raise ServiceUnavailableError(
            "Revocation is temporarily unavailable.", code="authz_unavailable"
        ) from exc
    await _audit_revocation(
        request, log, actor=actor.id, target=body.user_id, scope="session", reason=body.reason
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
