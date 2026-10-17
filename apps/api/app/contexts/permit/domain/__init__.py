"""Permit domain: building-permit validity and permit-to-parcel matching."""

from app.contexts.permit.domain.permit import (
    MATCH_AREA_TOLERANCE_RATIO,
    BuildingPermit,
    MatchAssessment,
    MatchStatus,
    PermitStatus,
    SanctionedPlan,
    assess_parcel_match,
    validate_status_change,
)

__all__ = [
    "MATCH_AREA_TOLERANCE_RATIO",
    "BuildingPermit",
    "MatchAssessment",
    "MatchStatus",
    "PermitStatus",
    "SanctionedPlan",
    "assess_parcel_match",
    "validate_status_change",
]
