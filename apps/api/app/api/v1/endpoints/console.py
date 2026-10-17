"""Officer-console read models: caller identity, dashboard summary and recent activity.

These endpoints exist so the console never has to download whole collections to compute a number.
Each section is computed only when the caller holds the section's permission, inside a tenant
session limited to the jurisdictions where they hold *that* permission (row-level security), so a
count never includes rows the caller could not list. Nothing here reads the security audit log:
activity is drawn from the append-only workflow history tables and exposes no request metadata.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.api.deps import CurrentUserDep, _request_id, get_access_store
from app.api.ratelimit import client_ip, limit_user
from app.core.authz import AccessContext, AccessStore
from app.core.exceptions import ServiceUnavailableError
from app.db.rls import tenant_session
from app.services.compliance_workflow import Actor, ComplianceService

router = APIRouter(tags=["console"], dependencies=[Depends(limit_user("api_user"))])

# Permissions the console adapts its navigation and controls to. Informational for the UI only;
# every route still enforces its own permission on the server.
CONSOLE_PERMISSIONS: tuple[str, ...] = (
    "parcel:read",
    "property:read",
    "permit:read",
    "candidate:read",
    "finding:verify",
    "case:read",
    "case:create",
    "case:assign",
    "case:update",
    "case:resolve",
    "case:issue_notice",
)


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class JurisdictionOut(_Out):
    id: uuid.UUID
    code: str
    name: str
    level: str


class MeOut(_Out):
    user_id: uuid.UUID
    status: str
    permissions: dict[str, list[uuid.UUID]]
    jurisdictions: list[JurisdictionOut]


class ActivityItem(_Out):
    kind: str
    occurred_at: datetime
    actor_id: uuid.UUID | None
    entity_type: str
    entity_id: uuid.UUID
    jurisdiction_id: uuid.UUID
    summary: str


class ActivityOut(_Out):
    items: list[ActivityItem]
    sources: list[str]


def _sessions(request_state: Any) -> Any:
    sessions = getattr(request_state, "sessions", None)
    if sessions is None:
        raise ServiceUnavailableError("The database is not available.", code="database_unavailable")
    return sessions


async def _grants(
    store: AccessStore, user_id: uuid.UUID, permissions: tuple[str, ...]
) -> dict[str, frozenset[uuid.UUID]]:
    now = datetime.now(UTC)
    return {
        p: await store.permitted_jurisdictions(user_id=user_id, permission=p, at=now)
        for p in permissions
    }


@router.get("/me", response_model=MeOut, summary="The caller and where they hold each permission")
async def me(
    request: Request,
    user: CurrentUserDep,
    store: Annotated[AccessStore, Depends(get_access_store)],
) -> Any:
    grants = await _grants(store, user.id, CONSOLE_PERMISSIONS)
    ids = sorted({j for v in grants.values() for j in v}, key=str)
    jurisdictions: list[dict[str, Any]] = []
    if ids:
        sessions = _sessions(request.app.state)
        async with tenant_session(sessions, user_id=user.id, jurisdiction_ids=ids) as session:
            rows = await session.execute(
                text("SELECT id, code, name, level FROM jurisdiction WHERE id = ANY(:ids)"),
                {"ids": ids},
            )
            jurisdictions = [dict(r._mapping) for r in rows]
    return {
        "user_id": user.id,
        "status": user.status,
        "permissions": {p: sorted(v, key=str) for p, v in grants.items() if v},
        "jurisdictions": jurisdictions,
    }


def _service(request: Request) -> ComplianceService:
    return ComplianceService(
        getattr(request.app.state, "sessions", None),
        getattr(request.app.state, "audit", None),
        getattr(request.app.state, "access", None),
    )


def _actor(request: Request, user: CurrentUserDep) -> Actor:
    return Actor(user_id=user.id, ip=client_ip(request), request_id=_request_id())


async def _sections(
    request: Request, user: CurrentUserDep, store: AccessStore, permissions: tuple[str, ...]
) -> tuple[ComplianceService, Actor, dict[str, AccessContext]]:
    grants = await _grants(store, user.id, permissions)
    contexts = {p: AccessContext(user.id, p, g) for p, g in grants.items() if g}
    if not contexts:
        raise AccessContext(user.id, permissions[0], frozenset()).denial()
    return _service(request), _actor(request, user), contexts


@router.get("/dashboard/summary", summary="Counts for the officer dashboard (server-side)")
async def dashboard_summary(
    request: Request,
    user: CurrentUserDep,
    store: Annotated[AccessStore, Depends(get_access_store)],
) -> dict[str, Any]:
    """Aggregates per section; a section is ``null`` when the caller lacks its permission.

    SLA data does not exist yet (FR-10.4), so overdue counts are reported as unavailable rather
    than as zero.
    """
    service, actor, contexts = await _sections(
        request, user, store, ("candidate:read", "case:read")
    )
    result: dict[str, Any] = {
        "candidates": None,
        "cases": None,
        "sla": {"available": False, "reason": "SLA clocks (FR-10.4) are not implemented"},
        "generated_at": datetime.now(UTC),
    }
    if (ctx := contexts.get("candidate:read")) is not None:
        result["candidates"] = await service.read(ctx, actor, lambda s: s.candidate_dashboard())
    if (ctx := contexts.get("case:read")) is not None:
        result["cases"] = await service.read(ctx, actor, lambda s: s.case_dashboard())
    return result


@router.get("/activity", response_model=ActivityOut, summary="Recent workflow history")
async def recent_activity(
    request: Request,
    user: CurrentUserDep,
    store: Annotated[AccessStore, Depends(get_access_store)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> Any:
    """Newest-first history rows from the sections the caller may read (no audit metadata)."""
    service, actor, contexts = await _sections(
        request, user, store, ("candidate:read", "case:read", "permit:read", "parcel:read")
    )
    readers = {
        "candidate:read": lambda s: s.recent_candidate_activity(limit),
        "case:read": lambda s: s.recent_case_activity(limit),
        "permit:read": lambda s: s.recent_permit_activity(limit),
        "parcel:read": lambda s: s.recent_parcel_activity(limit),
    }
    rows: list[dict[str, Any]] = []
    for permission, ctx in contexts.items():
        rows.extend(await service.read(ctx, actor, readers[permission]))
    rows.sort(key=lambda r: r["occurred_at"], reverse=True)
    return {"items": rows[:limit], "sources": sorted(contexts)}
