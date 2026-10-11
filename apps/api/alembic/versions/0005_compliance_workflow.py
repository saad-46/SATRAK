"""Parcels, properties, permits, construction-change candidates and cases.

Adds the jurisdiction-owned tables of the construction-compliance workflow (ADR-0011, 0012,
0014), all with forced row-level security. Beyond the plain tables this migration installs the
database-level guarantees the application also enforces:

* history tables are append-only for every role (UPDATE/DELETE/TRUNCATE are rejected);
* a child row must carry the jurisdiction of the row it references (no cross-tenant links);
* a candidate becomes ``confirmed`` only after a matching officer review is recorded, and its
  evidence columns never change;
* a case can only be inserted for a ``confirmed`` candidate that has been evaluated (the
  ADR-0014 release gate, enforced in the database as well as in the service);
* a closed case is immutable.

It also extends the security audit event types and seeds the permission catalogue. Role and
assignment data are not touched. Downgrade removes everything created here.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_TABLES = (
    "parcel",
    "parcel_geometry_version",
    "property",
    "building_permit",
    "permit_history",
    "construction_change_candidate",
    "candidate_review",
    "candidate_evaluation",
    "inspection_case",
    "case_state_transition",
    "case_assignment",
    "case_finding",
)
APPEND_ONLY_TABLES = (
    "parcel_geometry_version",
    "permit_history",
    "candidate_review",
    "candidate_evaluation",
    "case_state_transition",
    "case_assignment",
    "case_finding",
)
MUTABLE_TABLES = tuple(t for t in TENANT_TABLES if t not in APPEND_ONLY_TABLES)

# (child table, foreign-key column, parent table): the child's jurisdiction must equal the parent's.
CHILD_LINKS = (
    ("parcel_geometry_version", "parcel_id", "parcel"),
    ("property", "parcel_id", "parcel"),
    ("building_permit", "parcel_id", "parcel"),
    ("permit_history", "permit_id", "building_permit"),
    ("construction_change_candidate", "parcel_id", "parcel"),
    ("candidate_review", "candidate_id", "construction_change_candidate"),
    ("candidate_evaluation", "candidate_id", "construction_change_candidate"),
    ("candidate_evaluation", "parcel_id", "parcel"),
    ("inspection_case", "candidate_id", "construction_change_candidate"),
    ("inspection_case", "parcel_id", "parcel"),
    ("case_state_transition", "case_id", "inspection_case"),
    ("case_assignment", "case_id", "inspection_case"),
    ("case_finding", "case_id", "inspection_case"),
)

_BASE_EVENT_TYPES = (
    "privileged_db.used",
    "access.denied",
    "session.revoked",
    "user.login_failed",
    "user.logged_in",
)
_WORKFLOW_EVENT_TYPES = (
    "parcel.created",
    "parcel.geometry_versioned",
    "property.created",
    "permit.created",
    "permit.status_changed",
    "permit.match_resolved",
    "candidate.registered",
    "candidate.evaluated",
    "candidate.reviewed",
    "release.denied",
    "case.created",
    "case.assigned",
    "case.transitioned",
    "case.finding_added",
)

PERMISSIONS = {
    "parcel:read": "Read parcels and their geometry history",
    "parcel:write": "Register parcels and append geometry versions",
    "property:read": "Read property master records",
    "property:write": "Register property master records",
    "permit:read": "Read building permits and their history",
    "permit:write": "Register permits, change their status and resolve parcel matches",
    "candidate:read": "Read construction-change candidates (unverified findings included)",
    "candidate:create": "Register construction-change candidates",
    "candidate:evaluate": "Evaluate candidates against permit records",
    "finding:verify": "Verify or reject a construction-change candidate (officer verification)",
    "case:read": "Read inspection cases",
    "case:create": "Open a case from a verified candidate",
    "case:assign": "Assign or reassign a case",
    "case:update": "Record findings and start an investigation",
    "case:resolve": "Resolve or dismiss a case",
    "case:issue_notice": "Record that a notice is warranted on a case",
}

_PERMITTED = "jurisdiction_id = ANY (app_permitted_jurisdictions())"


def _event_types(*groups: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{t}'" for g in groups for t in g) + ")"


def _if_role(role: str, statement: str) -> str:
    return (
        f"DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "
        f"{statement}; END IF; END $$"
    )


def upgrade() -> None:
    op.create_table(
        "parcel",
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("current_version >= 1", name=op.f("ck_parcel_version_positive")),
        sa.CheckConstraint("length(btrim(code)) > 0", name=op.f("ck_parcel_coded")),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_parcel_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parcel")),
        sa.UniqueConstraint("jurisdiction_id", "code", name="uq_parcel_jurisdiction_code"),
    )
    op.create_index(op.f("ix_parcel_jurisdiction_id"), "parcel", ["jurisdiction_id"], unique=False)
    op.create_table(
        "building_permit",
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("permit_number", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("sanctioned_floors", sa.Integer(), nullable=False),
        sa.Column(
            "sanctioned_footprint_area_sq_m", sa.Numeric(precision=14, scale=2), nullable=False
        ),
        sa.Column(
            "sanctioned_built_up_area_sq_m", sa.Numeric(precision=14, scale=2), nullable=True
        ),
        sa.Column("declared_plot_area_sq_m", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("declared_parcel_code", sa.String(length=64), nullable=False),
        sa.Column("parcel_id", sa.Uuid(), nullable=True),
        sa.Column("match_status", sa.String(length=16), nullable=False),
        sa.Column(
            "match_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("source_record_ref", sa.String(length=128), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "match_status = 'unmatched' OR parcel_id IS NOT NULL",
            name=op.f("ck_building_permit_matched_has_parcel"),
        ),
        sa.CheckConstraint(
            "match_status IN ('matched', 'unmatched', 'conflict')",
            name=op.f("ck_building_permit_match_status_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('approved', 'suspended', 'revoked', 'closed')",
            name=op.f("ck_building_permit_status_valid"),
        ),
        sa.CheckConstraint(
            "sanctioned_floors BETWEEN 1 AND 200", name=op.f("ck_building_permit_floors_range")
        ),
        sa.CheckConstraint(
            "sanctioned_footprint_area_sq_m > 0", name=op.f("ck_building_permit_footprint_positive")
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name=op.f("ck_building_permit_window_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_building_permit_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parcel_id"],
            ["parcel.id"],
            name=op.f("fk_building_permit_parcel_id_parcel"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_building_permit")),
        sa.UniqueConstraint("jurisdiction_id", "permit_number", name="uq_building_permit_number"),
    )
    op.create_index(
        op.f("ix_building_permit_jurisdiction_id"),
        "building_permit",
        ["jurisdiction_id"],
        unique=False,
    )
    op.create_index(
        "ix_building_permit_jurisdiction_match",
        "building_permit",
        ["jurisdiction_id", "match_status"],
        unique=False,
    )
    op.create_index("ix_building_permit_parcel_id", "building_permit", ["parcel_id"], unique=False)
    op.create_table(
        "construction_change_candidate",
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("change_type", sa.String(length=32), nullable=False),
        sa.Column(
            "footprint",
            geoalchemy2.types.Geometry(
                geometry_type="POLYGON",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("footprint_area_sq_m", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("estimated_floors", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column(
            "imagery_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("provenance_note", sa.Text(), nullable=True),
        sa.Column("parcel_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "change_type IN ('new_structure', 'extension', 'alteration')",
            name=op.f("ck_construction_change_candidate_change_type_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(imagery_refs) = 'array'",
            name=op.f("ck_construction_change_candidate_imagery_is_array"),
        ),
        sa.CheckConstraint(
            "source_type <> 'ai_detection' OR "
            "(model_name IS NOT NULL AND model_version IS NOT NULL AND confidence IS NOT NULL)",
            name=op.f("ck_construction_change_candidate_ai_provenance"),
        ),
        sa.CheckConstraint(
            "source_type IN ('ai_detection', 'manual_report', 'imported')",
            name=op.f("ck_construction_change_candidate_source_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('unverified', 'needs_evidence', 'confirmed', 'rejected')",
            name=op.f("ck_construction_change_candidate_status_valid"),
        ),
        sa.CheckConstraint(
            "ST_IsValid(footprint)", name=op.f("ck_construction_change_candidate_footprint_valid")
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name=op.f("ck_construction_change_candidate_confidence_range"),
        ),
        sa.CheckConstraint(
            "estimated_floors IS NULL OR estimated_floors BETWEEN 1 AND 200",
            name=op.f("ck_construction_change_candidate_floors_range"),
        ),
        sa.CheckConstraint(
            "footprint_area_sq_m > 0",
            name=op.f("ck_construction_change_candidate_footprint_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_construction_change_candidate_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parcel_id"],
            ["parcel.id"],
            name=op.f("fk_construction_change_candidate_parcel_id_parcel"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_construction_change_candidate")),
    )
    op.create_index(
        "ix_candidate_jurisdiction_status",
        "construction_change_candidate",
        ["jurisdiction_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_construction_change_candidate_jurisdiction_id"),
        "construction_change_candidate",
        ["jurisdiction_id"],
        unique=False,
    )
    op.create_table(
        "property",
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("parcel_id", sa.Uuid(), nullable=False),
        sa.Column("property_ref", sa.String(length=64), nullable=False),
        sa.Column("land_use", sa.String(length=32), nullable=False),
        sa.Column("address_text", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("length(btrim(property_ref)) > 0", name=op.f("ck_property_referenced")),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_property_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parcel_id"],
            ["parcel.id"],
            name=op.f("fk_property_parcel_id_parcel"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property")),
        sa.UniqueConstraint("jurisdiction_id", "property_ref", name="uq_property_jurisdiction_ref"),
        sa.UniqueConstraint("parcel_id", name="uq_property_parcel_id"),
    )
    op.create_index(
        op.f("ix_property_jurisdiction_id"), "property", ["jurisdiction_id"], unique=False
    )
    op.create_table(
        "candidate_evaluation",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("evaluated_by", sa.Uuid(), nullable=False),
        sa.Column("parcel_id", sa.Uuid(), nullable=True),
        sa.Column("classification", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("failed_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(failed_rules) = 'array'",
            name=op.f("ck_candidate_evaluation_failed_is_array"),
        ),
        sa.CheckConstraint(
            "severity IN ('none', 'low', 'medium', 'high')",
            name=op.f("ck_candidate_evaluation_severity_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["construction_change_candidate.id"],
            name=op.f("fk_candidate_evaluation_candidate_id_construction_change_candidate"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evaluated_by"],
            ["user_account.id"],
            name=op.f("fk_candidate_evaluation_evaluated_by_user_account"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_candidate_evaluation_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parcel_id"],
            ["parcel.id"],
            name=op.f("fk_candidate_evaluation_parcel_id_parcel"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_evaluation")),
        sa.UniqueConstraint("seq", name=op.f("uq_candidate_evaluation_seq")),
    )
    op.create_index(
        op.f("ix_candidate_evaluation_candidate_id"),
        "candidate_evaluation",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_evaluation_jurisdiction_id"),
        "candidate_evaluation",
        ["jurisdiction_id"],
        unique=False,
    )
    op.create_table(
        "candidate_review",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("resulting_status", sa.String(length=16), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column(
            "evidence_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_reversal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('confirm', 'reject', 'request_evidence')",
            name=op.f("ck_candidate_review_decision_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_refs) = 'array'",
            name=op.f("ck_candidate_review_evidence_is_array"),
        ),
        sa.CheckConstraint(
            "resulting_status IN ('unverified', 'needs_evidence', 'confirmed', 'rejected')",
            name=op.f("ck_candidate_review_status_valid"),
        ),
        sa.CheckConstraint(
            "length(btrim(justification)) >= 10", name=op.f("ck_candidate_review_justified")
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["construction_change_candidate.id"],
            name=op.f("fk_candidate_review_candidate_id_construction_change_candidate"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_candidate_review_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["user_account.id"],
            name=op.f("fk_candidate_review_reviewer_id_user_account"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_review")),
        sa.UniqueConstraint("seq", name=op.f("uq_candidate_review_seq")),
    )
    op.create_index(
        op.f("ix_candidate_review_candidate_id"), "candidate_review", ["candidate_id"], unique=False
    )
    op.create_index(
        op.f("ix_candidate_review_jurisdiction_id"),
        "candidate_review",
        ["jurisdiction_id"],
        unique=False,
    )
    op.create_table(
        "parcel_geometry_version",
        sa.Column("parcel_id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(
                geometry_type="MULTIPOLYGON",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("area_sq_m", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("topology_status", sa.String(length=32), nullable=False),
        sa.Column(
            "topology_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "topology_status IN ('clean', 'overlaps_neighbour')",
            name=op.f("ck_parcel_geometry_version_topology_status_valid"),
        ),
        sa.CheckConstraint(
            "ST_IsValid(geometry)", name=op.f("ck_parcel_geometry_version_geometry_valid")
        ),
        sa.CheckConstraint("area_sq_m > 0", name=op.f("ck_parcel_geometry_version_area_positive")),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_parcel_geometry_version_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_parcel_geometry_version_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parcel_id"],
            ["parcel.id"],
            name=op.f("fk_parcel_geometry_version_parcel_id_parcel"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["user_account.id"],
            name=op.f("fk_parcel_geometry_version_recorded_by_user_account"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parcel_geometry_version")),
        sa.UniqueConstraint(
            "parcel_id", "version", name="uq_parcel_geometry_version_parcel_version"
        ),
    )
    op.create_index(
        op.f("ix_parcel_geometry_version_jurisdiction_id"),
        "parcel_geometry_version",
        ["jurisdiction_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_parcel_geometry_version_parcel_id"),
        "parcel_geometry_version",
        ["parcel_id"],
        unique=False,
    )
    op.create_table(
        "permit_history",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("permit_id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("from_value", sa.String(length=64), nullable=True),
        sa.Column("to_value", sa.String(length=64), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event IN ('created', 'status_changed', 'match_resolved')",
            name=op.f("ck_permit_history_event_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["user_account.id"],
            name=op.f("fk_permit_history_actor_id_user_account"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_permit_history_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["permit_id"],
            ["building_permit.id"],
            name=op.f("fk_permit_history_permit_id_building_permit"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permit_history")),
        sa.UniqueConstraint("seq", name=op.f("uq_permit_history_seq")),
    )
    op.create_index(
        op.f("ix_permit_history_jurisdiction_id"),
        "permit_history",
        ["jurisdiction_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_permit_history_permit_id"), "permit_history", ["permit_id"], unique=False
    )
    op.create_table(
        "inspection_case",
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("parcel_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("priority_score", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("opened_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "severity IN ('none', 'low', 'medium', 'high')",
            name=op.f("ck_inspection_case_severity_valid"),
        ),
        sa.CheckConstraint(
            "source_type IN ('ai_detection', 'manual_report', 'imported')",
            name=op.f("ck_inspection_case_source_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('created', 'assigned', 'under_investigation', "
            "'notice_issued', 'resolved', 'dismissed')",
            name=op.f("ck_inspection_case_status_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('created', 'dismissed') OR assigned_to IS NOT NULL",
            name=op.f("ck_inspection_case_active_has_assignee"),
        ),
        sa.CheckConstraint(
            "priority_score BETWEEN 0 AND 100", name=op.f("ck_inspection_case_priority_range")
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["user_account.id"],
            name=op.f("fk_inspection_case_assigned_to_user_account"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["construction_change_candidate.id"],
            name=op.f("fk_inspection_case_candidate_id_construction_change_candidate"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["candidate_evaluation.id"],
            name=op.f("fk_inspection_case_evaluation_id_candidate_evaluation"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_inspection_case_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["opened_by"],
            ["user_account.id"],
            name=op.f("fk_inspection_case_opened_by_user_account"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parcel_id"],
            ["parcel.id"],
            name=op.f("fk_inspection_case_parcel_id_parcel"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inspection_case")),
        sa.UniqueConstraint("candidate_id", name="uq_inspection_case_candidate_id"),
    )
    op.create_index(
        "ix_inspection_case_assigned_to", "inspection_case", ["assigned_to"], unique=False
    )
    op.create_index(
        op.f("ix_inspection_case_jurisdiction_id"),
        "inspection_case",
        ["jurisdiction_id"],
        unique=False,
    )
    op.create_index(
        "ix_inspection_case_jurisdiction_status",
        "inspection_case",
        ["jurisdiction_id", "status"],
        unique=False,
    )
    op.create_table(
        "case_assignment",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"],
            ["user_account.id"],
            name=op.f("fk_case_assignment_assigned_by_user_account"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["user_account.id"],
            name=op.f("fk_case_assignment_assigned_to_user_account"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["inspection_case.id"],
            name=op.f("fk_case_assignment_case_id_inspection_case"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_case_assignment_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_assignment")),
        sa.UniqueConstraint("seq", name=op.f("uq_case_assignment_seq")),
    )
    op.create_index(
        op.f("ix_case_assignment_case_id"), "case_assignment", ["case_id"], unique=False
    )
    op.create_index(
        op.f("ix_case_assignment_jurisdiction_id"),
        "case_assignment",
        ["jurisdiction_id"],
        unique=False,
    )
    op.create_table(
        "case_finding",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column(
            "measurements",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'array'", name=op.f("ck_case_finding_evidence_is_array")
        ),
        sa.CheckConstraint("length(btrim(notes)) > 0", name=op.f("ck_case_finding_noted")),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["user_account.id"],
            name=op.f("fk_case_finding_author_id_user_account"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["inspection_case.id"],
            name=op.f("fk_case_finding_case_id_inspection_case"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_case_finding_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_finding")),
        sa.UniqueConstraint("seq", name=op.f("uq_case_finding_seq")),
    )
    op.create_index(op.f("ix_case_finding_case_id"), "case_finding", ["case_id"], unique=False)
    op.create_index(
        op.f("ix_case_finding_jurisdiction_id"), "case_finding", ["jurisdiction_id"], unique=False
    )
    op.create_table(
        "case_state_transition",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('created', 'assigned', "
            "'under_investigation', 'notice_issued', 'resolved', 'dismissed')",
            name=op.f("ck_case_state_transition_from_valid"),
        ),
        sa.CheckConstraint(
            "to_status IN ('created', 'assigned', 'under_investigation', "
            "'notice_issued', 'resolved', 'dismissed')",
            name=op.f("ck_case_state_transition_to_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["user_account.id"],
            name=op.f("fk_case_state_transition_actor_id_user_account"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["inspection_case.id"],
            name=op.f("fk_case_state_transition_case_id_inspection_case"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_case_state_transition_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_state_transition")),
        sa.UniqueConstraint("seq", name=op.f("uq_case_state_transition_seq")),
    )
    op.create_index(
        op.f("ix_case_state_transition_case_id"), "case_state_transition", ["case_id"], unique=False
    )
    op.create_index(
        op.f("ix_case_state_transition_jurisdiction_id"),
        "case_state_transition",
        ["jurisdiction_id"],
        unique=False,
    )

    # --- Guarantees enforced by the database itself --------------------------------------
    op.execute(
        """
        CREATE FUNCTION append_only_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only (% rejected)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only_rows BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION append_only_reject_change()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_append_only_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION append_only_reject_change()"
        )

    op.execute(
        """
        CREATE FUNCTION app_child_jurisdiction_matches() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            reference uuid;
            parent_jurisdiction uuid;
        BEGIN
            EXECUTE format('SELECT ($1).%I', TG_ARGV[0]) INTO reference USING NEW;
            IF reference IS NULL THEN
                RETURN NEW;
            END IF;
            EXECUTE format('SELECT jurisdiction_id FROM %I WHERE id = $1', TG_ARGV[1])
                INTO parent_jurisdiction USING reference;
            IF parent_jurisdiction IS DISTINCT FROM NEW.jurisdiction_id THEN
                RAISE EXCEPTION '% must belong to the jurisdiction of the % it references',
                    TG_TABLE_NAME, TG_ARGV[1]
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table, column, parent in CHILD_LINKS:
        op.execute(
            f"CREATE TRIGGER {table}_{column}_same_jurisdiction BEFORE INSERT OR UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION app_child_jurisdiction_matches('{column}', '{parent}')"
        )

    op.execute(
        """
        CREATE FUNCTION candidate_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            last_status text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'unverified' THEN
                    RAISE EXCEPTION 'a candidate starts unverified'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.jurisdiction_id IS DISTINCT FROM OLD.jurisdiction_id
               OR NEW.source_type IS DISTINCT FROM OLD.source_type
               OR NEW.is_simulated IS DISTINCT FROM OLD.is_simulated
               OR NEW.observed_on IS DISTINCT FROM OLD.observed_on
               OR NEW.change_type IS DISTINCT FROM OLD.change_type
               OR NEW.estimated_floors IS DISTINCT FROM OLD.estimated_floors
               OR NEW.confidence IS DISTINCT FROM OLD.confidence
               OR NEW.model_name IS DISTINCT FROM OLD.model_name
               OR NEW.model_version IS DISTINCT FROM OLD.model_version
               OR NEW.imagery_refs IS DISTINCT FROM OLD.imagery_refs
               OR NEW.provenance_note IS DISTINCT FROM OLD.provenance_note
               OR NOT ST_OrderingEquals(NEW.footprint, OLD.footprint) THEN
                RAISE EXCEPTION 'candidate evidence is immutable'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status THEN
                SELECT resulting_status INTO last_status FROM candidate_review
                    WHERE candidate_id = NEW.id ORDER BY seq DESC LIMIT 1;
                IF last_status IS DISTINCT FROM NEW.status THEN
                    RAISE EXCEPTION 'candidate status must follow a recorded officer review'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                IF OLD.status = 'confirmed' AND EXISTS (
                    SELECT 1 FROM inspection_case
                    WHERE candidate_id = NEW.id AND status NOT IN ('resolved', 'dismissed')
                ) THEN
                    RAISE EXCEPTION 'a confirmed candidate with an open case cannot change'
                        USING ERRCODE = 'restrict_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER construction_change_candidate_guard "
        "BEFORE INSERT OR UPDATE ON construction_change_candidate "
        "FOR EACH ROW EXECUTE FUNCTION candidate_guard()"
    )

    op.execute(
        """
        CREATE FUNCTION inspection_case_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            candidate_status text;
            evaluation_candidate uuid;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                SELECT status INTO candidate_status FROM construction_change_candidate
                    WHERE id = NEW.candidate_id;
                IF candidate_status IS DISTINCT FROM 'confirmed' THEN
                    RAISE EXCEPTION 'only an officer-verified candidate can be released into a case'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                SELECT candidate_id INTO evaluation_candidate FROM candidate_evaluation
                    WHERE id = NEW.evaluation_id;
                IF evaluation_candidate IS DISTINCT FROM NEW.candidate_id THEN
                    RAISE EXCEPTION 'the evaluation must belong to the candidate'
                        USING ERRCODE = 'check_violation';
                END IF;
                IF NEW.status <> 'created' THEN
                    RAISE EXCEPTION 'a case starts in the created state'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status IN ('resolved', 'dismissed') THEN
                RAISE EXCEPTION 'a closed case is immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.candidate_id IS DISTINCT FROM OLD.candidate_id
               OR NEW.evaluation_id IS DISTINCT FROM OLD.evaluation_id
               OR NEW.jurisdiction_id IS DISTINCT FROM OLD.jurisdiction_id THEN
                RAISE EXCEPTION 'a case keeps its candidate and jurisdiction'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER inspection_case_guard BEFORE INSERT OR UPDATE ON inspection_case "
        "FOR EACH ROW EXECUTE FUNCTION inspection_case_guard()"
    )

    # --- Row-level security (ADR-0011) -----------------------------------------------------
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
            f"USING ({_PERMITTED}) WITH CHECK ({_PERMITTED})"
        )

    # --- Least-privilege grants ------------------------------------------------------------
    for table in TENANT_TABLES:
        app_privileges = "SELECT, INSERT, UPDATE" if table in MUTABLE_TABLES else "SELECT, INSERT"
        op.execute(_if_role("satrak_app", f"GRANT {app_privileges} ON {table} TO satrak_app"))
        admin_privileges = (
            "SELECT, INSERT, UPDATE, DELETE" if table in MUTABLE_TABLES else "SELECT, INSERT"
        )
        op.execute(_if_role("satrak_admin", f"GRANT {admin_privileges} ON {table} TO satrak_admin"))

    # --- Audit event types and the permission catalogue -------------------------------------
    op.execute("ALTER TABLE audit_event DROP CONSTRAINT ck_audit_event_event_type_valid")
    op.execute(
        "ALTER TABLE audit_event ADD CONSTRAINT ck_audit_event_event_type_valid "
        f"CHECK (event_type IN {_event_types(_BASE_EVENT_TYPES, _WORKFLOW_EVENT_TYPES)})"
    )
    permission = sa.table(
        "permission", sa.column("code", sa.String), sa.column("description", sa.Text)
    )
    for code, description in PERMISSIONS.items():
        op.execute(
            postgresql.insert(permission)
            .values(code=code, description=description)
            .on_conflict_do_nothing(index_elements=["code"])
        )


def downgrade() -> None:

    codes = ", ".join(f"'{c}'" for c in PERMISSIONS)
    op.execute(
        "DELETE FROM role_permission WHERE permission_id IN "
        f"(SELECT id FROM permission WHERE code IN ({codes}) AND code <> 'finding:verify')"
    )
    op.execute(
        f"DELETE FROM permission WHERE code IN ({codes}) AND NOT EXISTS ("
        "SELECT 1 FROM role_permission WHERE permission_id = permission.id)"
    )
    op.execute("ALTER TABLE audit_event DROP CONSTRAINT ck_audit_event_event_type_valid")
    # The audit log is append-only, so rows with the workflow event types cannot be removed.
    # NOT VALID keeps the narrower rule for every new row without re-checking (or rewriting)
    # the history that already exists.
    op.execute(
        "ALTER TABLE audit_event ADD CONSTRAINT ck_audit_event_event_type_valid "
        f"CHECK (event_type IN {_event_types(_BASE_EVENT_TYPES)}) NOT VALID"
    )
    op.drop_index(
        op.f("ix_case_state_transition_jurisdiction_id"), table_name="case_state_transition"
    )
    op.drop_index(op.f("ix_case_state_transition_case_id"), table_name="case_state_transition")
    op.drop_table("case_state_transition")
    op.drop_index(op.f("ix_case_finding_jurisdiction_id"), table_name="case_finding")
    op.drop_index(op.f("ix_case_finding_case_id"), table_name="case_finding")
    op.drop_table("case_finding")
    op.drop_index(op.f("ix_case_assignment_jurisdiction_id"), table_name="case_assignment")
    op.drop_index(op.f("ix_case_assignment_case_id"), table_name="case_assignment")
    op.drop_table("case_assignment")
    op.drop_index("ix_inspection_case_jurisdiction_status", table_name="inspection_case")
    op.drop_index(op.f("ix_inspection_case_jurisdiction_id"), table_name="inspection_case")
    op.drop_index("ix_inspection_case_assigned_to", table_name="inspection_case")
    op.drop_table("inspection_case")
    op.drop_index(op.f("ix_permit_history_permit_id"), table_name="permit_history")
    op.drop_index(op.f("ix_permit_history_jurisdiction_id"), table_name="permit_history")
    op.drop_table("permit_history")
    op.drop_index(
        op.f("ix_parcel_geometry_version_parcel_id"), table_name="parcel_geometry_version"
    )
    op.drop_index(
        op.f("ix_parcel_geometry_version_jurisdiction_id"), table_name="parcel_geometry_version"
    )
    op.drop_table("parcel_geometry_version")
    op.drop_index(op.f("ix_candidate_review_jurisdiction_id"), table_name="candidate_review")
    op.drop_index(op.f("ix_candidate_review_candidate_id"), table_name="candidate_review")
    op.drop_table("candidate_review")
    op.drop_index(
        op.f("ix_candidate_evaluation_jurisdiction_id"), table_name="candidate_evaluation"
    )
    op.drop_index(op.f("ix_candidate_evaluation_candidate_id"), table_name="candidate_evaluation")
    op.drop_table("candidate_evaluation")
    op.drop_index(op.f("ix_property_jurisdiction_id"), table_name="property")
    op.drop_table("property")
    op.drop_index(
        op.f("ix_construction_change_candidate_jurisdiction_id"),
        table_name="construction_change_candidate",
    )
    op.drop_index("ix_candidate_jurisdiction_status", table_name="construction_change_candidate")
    op.drop_table("construction_change_candidate")
    op.drop_index("ix_building_permit_parcel_id", table_name="building_permit")
    op.drop_index("ix_building_permit_jurisdiction_match", table_name="building_permit")
    op.drop_index(op.f("ix_building_permit_jurisdiction_id"), table_name="building_permit")
    op.drop_table("building_permit")
    op.drop_index(op.f("ix_parcel_jurisdiction_id"), table_name="parcel")
    op.drop_table("parcel")

    op.execute("DROP FUNCTION IF EXISTS inspection_case_guard()")
    op.execute("DROP FUNCTION IF EXISTS candidate_guard()")
    op.execute("DROP FUNCTION IF EXISTS app_child_jurisdiction_matches()")
    op.execute("DROP FUNCTION IF EXISTS append_only_reject_change()")
