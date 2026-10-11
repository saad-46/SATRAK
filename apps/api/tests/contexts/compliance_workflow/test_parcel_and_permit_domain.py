"""Parcel identity rules and building-permit validity/matching (pure domain)."""

from __future__ import annotations

from datetime import date

import pytest

from app.contexts.permit.domain import (
    MATCH_AREA_TOLERANCE_RATIO,
    BuildingPermit,
    MatchStatus,
    PermitStatus,
    SanctionedPlan,
    assess_parcel_match,
    validate_status_change,
)
from app.contexts.property.domain import (
    normalize_land_use,
    normalize_parcel_code,
    normalize_property_ref,
)
from app.shared.domain.errors import BusinessRuleViolation, ValueValidationError


@pytest.mark.parametrize(
    ("raw", "expected"), [(" ward-7/12a ", "WARD-7/12A"), ("p_1.2", "P_1.2"), ("9", "9")]
)
def test_parcel_codes_are_normalised(raw: str, expected: str) -> None:
    assert normalize_parcel_code(raw) == expected
    assert normalize_property_ref(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "-x", "a b", "a;b", "x" * 65, "ü1"])
def test_unsafe_or_empty_codes_are_rejected(raw: str) -> None:
    with pytest.raises(ValueValidationError):
        normalize_parcel_code(raw)
    with pytest.raises(ValueValidationError):
        normalize_property_ref(raw)


def test_land_use_is_a_closed_vocabulary() -> None:
    assert normalize_land_use(" Residential ") == "residential"
    with pytest.raises(ValueValidationError, match="land use"):
        normalize_land_use("casino")


def _permit(**overrides: object) -> BuildingPermit:
    values: dict[str, object] = {
        "permit_number": "BP-1",
        "status": PermitStatus.APPROVED,
        "valid_from": date(2024, 1, 1),
        "valid_to": date(2025, 12, 31),
        "plan": SanctionedPlan(floors=2, footprint_area_sq_m=120.0),
    }
    values.update(overrides)
    return BuildingPermit(**values)  # type: ignore[arg-type]


def test_permit_validity_is_judged_on_the_given_date() -> None:
    permit = _permit()
    assert permit.in_effect_on(date(2024, 1, 1))
    assert permit.in_effect_on(date(2025, 12, 31))
    assert permit.ineffective_reason(date(2023, 12, 31)) == "not valid until 2024-01-01"
    assert permit.ineffective_reason(date(2026, 1, 1)) == "expired on 2025-12-31"


def test_an_open_ended_permit_never_expires_but_status_still_matters() -> None:
    assert _permit(valid_to=None).in_effect_on(date(2099, 1, 1))
    for status in (PermitStatus.SUSPENDED, PermitStatus.REVOKED, PermitStatus.CLOSED):
        assert _permit(status=status).ineffective_reason(date(2024, 6, 1)) == (
            f"status is {status.value}"
        )


def test_permit_invariants() -> None:
    with pytest.raises(ValueValidationError, match="permit number"):
        _permit(permit_number=" ")
    with pytest.raises(ValueValidationError, match="valid_to"):
        _permit(valid_to=date(2023, 1, 1))
    for floors in (0, 201):
        with pytest.raises(ValueValidationError, match="floors"):
            SanctionedPlan(floors=floors, footprint_area_sq_m=10)
    with pytest.raises(ValueValidationError, match="footprint"):
        SanctionedPlan(floors=1, footprint_area_sq_m=0)
    with pytest.raises(ValueValidationError, match="built-up"):
        SanctionedPlan(floors=1, footprint_area_sq_m=5, built_up_area_sq_m=-1)


def test_permit_status_changes_follow_the_allowed_graph() -> None:
    validate_status_change(PermitStatus.APPROVED, PermitStatus.SUSPENDED)
    validate_status_change(PermitStatus.SUSPENDED, PermitStatus.APPROVED)
    validate_status_change(PermitStatus.APPROVED, PermitStatus.CLOSED)
    for final in (PermitStatus.REVOKED, PermitStatus.CLOSED):
        for target in PermitStatus:
            with pytest.raises(BusinessRuleViolation):
                validate_status_change(final, target)
    with pytest.raises(BusinessRuleViolation):
        validate_status_change(PermitStatus.APPROVED, PermitStatus.APPROVED)


def test_a_permit_for_an_unknown_parcel_is_unmatched_not_guessed() -> None:
    result = assess_parcel_match(
        parcel_found=False, parcel_area_sq_m=None, declared_plot_area_sq_m=100.0
    )
    assert result.status is MatchStatus.UNMATCHED


def test_matching_compares_declared_plot_area_with_the_register() -> None:
    ok = assess_parcel_match(
        parcel_found=True, parcel_area_sq_m=1000.0, declared_plot_area_sq_m=1000.0 * 1.05
    )
    assert ok.status is MatchStatus.MATCHED
    assert ok.detail["area_check"] == "performed"
    conflict = assess_parcel_match(
        parcel_found=True, parcel_area_sq_m=1000.0, declared_plot_area_sq_m=1500.0
    )
    assert conflict.status is MatchStatus.CONFLICT
    assert conflict.detail["tolerance_ratio"] == MATCH_AREA_TOLERANCE_RATIO
    skipped = assess_parcel_match(
        parcel_found=True, parcel_area_sq_m=1000.0, declared_plot_area_sq_m=None
    )
    assert skipped.status is MatchStatus.MATCHED
    assert skipped.detail == {"area_check": "not performed"}
