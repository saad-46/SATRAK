"""Construction-compliance workflow API (parcels → permits → candidates → verification → cases).

Authorization is server-side and jurisdiction-scoped on every route: ``require_permission`` yields
the jurisdictions in which the caller holds the route's permission, the service restricts the
database transaction to them (row-level security), and objects in other jurisdictions are
invisible (404, indistinguishable from a missing id). Writes name their jurisdiction explicitly
and are refused (403, audited) outside the caller's scope.

AI output is registered as a *candidate*. It cannot become a case, notice or enforcement action
until an officer confirms it with ``finding:verify`` (ADR-0014); ``POST /cases`` re-checks this on
the server and the database enforces it again with a trigger.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUserDep, _request_id, get_access_store, require_permission
from app.api.pagination import PageParamsDep
from app.api.ratelimit import client_ip, limit_user
from app.api.schemas import PageResponse
from app.contexts.inspection.domain.case import CaseStatus
from app.core.authz import AccessContext, AccessStore
from app.services.compliance_workflow import (
    TRANSITION_PERMISSION,
    Actor,
    ComplianceService,
)
from app.shared.pagination import Page

router = APIRouter(dependencies=[Depends(limit_user("api_user"))])

Geometry = Annotated[dict[str, Any], Field(description="GeoJSON geometry, EPSG:4326 lon/lat")]
Version = Annotated[int, Field(ge=1, description="The version last read (optimistic concurrency)")]


# --------------------------------------------------------------------- dependencies
def get_compliance_service(request: Request) -> ComplianceService:
    return ComplianceService(
        getattr(request.app.state, "sessions", None),
        getattr(request.app.state, "audit", None),
        getattr(request.app.state, "access", None),
    )


ServiceDep = Annotated[ComplianceService, Depends(get_compliance_service)]


def _actor(request: Request, user: CurrentUserDep) -> Actor:
    return Actor(user_id=user.id, ip=client_ip(request), request_id=_request_id())


ActorDep = Annotated[Actor, Depends(_actor)]


def _need(permission: str) -> Any:
    return Depends(require_permission(permission))


# ------------------------------------------------------------------------- schemas
class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ParcelOut(_Out):
    id: uuid.UUID
    jurisdiction_id: uuid.UUID
    code: str
    current_version: int
    area_sq_m: float
    topology_status: Literal["clean", "overlaps_neighbour"]
    topology_detail: dict[str, Any]
    geometry: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class GeometryVersionOut(_Out):
    version: int
    area_sq_m: float
    topology_status: str
    topology_detail: dict[str, Any]
    reason: str | None
    recorded_by: uuid.UUID
    created_at: datetime
    geometry: dict[str, Any]


class ParcelCreate(BaseModel):
    jurisdiction_id: uuid.UUID
    code: str = Field(min_length=1, max_length=64)
    geometry: Geometry
    reason: str | None = Field(default=None, max_length=1000)


class GeometryVersionCreate(BaseModel):
    geometry: Geometry
    reason: str = Field(min_length=3, max_length=1000)
    expected_version: Version


class PropertyCreate(BaseModel):
    jurisdiction_id: uuid.UUID
    parcel_id: uuid.UUID
    property_ref: str = Field(min_length=1, max_length=64)
    land_use: str = Field(min_length=1, max_length=32)
    address_text: str | None = Field(default=None, max_length=500)


class PropertyOut(_Out):
    id: uuid.UUID
    jurisdiction_id: uuid.UUID
    parcel_id: uuid.UUID
    property_ref: str
    land_use: str
    address_text: str | None
    created_at: datetime


class PermitCreate(BaseModel):
    jurisdiction_id: uuid.UUID
    permit_number: str = Field(min_length=1, max_length=64)
    status: Literal["approved", "suspended", "revoked", "closed"] = "approved"
    valid_from: date
    valid_to: date | None = None
    sanctioned_floors: int = Field(ge=1, le=200)
    sanctioned_footprint_area_sq_m: float = Field(gt=0, le=1e9)
    sanctioned_built_up_area_sq_m: float | None = Field(default=None, gt=0, le=1e10)
    declared_plot_area_sq_m: float | None = Field(default=None, gt=0, le=1e10)
    declared_parcel_code: str = Field(min_length=1, max_length=64)
    source_system: str = Field(min_length=1, max_length=64)
    source_record_ref: str | None = Field(default=None, max_length=128)
    is_simulated: bool = Field(
        default=False, description="True for fixtures; never present simulated data as official"
    )


class PermitOut(_Out):
    id: uuid.UUID
    jurisdiction_id: uuid.UUID
    permit_number: str
    status: str
    valid_from: date
    valid_to: date | None
    sanctioned_floors: int
    sanctioned_footprint_area_sq_m: float
    sanctioned_built_up_area_sq_m: float | None
    declared_plot_area_sq_m: float | None
    declared_parcel_code: str
    parcel_id: uuid.UUID | None
    match_status: Literal["matched", "unmatched", "conflict"]
    match_detail: dict[str, Any]
    source_system: str
    source_record_ref: str | None
    is_simulated: bool
    version: int
    created_at: datetime
    updated_at: datetime


class PermitStatusChange(BaseModel):
    status: Literal["approved", "suspended", "revoked", "closed"]
    reason: str = Field(min_length=3, max_length=1000)
    expected_version: Version


class PermitMatchResolution(BaseModel):
    parcel_id: uuid.UUID
    reason: str = Field(min_length=10, max_length=1000)
    expected_version: Version


class ImageryRef(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    reference: str = Field(min_length=1, max_length=512)
    acquired_on: date


class CandidateCreate(BaseModel):
    jurisdiction_id: uuid.UUID
    source_type: Literal["ai_detection", "manual_report", "imported"]
    observed_on: date
    change_type: Literal["new_structure", "extension", "alteration"]
    footprint: Geometry
    estimated_floors: int | None = Field(default=None, ge=1, le=200)
    confidence: float | None = Field(default=None, ge=0, le=1)
    model_name: str | None = Field(default=None, max_length=128)
    model_version: str | None = Field(default=None, max_length=64)
    imagery_refs: list[ImageryRef] = Field(default_factory=list, max_length=20)
    provenance_note: str | None = Field(default=None, max_length=2000)
    is_simulated: bool = Field(
        default=False, description="True when the detection comes from a fixture, not a model"
    )


class CandidateOut(_Out):
    id: uuid.UUID
    jurisdiction_id: uuid.UUID
    source_type: str
    is_simulated: bool
    observed_on: date
    change_type: str
    footprint: dict[str, Any]
    footprint_area_sq_m: float
    estimated_floors: int | None
    confidence: float | None
    model_name: str | None
    model_version: str | None
    imagery_refs: list[dict[str, Any]]
    provenance_note: str | None
    parcel_id: uuid.UUID | None
    status: Literal["unverified", "needs_evidence", "confirmed", "rejected"]
    created_at: datetime


class EvaluationOut(_Out):
    id: uuid.UUID
    seq: int
    classification: str
    severity: str
    failed_rules: list[str]
    result: dict[str, Any]
    parcel_id: uuid.UUID | None
    evaluated_by: uuid.UUID
    created_at: datetime


class ReviewCreate(BaseModel):
    decision: Literal["confirm", "reject", "request_evidence"]
    justification: str = Field(min_length=1, max_length=4000)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class ReviewOut(_Out):
    seq: int
    decision: str
    resulting_status: str
    justification: str
    evidence_refs: list[dict[str, Any]]
    is_reversal: bool
    reviewer_id: uuid.UUID
    created_at: datetime


class CaseCreate(BaseModel):
    candidate_id: uuid.UUID


class CaseOut(_Out):
    id: uuid.UUID
    jurisdiction_id: uuid.UUID
    candidate_id: uuid.UUID
    evaluation_id: uuid.UUID
    parcel_id: uuid.UUID | None
    source_type: str
    severity: str
    priority_score: int
    status: str
    assigned_to: uuid.UUID | None
    opened_by: uuid.UUID
    version: int
    created_at: datetime
    updated_at: datetime


class CaseAssign(BaseModel):
    assignee_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=1000)
    expected_version: Version


class CaseTransition(BaseModel):
    target: Literal["assigned", "under_investigation", "notice_issued", "resolved", "dismissed"]
    reason: str | None = Field(default=None, max_length=1000)
    expected_version: Version


class EvidenceItem(BaseModel):
    kind: Literal["photo", "document", "drone_survey", "measurement_log"]
    reference: str = Field(min_length=1, max_length=512)
    sha256: str = Field(min_length=64, max_length=64)
    captured_at: datetime


class FindingCreate(BaseModel):
    notes: str = Field(min_length=1, max_length=4000)
    measurements: dict[str, float | int | str] = Field(default_factory=dict, max_length=20)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=20)


class FindingOut(_Out):
    seq: int
    author_id: uuid.UUID
    notes: str
    measurements: dict[str, Any]
    evidence: list[dict[str, Any]]
    created_at: datetime


class CaseHistoryOut(BaseModel):
    transitions: list[dict[str, Any]]
    assignments: list[dict[str, Any]]
    findings: list[FindingOut]


def _page(page: Page[Any], model: type[BaseModel]) -> PageResponse[Any]:
    items = tuple(model.model_validate(i) for i in page.items)
    return PageResponse[Any].from_page(
        Page(items=items, total=page.total, page=page.page, size=page.size)
    )


def _scoped(ctx: AccessContext, row: dict[str, Any]) -> dict[str, Any]:
    ctx.require(row["jurisdiction_id"])
    return row


# --------------------------------------------------------------------------- parcels
@router.post(
    "/parcels",
    response_model=ParcelOut,
    status_code=status.HTTP_201_CREATED,
    tags=["parcels"],
    summary="Register a parcel with its first geometry version",
)
async def create_parcel(
    body: ParcelCreate,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("parcel:write"),
) -> Any:
    return await service.create_parcel(
        ctx,
        actor,
        jurisdiction_id=body.jurisdiction_id,
        code=body.code,
        geometry=body.geometry,
        reason=body.reason,
    )


@router.get("/parcels", response_model=PageResponse[ParcelOut], tags=["parcels"])
async def list_parcels(
    params: PageParamsDep,
    service: ServiceDep,
    actor: ActorDep,
    topology_status: Literal["clean", "overlaps_neighbour"] | None = None,
    ctx: AccessContext = _need("parcel:read"),
) -> Any:
    request = params.to_page_request()
    page = await service.read(
        ctx, actor, lambda s: s.list_parcels(request, topology_status=topology_status)
    )
    return _page(page, ParcelOut)


@router.get("/parcels/{parcel_id}", response_model=ParcelOut, tags=["parcels"])
async def get_parcel(
    parcel_id: uuid.UUID,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("parcel:read"),
) -> Any:
    return _scoped(ctx, await service.read(ctx, actor, lambda s: s.get_parcel(parcel_id)))


@router.get(
    "/parcels/{parcel_id}/geometry-versions",
    response_model=list[GeometryVersionOut],
    tags=["parcels"],
)
async def parcel_geometry_history(
    parcel_id: uuid.UUID,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("parcel:read"),
) -> Any:
    return await service.read(ctx, actor, lambda s: s.parcel_history(parcel_id))


@router.post(
    "/parcels/{parcel_id}/geometry-versions",
    response_model=ParcelOut,
    status_code=status.HTTP_201_CREATED,
    tags=["parcels"],
    summary="Append a geometry version (earlier versions are kept)",
)
async def add_geometry_version(
    parcel_id: uuid.UUID,
    body: GeometryVersionCreate,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("parcel:write"),
) -> Any:
    return await service.add_parcel_geometry(
        ctx,
        actor,
        parcel_id,
        geometry=body.geometry,
        reason=body.reason,
        expected_version=body.expected_version,
    )


# ------------------------------------------------------------------------ properties
@router.post(
    "/properties",
    response_model=PropertyOut,
    status_code=status.HTTP_201_CREATED,
    tags=["properties"],
)
async def create_property(
    body: PropertyCreate,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("property:write"),
) -> Any:
    return await service.create_property(
        ctx,
        actor,
        jurisdiction_id=body.jurisdiction_id,
        parcel_id=body.parcel_id,
        property_ref=body.property_ref,
        land_use=body.land_use,
        address_text=body.address_text,
    )


@router.get("/properties", response_model=PageResponse[PropertyOut], tags=["properties"])
async def list_properties(
    params: PageParamsDep,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("property:read"),
) -> Any:
    request = params.to_page_request()
    return _page(await service.read(ctx, actor, lambda s: s.list_properties(request)), PropertyOut)


@router.get("/properties/{property_id}", response_model=PropertyOut, tags=["properties"])
async def get_property(
    property_id: uuid.UUID,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("property:read"),
) -> Any:
    return _scoped(ctx, await service.read(ctx, actor, lambda s: s.get_property(property_id)))


# --------------------------------------------------------------------------- permits
@router.post(
    "/permits",
    response_model=PermitOut,
    status_code=status.HTTP_201_CREATED,
    tags=["permits"],
    summary="Register a building permit and match it to a parcel",
)
async def create_permit(
    body: PermitCreate,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("permit:write"),
) -> Any:
    fields = body.model_dump()
    fields.pop("jurisdiction_id")
    return await service.create_permit(
        ctx, actor, jurisdiction_id=body.jurisdiction_id, fields=fields
    )


@router.get("/permits", response_model=PageResponse[PermitOut], tags=["permits"])
async def list_permits(
    params: PageParamsDep,
    service: ServiceDep,
    actor: ActorDep,
    match_status: Literal["matched", "unmatched", "conflict"] | None = None,
    permit_status: Annotated[
        Literal["approved", "suspended", "revoked", "closed"] | None, Query(alias="status")
    ] = None,
    ctx: AccessContext = _need("permit:read"),
) -> Any:
    request = params.to_page_request()
    page = await service.read(
        ctx,
        actor,
        lambda s: s.list_permits(request, match_status=match_status, status=permit_status),
    )
    return _page(page, PermitOut)


@router.get("/permits/{permit_id}", response_model=PermitOut, tags=["permits"])
async def get_permit(
    permit_id: uuid.UUID,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("permit:read"),
) -> Any:
    return _scoped(ctx, await service.read(ctx, actor, lambda s: s.get_permit(permit_id)))


@router.get("/permits/{permit_id}/history", response_model=list[dict[str, Any]], tags=["permits"])
async def permit_history(
    permit_id: uuid.UUID,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("permit:read"),
) -> Any:
    return await service.read(ctx, actor, lambda s: s.permit_history(permit_id))


@router.post("/permits/{permit_id}/status", response_model=PermitOut, tags=["permits"])
async def change_permit_status(
    permit_id: uuid.UUID,
    body: PermitStatusChange,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("permit:write"),
) -> Any:
    return await service.change_permit_status(
        ctx,
        actor,
        permit_id,
        target=body.status,
        reason=body.reason,
        expected_version=body.expected_version,
    )


@router.post(
    "/permits/{permit_id}/match",
    response_model=PermitOut,
    tags=["permits"],
    summary="Resolve an unmatched or conflicting permit to a parcel (officer decision)",
)
async def resolve_permit_match(
    permit_id: uuid.UUID,
    body: PermitMatchResolution,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("permit:write"),
) -> Any:
    return await service.resolve_permit_match(
        ctx,
        actor,
        permit_id,
        parcel_id=body.parcel_id,
        reason=body.reason,
        expected_version=body.expected_version,
    )


# ------------------------------------------------------------------------ candidates
@router.post(
    "/candidates",
    response_model=CandidateOut,
    status_code=status.HTTP_201_CREATED,
    tags=["candidates"],
    summary="Register a construction-change candidate (always starts unverified)",
)
async def register_candidate(
    body: CandidateCreate,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("candidate:create"),
) -> Any:
    fields = body.model_dump(mode="json")
    fields["observed_on"] = body.observed_on
    fields.pop("jurisdiction_id")
    return await service.register_candidate(
        ctx, actor, jurisdiction_id=body.jurisdiction_id, fields=fields
    )


@router.get("/candidates", response_model=PageResponse[CandidateOut], tags=["candidates"])
async def list_candidates(
    params: PageParamsDep,
    service: ServiceDep,
    actor: ActorDep,
    candidate_status: Annotated[
        Literal["unverified", "needs_evidence", "confirmed", "rejected"] | None,
        Query(alias="status"),
    ] = None,
    source_type: Literal["ai_detection", "manual_report", "imported"] | None = None,
    ctx: AccessContext = _need("candidate:read"),
) -> Any:
    request = params.to_page_request()
    page = await service.read(
        ctx,
        actor,
        lambda s: s.list_candidates(request, status=candidate_status, source_type=source_type),
    )
    return _page(page, CandidateOut)


@router.get("/candidates/{candidate_id}", response_model=CandidateOut, tags=["candidates"])
async def get_candidate(
    candidate_id: uuid.UUID,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("candidate:read"),
) -> Any:
    return _scoped(ctx, await service.read(ctx, actor, lambda s: s.get_candidate(candidate_id)))


@router.post(
    "/candidates/{candidate_id}/evaluations",
    response_model=EvaluationOut,
    status_code=status.HTTP_201_CREATED,
    tags=["candidates"],
    summary="Run the deterministic permit rules; the result is a recommendation, not a finding",
)
async def evaluate_candidate(
    candidate_id: uuid.UUID,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("candidate:evaluate"),
) -> Any:
    return await service.evaluate_candidate(ctx, actor, candidate_id)


@router.get(
    "/candidates/{candidate_id}/evaluations",
    response_model=list[EvaluationOut],
    tags=["candidates"],
)
async def candidate_evaluations(
    candidate_id: uuid.UUID,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("candidate:read"),
) -> Any:
    return await service.read(ctx, actor, lambda s: s.candidate_evaluations(candidate_id))


@router.post(
    "/candidates/{candidate_id}/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    tags=["verification"],
    summary="Officer verification: confirm, reject or request more evidence",
)
async def review_candidate(
    candidate_id: uuid.UUID,
    body: ReviewCreate,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("finding:verify"),
) -> Any:
    return await service.review_candidate(
        ctx,
        actor,
        candidate_id,
        decision=body.decision,
        justification=body.justification,
        evidence_refs=body.evidence_refs,
    )


@router.get(
    "/candidates/{candidate_id}/reviews", response_model=list[ReviewOut], tags=["verification"]
)
async def candidate_reviews(
    candidate_id: uuid.UUID,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("candidate:read"),
) -> Any:
    return await service.read(ctx, actor, lambda s: s.candidate_reviews(candidate_id))


# --------------------------------------------------------------------------- cases
@router.post(
    "/cases",
    response_model=CaseOut,
    status_code=status.HTTP_201_CREATED,
    tags=["cases"],
    summary="Open a case from an officer-verified candidate (409 otherwise)",
)
async def create_case(
    body: CaseCreate,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("case:create"),
) -> Any:
    return await service.create_case(ctx, actor, body.candidate_id)


@router.get("/cases", response_model=PageResponse[CaseOut], tags=["cases"])
async def list_cases(
    params: PageParamsDep,
    service: ServiceDep,
    actor: ActorDep,
    case_status: Annotated[
        Literal[
            "created", "assigned", "under_investigation", "notice_issued", "resolved", "dismissed"
        ]
        | None,
        Query(alias="status"),
    ] = None,
    assigned_to: uuid.UUID | None = None,
    ctx: AccessContext = _need("case:read"),
) -> Any:
    request = params.to_page_request()
    page = await service.read(
        ctx,
        actor,
        lambda s: s.list_cases(request, status=case_status, assigned_to=assigned_to),
    )
    return _page(page, CaseOut)


@router.get("/cases/{case_id}", response_model=CaseOut, tags=["cases"])
async def get_case(
    case_id: uuid.UUID,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("case:read"),
) -> Any:
    return _scoped(ctx, await service.read(ctx, actor, lambda s: s.get_case(case_id)))


@router.get("/cases/{case_id}/history", response_model=CaseHistoryOut, tags=["cases"])
async def case_history(
    case_id: uuid.UUID,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("case:read"),
) -> Any:
    return await service.read(ctx, actor, lambda s: s.case_history(case_id))


@router.post("/cases/{case_id}/assignment", response_model=CaseOut, tags=["cases"])
async def assign_case(
    case_id: uuid.UUID,
    body: CaseAssign,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("case:assign"),
) -> Any:
    return await service.assign_case(
        ctx,
        actor,
        case_id,
        assignee_id=body.assignee_id,
        reason=body.reason,
        expected_version=body.expected_version,
    )


@router.post("/cases/{case_id}/transitions", response_model=CaseOut, tags=["cases"])
async def transition_case(
    case_id: uuid.UUID,
    body: CaseTransition,
    request: Request,
    user: CurrentUserDep,
    store: Annotated[AccessStore, Depends(get_access_store)],
    service: ServiceDep,
    actor: ActorDep,
) -> Any:
    target = CaseStatus(body.target)
    # The permission depends on the requested state (resolve, notice, ...), so it is resolved here.
    ctx: AccessContext = await require_permission(TRANSITION_PERMISSION[target])(
        request, user, store
    )
    return await service.transition_case(
        ctx,
        actor,
        case_id,
        target=target,
        reason=body.reason,
        expected_version=body.expected_version,
    )


@router.post(
    "/cases/{case_id}/findings",
    response_model=FindingOut,
    status_code=status.HTTP_201_CREATED,
    tags=["cases"],
)
async def add_finding(
    case_id: uuid.UUID,
    body: FindingCreate,
    service: ServiceDep,
    actor: ActorDep,
    ctx: AccessContext = _need("case:update"),
) -> Any:
    return await service.add_finding(
        ctx,
        actor,
        case_id,
        notes=body.notes,
        measurements=dict(body.measurements),
        evidence=[e.model_dump() for e in body.evidence],
    )
