"""Parcels, properties, permits, construction-change candidates and cases (ADR-0011/0012/0014).

Every table is jurisdiction-owned: non-null ``jurisdiction_id`` and forced row-level security
(see the ``0005`` migration). Tables whose rows are a *history* (geometry versions, permit
events, reviews, evaluations, case transitions/assignments/findings) are append-only: a trigger
rejects UPDATE, DELETE and TRUNCATE for every role, administrators included (PRD FR-20.2).

Vector geometry is EPSG:4326 (ADR-0012); areas are computed on the geography type, i.e. in
square metres on the spheroid, so they do not depend on a per-jurisdiction projection yet.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditEntity, BaseEntity, VersionMixin
from app.db.models.access import _in

PERMIT_STATUSES = ("approved", "suspended", "revoked", "closed")
MATCH_STATUSES = ("matched", "unmatched", "conflict")
TOPOLOGY_STATUSES = ("clean", "overlaps_neighbour")
CANDIDATE_SOURCES = ("ai_detection", "manual_report", "imported")
CANDIDATE_STATUSES = ("unverified", "needs_evidence", "confirmed", "rejected")
REVIEW_DECISIONS = ("confirm", "reject", "request_evidence")
CHANGE_TYPES = ("new_structure", "extension", "alteration")
SEVERITIES = ("none", "low", "medium", "high")
CASE_STATUSES = (
    "created",
    "assigned",
    "under_investigation",
    "notice_issued",
    "resolved",
    "dismissed",
)
PERMIT_EVENTS = ("created", "status_changed", "match_resolved")

# Tables whose rows may be added but never changed or removed.
APPEND_ONLY_TABLES = (
    "parcel_geometry_version",
    "permit_history",
    "candidate_review",
    "candidate_evaluation",
    "case_state_transition",
    "case_assignment",
    "case_finding",
)


def _jurisdiction() -> Mapped[uuid.UUID]:
    return mapped_column(
        Uuid, ForeignKey("jurisdiction.id", ondelete="RESTRICT"), nullable=False, index=True
    )


def _user(*, nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(
        Uuid, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=nullable
    )


def _seq() -> Mapped[int]:
    """Insertion order that survives several rows sharing one transaction timestamp."""
    return mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True)


class Parcel(AuditEntity):
    """A parcel's stable identity; geometry lives in immutable versions."""

    __tablename__ = "parcel"
    __table_args__ = (
        UniqueConstraint("jurisdiction_id", "code", name="uq_parcel_jurisdiction_code"),
        CheckConstraint("length(btrim(code)) > 0", name="coded"),
        CheckConstraint("current_version >= 1", name="version_positive"),
    )

    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False)


class ParcelGeometryVersion(BaseEntity):
    __tablename__ = "parcel_geometry_version"
    __table_args__ = (
        UniqueConstraint("parcel_id", "version", name="uq_parcel_geometry_version_parcel_version"),
        CheckConstraint(_in("topology_status", TOPOLOGY_STATUSES), name="topology_status_valid"),
        CheckConstraint("ST_IsValid(geometry)", name="geometry_valid"),
        CheckConstraint("area_sq_m > 0", name="area_positive"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    parcel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("parcel.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry: Mapped[object] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False
    )
    area_sq_m: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    topology_status: Mapped[str] = mapped_column(String(32), nullable=False)
    topology_detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[uuid.UUID] = _user()


class PropertyRecord(AuditEntity):
    """The property master record for one parcel (PRD FR-5.1/5.2)."""

    __tablename__ = "property"
    __table_args__ = (
        UniqueConstraint("jurisdiction_id", "property_ref", name="uq_property_jurisdiction_ref"),
        UniqueConstraint("parcel_id", name="uq_property_parcel_id"),
        CheckConstraint("length(btrim(property_ref)) > 0", name="referenced"),
    )

    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    parcel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("parcel.id", ondelete="RESTRICT"), nullable=False
    )
    property_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    land_use: Mapped[str] = mapped_column(String(32), nullable=False)
    address_text: Mapped[str | None] = mapped_column(String(500), nullable=True)


class BuildingPermitRecord(AuditEntity, VersionMixin):
    """A sanctioned building permit as received from a source system."""

    __tablename__ = "building_permit"
    __table_args__ = (
        UniqueConstraint("jurisdiction_id", "permit_number", name="uq_building_permit_number"),
        CheckConstraint(_in("status", PERMIT_STATUSES), name="status_valid"),
        CheckConstraint(_in("match_status", MATCH_STATUSES), name="match_status_valid"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="window_ordered"),
        CheckConstraint("sanctioned_floors BETWEEN 1 AND 200", name="floors_range"),
        CheckConstraint("sanctioned_footprint_area_sq_m > 0", name="footprint_positive"),
        CheckConstraint(
            "match_status = 'unmatched' OR parcel_id IS NOT NULL", name="matched_has_parcel"
        ),
        Index("ix_building_permit_parcel_id", "parcel_id"),
        Index("ix_building_permit_jurisdiction_match", "jurisdiction_id", "match_status"),
    )

    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    permit_number: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    sanctioned_floors: Mapped[int] = mapped_column(Integer, nullable=False)
    sanctioned_footprint_area_sq_m: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    sanctioned_built_up_area_sq_m: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    declared_plot_area_sq_m: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    declared_parcel_code: Mapped[str] = mapped_column(String(64), nullable=False)
    parcel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("parcel.id", ondelete="RESTRICT"), nullable=True
    )
    match_status: Mapped[str] = mapped_column(String(16), nullable=False)
    match_detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class PermitHistory(BaseEntity):
    __tablename__ = "permit_history"
    __table_args__ = (CheckConstraint(_in("event", PERMIT_EVENTS), name="event_valid"),)

    seq: Mapped[int] = _seq()
    permit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("building_permit.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    from_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[uuid.UUID] = _user()
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class ConstructionChangeCandidate(AuditEntity):
    """A claim of construction change; ``unverified`` until an officer decides (ADR-0014)."""

    __tablename__ = "construction_change_candidate"
    __table_args__ = (
        CheckConstraint(_in("source_type", CANDIDATE_SOURCES), name="source_valid"),
        CheckConstraint(_in("status", CANDIDATE_STATUSES), name="status_valid"),
        CheckConstraint(_in("change_type", CHANGE_TYPES), name="change_type_valid"),
        CheckConstraint("ST_IsValid(footprint)", name="footprint_valid"),
        CheckConstraint("footprint_area_sq_m > 0", name="footprint_positive"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        CheckConstraint(
            "estimated_floors IS NULL OR estimated_floors BETWEEN 1 AND 200", name="floors_range"
        ),
        CheckConstraint(
            "source_type <> 'ai_detection' OR "
            "(model_name IS NOT NULL AND model_version IS NOT NULL AND confidence IS NOT NULL)",
            name="ai_provenance",
        ),
        CheckConstraint("jsonb_typeof(imagery_refs) = 'array'", name="imagery_is_array"),
        Index("ix_candidate_jurisdiction_status", "jurisdiction_id", "status"),
    )

    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    footprint: Mapped[object] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=True), nullable=False
    )
    footprint_area_sq_m: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    estimated_floors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    imagery_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    provenance_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    parcel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("parcel.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'unverified'")
    )


class CandidateReview(BaseEntity):
    """An officer's decision about a candidate (ADR-0014 §3-4); corrections append."""

    __tablename__ = "candidate_review"
    __table_args__ = (
        CheckConstraint(_in("decision", REVIEW_DECISIONS), name="decision_valid"),
        CheckConstraint(_in("resulting_status", CANDIDATE_STATUSES), name="status_valid"),
        CheckConstraint("length(btrim(justification)) >= 10", name="justified"),
        CheckConstraint("jsonb_typeof(evidence_refs) = 'array'", name="evidence_is_array"),
    )

    seq: Mapped[int] = _seq()
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("construction_change_candidate.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    reviewer_id: Mapped[uuid.UUID] = _user()
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    resulting_status: Mapped[str] = mapped_column(String(16), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    is_reversal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class CandidateEvaluation(BaseEntity):
    """One run of the deterministic rules; the full machine-readable explanation is kept."""

    __tablename__ = "candidate_evaluation"
    __table_args__ = (
        CheckConstraint(_in("severity", SEVERITIES), name="severity_valid"),
        CheckConstraint("jsonb_typeof(failed_rules) = 'array'", name="failed_is_array"),
    )

    seq: Mapped[int] = _seq()
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("construction_change_candidate.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    evaluated_by: Mapped[uuid.UUID] = _user()
    parcel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("parcel.id", ondelete="RESTRICT"), nullable=True
    )
    classification: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    failed_rules: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class InspectionCase(AuditEntity, VersionMixin):
    """A case opened from an officer-verified candidate; a trigger enforces that (ADR-0014)."""

    __tablename__ = "inspection_case"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_inspection_case_candidate_id"),
        CheckConstraint(_in("status", CASE_STATUSES), name="status_valid"),
        CheckConstraint(_in("source_type", CANDIDATE_SOURCES), name="source_valid"),
        CheckConstraint(_in("severity", SEVERITIES), name="severity_valid"),
        CheckConstraint("priority_score BETWEEN 0 AND 100", name="priority_range"),
        CheckConstraint(
            "status IN ('created', 'dismissed') OR assigned_to IS NOT NULL",
            name="active_has_assignee",
        ),
        Index("ix_inspection_case_jurisdiction_status", "jurisdiction_id", "status"),
        Index("ix_inspection_case_assigned_to", "assigned_to"),
    )

    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("construction_change_candidate.id", ondelete="RESTRICT"), nullable=False
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("candidate_evaluation.id", ondelete="RESTRICT"), nullable=False
    )
    parcel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("parcel.id", ondelete="RESTRICT"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    assigned_to: Mapped[uuid.UUID | None] = _user(nullable=True)
    opened_by: Mapped[uuid.UUID] = _user()


class CaseStateTransition(BaseEntity):
    __tablename__ = "case_state_transition"
    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR " + _in("from_status", CASE_STATUSES), name="from_valid"
        ),
        CheckConstraint(_in("to_status", CASE_STATUSES), name="to_valid"),
    )

    seq: Mapped[int] = _seq()
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inspection_case.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[uuid.UUID] = _user()
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CaseAssignment(BaseEntity):
    __tablename__ = "case_assignment"

    seq: Mapped[int] = _seq()
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inspection_case.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    assigned_to: Mapped[uuid.UUID] = _user()
    assigned_by: Mapped[uuid.UUID] = _user()
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CaseFinding(BaseEntity):
    __tablename__ = "case_finding"
    __table_args__ = (
        CheckConstraint("length(btrim(notes)) > 0", name="noted"),
        CheckConstraint("jsonb_typeof(evidence) = 'array'", name="evidence_is_array"),
    )

    seq: Mapped[int] = _seq()
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inspection_case.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    jurisdiction_id: Mapped[uuid.UUID] = _jurisdiction()
    author_id: Mapped[uuid.UUID] = _user()
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    measurements: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
