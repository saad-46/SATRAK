"""Building-permit records, effective-date validity and permit-to-parcel matching.

Rules follow PRD FR-6.2 (a permit is judged by the date the construction was *observed*, not by
the date it is evaluated) and FR-5.3 (conflicting source data is surfaced, never silently
resolved: a permit whose declared plot area disagrees with the parcel it points at is marked
``conflict`` and left for a human to resolve).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final

from app.shared.domain.errors import InvalidStateTransition, ValueValidationError

# Placeholder tolerance for "declared plot area agrees with the surveyed parcel". It is a
# default, recorded with every assessment, pending an approved municipal rule (FR-6.1/6.5).
MATCH_AREA_TOLERANCE_RATIO: Final = 0.10
MAX_FLOORS: Final = 200


class PermitStatus(StrEnum):
    APPROVED = "approved"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    CLOSED = "closed"  # completion certified; no longer authorises further construction


class MatchStatus(StrEnum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    CONFLICT = "conflict"


# Allowed administrative changes. ``revoked`` and ``closed`` are final.
_STATUS_CHANGES: Final = {
    PermitStatus.APPROVED: {PermitStatus.SUSPENDED, PermitStatus.REVOKED, PermitStatus.CLOSED},
    PermitStatus.SUSPENDED: {PermitStatus.APPROVED, PermitStatus.REVOKED},
    PermitStatus.REVOKED: set(),
    PermitStatus.CLOSED: set(),
}


def validate_status_change(current: PermitStatus, target: PermitStatus) -> None:
    if target not in _STATUS_CHANGES[current]:
        raise InvalidStateTransition(
            f"a {current.value} permit cannot become {target.value}",
            details={"from": current.value, "to": target.value},
        )


@dataclass(frozen=True, slots=True)
class SanctionedPlan:
    """The plan parameters a permit authorises (PRD FR-5.1)."""

    floors: int
    footprint_area_sq_m: float
    built_up_area_sq_m: float | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.floors <= MAX_FLOORS:
            raise ValueValidationError(
                f"sanctioned floors must be between 1 and {MAX_FLOORS}", field="sanctioned_floors"
            )
        if self.footprint_area_sq_m <= 0:
            raise ValueValidationError(
                "sanctioned footprint area must be positive", field="sanctioned_footprint_area_sq_m"
            )
        if self.built_up_area_sq_m is not None and self.built_up_area_sq_m <= 0:
            raise ValueValidationError(
                "sanctioned built-up area must be positive", field="sanctioned_built_up_area_sq_m"
            )


@dataclass(frozen=True, slots=True)
class BuildingPermit:
    permit_number: str
    status: PermitStatus
    valid_from: date
    valid_to: date | None
    plan: SanctionedPlan

    def __post_init__(self) -> None:
        if not self.permit_number.strip():
            raise ValueValidationError("permit number is required", field="permit_number")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueValidationError("valid_to must not precede valid_from", field="valid_to")

    def ineffective_reason(self, on: date) -> str | None:
        """Why the permit did not authorise construction on ``on`` (``None`` if it did)."""
        if self.status is not PermitStatus.APPROVED:
            return f"status is {self.status.value}"
        if on < self.valid_from:
            return f"not valid until {self.valid_from.isoformat()}"
        if self.valid_to is not None and on > self.valid_to:
            return f"expired on {self.valid_to.isoformat()}"
        return None

    def in_effect_on(self, on: date) -> bool:
        return self.ineffective_reason(on) is None


@dataclass(frozen=True, slots=True)
class MatchAssessment:
    status: MatchStatus
    detail: dict[str, object]


def assess_parcel_match(
    *,
    parcel_found: bool,
    parcel_area_sq_m: float | None,
    declared_plot_area_sq_m: float | None,
    tolerance_ratio: float = MATCH_AREA_TOLERANCE_RATIO,
) -> MatchAssessment:
    """Decide how a permit's parcel reference compares with the parcel register."""
    if not parcel_found:
        return MatchAssessment(MatchStatus.UNMATCHED, {"reason": "parcel code not in register"})
    if declared_plot_area_sq_m is None or parcel_area_sq_m is None or parcel_area_sq_m <= 0:
        return MatchAssessment(MatchStatus.MATCHED, {"area_check": "not performed"})
    ratio = abs(declared_plot_area_sq_m - parcel_area_sq_m) / parcel_area_sq_m
    detail: dict[str, object] = {
        "area_check": "performed",
        "declared_plot_area_sq_m": round(declared_plot_area_sq_m, 2),
        "parcel_area_sq_m": round(parcel_area_sq_m, 2),
        "difference_ratio": round(ratio, 4),
        "tolerance_ratio": tolerance_ratio,
    }
    if ratio > tolerance_ratio:
        return MatchAssessment(MatchStatus.CONFLICT, detail)
    return MatchAssessment(MatchStatus.MATCHED, detail)
