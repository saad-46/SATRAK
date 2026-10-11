"""Compliance workflow orchestration (parcels, permits, candidates, officer verification, cases).

This layer ties the pure domain rules (``app.contexts.*.domain``) to PostgreSQL persistence
(``app.db.compliance_store``) and the security audit log. Every operation:

1. receives an :class:`AccessContext` for the permission the route requires and checks the target
   jurisdiction against it (default deny);
2. runs inside a ``tenant_session`` so PostgreSQL row-level security limits the rows it can see
   to the caller's permitted jurisdictions, whatever the code does (ADR-0011);
3. applies the domain rules, persists, and records an audit event before the transaction commits.
   The audit log commits independently, so a refused action (``release.denied``) stays recorded
   even though its transaction rolls back. A failure to record fails the request (503).

AI findings are *candidates*: nothing here lets one reach a case, a notice or an enforcement
step until an officer has confirmed it (ADR-0014).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contexts.compliance.domain.candidate import (
    CandidateSource,
    CandidateStatus,
    ReviewDecision,
    decide_review,
    require_verified,
    validate_provenance,
)
from app.contexts.compliance.domain.evaluation import (
    EvaluationFacts,
    EvaluationParameters,
    PermitFacts,
    evaluate,
)
from app.contexts.inspection.domain.case import (
    TERMINAL,
    CaseSource,
    CaseStatus,
    compute_priority,
    validate_assignment_change,
    validate_finding,
    validate_transition,
)
from app.contexts.permit.domain.permit import (
    BuildingPermit,
    MatchStatus,
    PermitStatus,
    SanctionedPlan,
    assess_parcel_match,
    validate_status_change,
)
from app.contexts.property.domain.parcel import (
    normalize_land_use,
    normalize_parcel_code,
    normalize_property_ref,
)
from app.core.authz import AccessContext, AccessStore
from app.core.authz.verification import authorize_verification
from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.core.security_audit import (
    CANDIDATE_EVALUATED,
    CANDIDATE_REGISTERED,
    CANDIDATE_REVIEWED,
    CASE_ASSIGNED,
    CASE_CREATED,
    CASE_FINDING_ADDED,
    CASE_TRANSITIONED,
    PARCEL_CREATED,
    PARCEL_GEOMETRY_VERSIONED,
    PERMIT_CREATED,
    PERMIT_MATCH_RESOLVED,
    PERMIT_STATUS_CHANGED,
    PROPERTY_CREATED,
    RELEASE_DENIED,
    SecurityAuditLog,
    SecurityEvent,
)
from app.db.compliance_store import ComplianceStore
from app.db.rls import tenant_session
from app.shared.domain.errors import (
    BusinessRuleViolation,
    ValueValidationError,
    VerificationRequiredError,
)
from app.shared.pagination import Page, PageRequest
from app.shared.value_objects.polygon import parse_polygon_geojson

logger = structlog.get_logger("services.compliance")

Sessions = Callable[[], async_sessionmaker[AsyncSession]]

# The permission each case transition needs; the route resolves the context for it.
TRANSITION_PERMISSION: dict[CaseStatus, str] = {
    CaseStatus.ASSIGNED: "case:update",
    CaseStatus.UNDER_INVESTIGATION: "case:update",
    CaseStatus.NOTICE_ISSUED: "case:issue_notice",
    CaseStatus.RESOLVED: "case:resolve",
    CaseStatus.DISMISSED: "case:resolve",
}


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: uuid.UUID
    ip: str | None = None
    request_id: str | None = None


class ComplianceService:
    def __init__(
        self, sessions: Sessions, audit: SecurityAuditLog | None, access: AccessStore | None
    ) -> None:
        self._sessions = sessions
        self._audit = audit
        self._access = access

    # --------------------------------------------------------------- plumbing
    def _scope(self, ctx: AccessContext, actor: Actor) -> Any:
        return tenant_session(
            self._sessions, user_id=actor.user_id, jurisdiction_ids=ctx.jurisdictions
        )

    async def _record(
        self,
        event_type: str,
        ctx: AccessContext,
        actor: Actor,
        *,
        jurisdiction_id: uuid.UUID | None,
        outcome: str = "success",
        **details: str | int | bool | None,
    ) -> None:
        if self._audit is None:  # fail closed: an unaudited decision must not proceed
            raise ServiceUnavailableError("Auditing is not available.", code="audit_unavailable")
        event = SecurityEvent(
            event_type=event_type,
            outcome=outcome,
            actor_user_id=actor.user_id,
            jurisdiction_id=jurisdiction_id,
            permission=ctx.permission,
            ip=actor.ip,
            request_id=actor.request_id,
            details={k: v for k, v in details.items() if v is not None},
        )
        try:
            await self._audit.record(event)
        except Exception as exc:
            logger.error("audit_write_failed", event_type=event_type, error=type(exc).__name__)
            raise ServiceUnavailableError(
                "Auditing is temporarily unavailable.", code="audit_unavailable"
            ) from exc

    # ----------------------------------------------------------------- parcels
    async def create_parcel(
        self,
        ctx: AccessContext,
        actor: Actor,
        *,
        jurisdiction_id: uuid.UUID,
        code: str,
        geometry: object,
        reason: str | None,
    ) -> dict[str, Any]:
        ctx.require(jurisdiction_id)
        normalized = normalize_parcel_code(code)
        polygon = parse_polygon_geojson(geometry, allow_multi=True)
        async with self._scope(ctx, actor) as session:
            parcel = await ComplianceStore(session).create_parcel(
                jurisdiction_id=jurisdiction_id,
                code=normalized,
                polygon=polygon,
                actor=actor.user_id,
                reason=reason,
            )
            await self._record(
                PARCEL_CREATED,
                ctx,
                actor,
                jurisdiction_id=jurisdiction_id,
                parcel_id=str(parcel["id"]),
                topology=parcel["topology_status"],
            )
        return parcel

    async def add_parcel_geometry(
        self,
        ctx: AccessContext,
        actor: Actor,
        parcel_id: uuid.UUID,
        *,
        geometry: object,
        reason: str,
        expected_version: int,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise ValueValidationError("a reason is required", field="reason")
        polygon = parse_polygon_geojson(geometry, allow_multi=True)
        async with self._scope(ctx, actor) as session:
            parcel = await ComplianceStore(session).add_geometry_version(
                parcel_id,
                polygon=polygon,
                actor=actor.user_id,
                reason=reason.strip(),
                expected_version=expected_version,
            )
            ctx.require(parcel["jurisdiction_id"])
            await self._record(
                PARCEL_GEOMETRY_VERSIONED,
                ctx,
                actor,
                jurisdiction_id=parcel["jurisdiction_id"],
                parcel_id=str(parcel_id),
                version=parcel["current_version"],
                topology=parcel["topology_status"],
            )
        return parcel

    async def create_property(
        self,
        ctx: AccessContext,
        actor: Actor,
        *,
        jurisdiction_id: uuid.UUID,
        parcel_id: uuid.UUID,
        property_ref: str,
        land_use: str,
        address_text: str | None,
    ) -> dict[str, Any]:
        ctx.require(jurisdiction_id)
        async with self._scope(ctx, actor) as session:
            record = await ComplianceStore(session).create_property(
                jurisdiction_id=jurisdiction_id,
                parcel_id=parcel_id,
                property_ref=normalize_property_ref(property_ref),
                land_use=normalize_land_use(land_use),
                address_text=address_text.strip() if address_text else None,
                actor=actor.user_id,
            )
            await self._record(
                PROPERTY_CREATED,
                ctx,
                actor,
                jurisdiction_id=jurisdiction_id,
                property_id=str(record["id"]),
            )
        return record

    # ----------------------------------------------------------------- permits
    async def create_permit(
        self,
        ctx: AccessContext,
        actor: Actor,
        *,
        jurisdiction_id: uuid.UUID,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        ctx.require(jurisdiction_id)
        code = normalize_parcel_code(fields["declared_parcel_code"])
        # Constructing the domain object validates the permit's own rules.
        BuildingPermit(
            permit_number=fields["permit_number"].strip(),
            status=PermitStatus(fields["status"]),
            valid_from=fields["valid_from"],
            valid_to=fields.get("valid_to"),
            plan=SanctionedPlan(
                floors=fields["sanctioned_floors"],
                footprint_area_sq_m=float(fields["sanctioned_footprint_area_sq_m"]),
                built_up_area_sq_m=_optional_float(fields.get("sanctioned_built_up_area_sq_m")),
            ),
        )
        values = {
            **fields,
            "permit_number": fields["permit_number"].strip(),
            "declared_parcel_code": code,
        }
        async with self._scope(ctx, actor) as session:
            store = ComplianceStore(session)
            parcel = await store.find_parcel_by_code(jurisdiction_id, code)
            plot = _optional_float(fields.get("declared_plot_area_sq_m"))
            assessment = assess_parcel_match(
                parcel_found=parcel is not None,
                parcel_area_sq_m=None if parcel is None else float(parcel["area_sq_m"]),
                declared_plot_area_sq_m=plot,
            )
            matched = assessment.status is not MatchStatus.UNMATCHED
            permit = await store.create_permit(
                jurisdiction_id=jurisdiction_id,
                values=values,
                parcel_id=parcel["id"] if parcel is not None and matched else None,
                match_status=assessment.status.value,
                match_detail=assessment.detail,
                actor=actor.user_id,
            )
            await self._record(
                PERMIT_CREATED,
                ctx,
                actor,
                jurisdiction_id=jurisdiction_id,
                permit_id=str(permit["id"]),
                match_status=permit["match_status"],
                simulated=bool(fields["is_simulated"]),
            )
        return permit

    async def change_permit_status(
        self,
        ctx: AccessContext,
        actor: Actor,
        permit_id: uuid.UUID,
        *,
        target: str,
        reason: str,
        expected_version: int,
    ) -> dict[str, Any]:
        if len(reason.strip()) < 3:
            raise ValueValidationError("a reason is required", field="reason")
        target_status = PermitStatus(target)
        async with self._scope(ctx, actor) as session:
            permit = await ComplianceStore(session).change_permit_status(
                permit_id,
                target=target_status.value,
                reason=reason.strip(),
                actor=actor.user_id,
                expected_version=expected_version,
                validate=lambda current, new: validate_status_change(
                    PermitStatus(current), PermitStatus(new)
                ),
            )
            ctx.require(permit["jurisdiction_id"])
            await self._record(
                PERMIT_STATUS_CHANGED,
                ctx,
                actor,
                jurisdiction_id=permit["jurisdiction_id"],
                permit_id=str(permit_id),
                to_status=target_status.value,
            )
        return permit

    async def resolve_permit_match(
        self,
        ctx: AccessContext,
        actor: Actor,
        permit_id: uuid.UUID,
        *,
        parcel_id: uuid.UUID,
        reason: str,
        expected_version: int,
    ) -> dict[str, Any]:
        if len(reason.strip()) < 10:
            raise ValueValidationError(
                "a reason of at least 10 characters is required", field="reason"
            )
        async with self._scope(ctx, actor) as session:
            permit = await ComplianceStore(session).resolve_permit_match(
                permit_id,
                parcel_id=parcel_id,
                reason=reason.strip(),
                actor=actor.user_id,
                expected_version=expected_version,
            )
            ctx.require(permit["jurisdiction_id"])
            await self._record(
                PERMIT_MATCH_RESOLVED,
                ctx,
                actor,
                jurisdiction_id=permit["jurisdiction_id"],
                permit_id=str(permit_id),
                parcel_id=str(parcel_id),
            )
        return permit

    # -------------------------------------------------------------- candidates
    async def register_candidate(
        self,
        ctx: AccessContext,
        actor: Actor,
        *,
        jurisdiction_id: uuid.UUID,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        ctx.require(jurisdiction_id)
        source = CandidateSource(fields["source_type"])
        validate_provenance(
            source=source,
            model_name=fields.get("model_name"),
            model_version=fields.get("model_version"),
            confidence=_optional_float(fields.get("confidence")),
            imagery_refs=fields["imagery_refs"],
            observed_on=fields["observed_on"],
        )
        if fields["observed_on"] > datetime.now(UTC).date():
            raise ValueValidationError("the observation date is in the future", field="observed_on")
        polygon = parse_polygon_geojson(fields["footprint"], allow_multi=False, field="footprint")
        async with self._scope(ctx, actor) as session:
            candidate = await ComplianceStore(session).create_candidate(
                jurisdiction_id=jurisdiction_id, polygon=polygon, values=fields, actor=actor.user_id
            )
            await self._record(
                CANDIDATE_REGISTERED,
                ctx,
                actor,
                jurisdiction_id=jurisdiction_id,
                candidate_id=str(candidate["id"]),
                source=source.value,
                simulated=bool(fields["is_simulated"]),
            )
        return candidate

    async def evaluate_candidate(
        self,
        ctx: AccessContext,
        actor: Actor,
        candidate_id: uuid.UUID,
        *,
        parameters: EvaluationParameters | None = None,
    ) -> dict[str, Any]:
        async with self._scope(ctx, actor) as session:
            store = ComplianceStore(session)
            candidate = await store.get_candidate(candidate_id, lock=True)
            ctx.require(candidate["jurisdiction_id"])
            if candidate["status"] not in (
                CandidateStatus.UNVERIFIED.value,
                CandidateStatus.NEEDS_EVIDENCE.value,
            ):
                raise BusinessRuleViolation(
                    "only a candidate still under review can be re-evaluated",
                    details={"status": candidate["status"]},
                )
            facts = await store.evaluation_facts(candidate)
            observed = candidate["observed_on"]
            permits = tuple(_permit_facts(p, observed) for p in facts["permits"])
            result = evaluate(
                EvaluationFacts(
                    observed_on=observed,
                    candidate_area_sq_m=float(candidate["footprint_area_sq_m"]),
                    estimated_floors=candidate["estimated_floors"],
                    parcel_id=None if facts["parcel_id"] is None else str(facts["parcel_id"]),
                    parcel_code=facts["parcel_code"],
                    outside_parcel_area_sq_m=facts["outside_sq_m"],
                    permits=permits,
                    unresolved_permit_count=facts["unresolved"],
                ),
                parameters,
            )
            evaluation = await store.record_evaluation(
                candidate,
                parcel_id=facts["parcel_id"],
                classification=result.classification.value,
                severity=result.severity.value,
                failed_rules=list(result.failed_rules),
                result=result.to_dict(),
                actor=actor.user_id,
            )
            await self._record(
                CANDIDATE_EVALUATED,
                ctx,
                actor,
                jurisdiction_id=candidate["jurisdiction_id"],
                candidate_id=str(candidate_id),
                classification=result.classification.value,
                severity=result.severity.value,
            )
        return evaluation

    async def review_candidate(
        self,
        ctx: AccessContext,
        actor: Actor,
        candidate_id: uuid.UUID,
        *,
        decision: str,
        justification: str,
        evidence_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        review_decision = ReviewDecision(decision)
        async with self._scope(ctx, actor) as session:
            store = ComplianceStore(session)
            candidate = await store.review_context(candidate_id)
            # Jurisdiction-scoped verification right (ADR-0014): the permission alone is not enough.
            authorize_verification(ctx, candidate["jurisdiction_id"])
            outcome = decide_review(
                current=CandidateStatus(candidate["status"]),
                decision=review_decision,
                justification=justification,
                evidence_complete=len(candidate["imagery_refs"]) > 0,
                evaluated=candidate["evaluated"],
                has_open_case=candidate["has_open_case"],
            )
            review = await store.record_review(
                candidate,
                decision=review_decision.value,
                resulting_status=outcome.status.value,
                justification=justification.strip(),
                evidence_refs=evidence_refs,
                is_reversal=outcome.is_reversal,
                actor=actor.user_id,
            )
            await self._record(
                CANDIDATE_REVIEWED,
                ctx,
                actor,
                jurisdiction_id=candidate["jurisdiction_id"],
                candidate_id=str(candidate_id),
                decision=review_decision.value,
                result=outcome.status.value,
                reversal=outcome.is_reversal,
            )
        return review

    # ------------------------------------------------------------------- cases
    async def create_case(
        self, ctx: AccessContext, actor: Actor, candidate_id: uuid.UUID
    ) -> dict[str, Any]:
        async with self._scope(ctx, actor) as session:
            store = ComplianceStore(session)
            candidate = await store.get_candidate(candidate_id, lock=True)
            ctx.require(candidate["jurisdiction_id"])
            try:
                require_verified(CandidateStatus(candidate["status"]))
            except VerificationRequiredError:
                await self._record(
                    RELEASE_DENIED,
                    ctx,
                    actor,
                    jurisdiction_id=candidate["jurisdiction_id"],
                    outcome="denied",
                    candidate_id=str(candidate_id),
                    status=candidate["status"],
                )
                raise
            evaluation = await store.latest_evaluation(candidate_id)
            if evaluation is None:  # unreachable for a confirmed candidate; defence in depth
                raise BusinessRuleViolation(
                    "the candidate has no recorded evaluation", details={"missing": "evaluation"}
                )
            priority = compute_priority(
                evaluation["severity"], CaseSource(candidate["source_type"])
            )
            case = await store.create_case(
                candidate, evaluation=evaluation, priority_score=priority, actor=actor.user_id
            )
            await self._record(
                CASE_CREATED,
                ctx,
                actor,
                jurisdiction_id=case["jurisdiction_id"],
                case_id=str(case["id"]),
                candidate_id=str(candidate_id),
                priority=priority,
            )
        return case

    async def assign_case(
        self,
        ctx: AccessContext,
        actor: Actor,
        case_id: uuid.UUID,
        *,
        assignee_id: uuid.UUID,
        reason: str | None,
        expected_version: int,
    ) -> dict[str, Any]:
        if self._access is None:
            raise ServiceUnavailableError(
                "Authorization is not available.", code="authz_unavailable"
            )
        async with self._scope(ctx, actor) as session:
            store = ComplianceStore(session)
            case = await store.get_case(case_id, lock=True)
            ctx.require(case["jurisdiction_id"])
            new_status = validate_assignment_change(CaseStatus(case["status"]))
            eligible = await self._access.permitted_jurisdictions(
                user_id=assignee_id, permission="case:update", at=datetime.now(UTC)
            )
            if case["jurisdiction_id"] not in eligible:
                raise BusinessRuleViolation(
                    "the assignee does not hold case:update in the case's jurisdiction",
                    details={"assignee_id": str(assignee_id)},
                )
            updated = await store.assign_case(
                case,
                assignee=assignee_id,
                new_status=new_status.value,
                reason=reason,
                actor=actor.user_id,
                expected_version=expected_version,
            )
            await self._record(
                CASE_ASSIGNED,
                ctx,
                actor,
                jurisdiction_id=case["jurisdiction_id"],
                case_id=str(case_id),
                assignee_id=str(assignee_id),
            )
        return updated

    async def transition_case(
        self,
        ctx: AccessContext,
        actor: Actor,
        case_id: uuid.UUID,
        *,
        target: CaseStatus,
        reason: str | None,
        expected_version: int,
    ) -> dict[str, Any]:
        if ctx.permission != TRANSITION_PERMISSION[target]:
            raise ctx.denial()
        async with self._scope(ctx, actor) as session:
            store = ComplianceStore(session)
            case = await store.get_case(case_id, lock=True)
            ctx.require(case["jurisdiction_id"])
            validate_transition(
                CaseStatus(case["status"]),
                target,
                has_assignee=case["assigned_to"] is not None,
                finding_count=await store.finding_count(case_id),
            )
            updated = await store.transition_case(
                case,
                target=target.value,
                reason=reason,
                actor=actor.user_id,
                expected_version=expected_version,
            )
            await self._record(
                CASE_TRANSITIONED,
                ctx,
                actor,
                jurisdiction_id=case["jurisdiction_id"],
                case_id=str(case_id),
                from_status=case["status"],
                to_status=target.value,
            )
        return updated

    async def add_finding(
        self,
        ctx: AccessContext,
        actor: Actor,
        case_id: uuid.UUID,
        *,
        notes: str,
        measurements: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        clean_notes, clean_measurements, clean_evidence = validate_finding(
            notes, measurements, evidence
        )
        async with self._scope(ctx, actor) as session:
            store = ComplianceStore(session)
            case = await store.get_case(case_id, lock=True)
            ctx.require(case["jurisdiction_id"])
            status = CaseStatus(case["status"])
            if status in TERMINAL or status is CaseStatus.CREATED:
                raise BusinessRuleViolation(
                    "findings can be recorded only on an assigned, open case",
                    details={"status": status.value},
                )
            finding = await store.add_finding(
                case,
                notes=clean_notes,
                measurements=clean_measurements,
                evidence=[e.to_dict() for e in clean_evidence],
                actor=actor.user_id,
            )
            await self._record(
                CASE_FINDING_ADDED,
                ctx,
                actor,
                jurisdiction_id=case["jurisdiction_id"],
                case_id=str(case_id),
                evidence_items=len(clean_evidence),
            )
        return finding

    # ------------------------------------------------------------------- reads
    async def read(
        self, ctx: AccessContext, actor: Actor, operation: Callable[[ComplianceStore], Any]
    ) -> Any:
        """Run a read inside the caller's tenant scope (rows outside it do not exist for them)."""
        async with self._scope(ctx, actor) as session:
            return await operation(ComplianceStore(session))

    async def read_in_jurisdiction(
        self,
        ctx: AccessContext,
        actor: Actor,
        operation: Callable[[ComplianceStore], Any],
    ) -> Any:
        result = await self.read(ctx, actor, operation)
        if isinstance(result, dict) and "jurisdiction_id" in result:
            ctx.require(result["jurisdiction_id"])
        return result


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _permit_facts(row: dict[str, Any], observed_on: date) -> PermitFacts:
    permit = BuildingPermit(
        permit_number=row["permit_number"],
        status=PermitStatus(row["status"]),
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        plan=SanctionedPlan(
            floors=row["sanctioned_floors"],
            footprint_area_sq_m=float(row["sanctioned_footprint_area_sq_m"]),
        ),
    )
    return PermitFacts(
        permit_id=str(row["id"]),
        permit_number=row["permit_number"],
        status=row["status"],
        ineffective_reason=permit.ineffective_reason(observed_on),
        sanctioned_floors=row["sanctioned_floors"],
        sanctioned_footprint_area_sq_m=float(row["sanctioned_footprint_area_sq_m"]),
    )


__all__ = ["Actor", "ComplianceService", "NotFoundError", "Page", "PageRequest"]
