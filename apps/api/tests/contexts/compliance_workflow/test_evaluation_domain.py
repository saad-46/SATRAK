"""Deterministic permit/footprint evaluation: every outcome is explained (FR-6.2, FR-6.3)."""

from __future__ import annotations

from datetime import date

import pytest

from app.contexts.compliance.domain import (
    EvaluationFacts,
    EvaluationParameters,
    PermitFacts,
    RuleCode,
    RuleOutcome,
    evaluate,
)
from app.contexts.compliance.domain.evaluation import CAVEAT, Classification, Severity
from app.shared.domain.errors import ValueValidationError

OBSERVED = date(2026, 3, 1)


def _permit(**overrides: object) -> PermitFacts:
    values: dict[str, object] = {
        "permit_id": "p1",
        "permit_number": "BP-1",
        "status": "approved",
        "ineffective_reason": None,
        "sanctioned_floors": 2,
        "sanctioned_footprint_area_sq_m": 100.0,
    }
    values.update(overrides)
    return PermitFacts(**values)  # type: ignore[arg-type]


def _facts(**overrides: object) -> EvaluationFacts:
    values: dict[str, object] = {
        "observed_on": OBSERVED,
        "candidate_area_sq_m": 100.0,
        "estimated_floors": 2,
        "parcel_id": "parcel-1",
        "parcel_code": "W7/12",
        "outside_parcel_area_sq_m": 0.0,
        "permits": (_permit(),),
    }
    values.update(overrides)
    return EvaluationFacts(**values)  # type: ignore[arg-type]


def _outcome(result: object, rule: RuleCode) -> RuleOutcome:
    return next(r.outcome for r in result.results if r.rule is rule)  # type: ignore[attr-defined]


def test_a_compliant_candidate_has_no_discrepancy() -> None:
    result = evaluate(_facts())
    assert result.classification is Classification.NO_DISCREPANCY_FOUND
    assert result.severity is Severity.NONE
    assert result.failed_rules == ()
    assert all(r.explanation for r in result.results)
    assert result.to_dict()["caveat"] == CAVEAT


def test_no_parcel_means_the_other_rules_are_not_applicable() -> None:
    result = evaluate(_facts(parcel_id=None, parcel_code=None, permits=()))
    assert result.classification is Classification.PARCEL_UNRESOLVED
    assert result.severity is Severity.LOW
    assert _outcome(result, RuleCode.PARCEL_RESOLVED) is RuleOutcome.FAIL
    others = [r for r in result.results if r.rule is not RuleCode.PARCEL_RESOLVED]
    assert len(others) == len(RuleCode) - 1
    assert all(r.outcome is RuleOutcome.NOT_APPLICABLE for r in others)


def test_no_permit_on_the_parcel_is_unpermitted_construction() -> None:
    result = evaluate(_facts(permits=()))
    assert result.classification is Classification.UNPERMITTED_CONSTRUCTION
    assert result.severity is Severity.HIGH
    assert _outcome(result, RuleCode.PERMIT_EXISTS) is RuleOutcome.FAIL
    assert _outcome(result, RuleCode.FOOTPRINT_WITHIN_SANCTIONED) is RuleOutcome.NOT_APPLICABLE


def test_a_permit_that_was_not_in_effect_on_the_observation_date_does_not_count() -> None:
    expired = _permit(ineffective_reason="expired on 2025-12-31")
    result = evaluate(_facts(permits=(expired,)))
    assert result.classification is Classification.PERMIT_NOT_IN_EFFECT
    assert result.severity is Severity.HIGH
    detail = next(r for r in result.results if r.rule is RuleCode.PERMIT_EFFECTIVE).detail
    assert detail["permits"][0]["reason"] == "expired on 2025-12-31"  # type: ignore[index]
    assert result.effective_date == OBSERVED


def test_footprint_tolerance_boundary() -> None:
    at_limit = evaluate(_facts(candidate_area_sq_m=110.0))  # 100 m2 + 10 %
    assert _outcome(at_limit, RuleCode.FOOTPRINT_WITHIN_SANCTIONED) is RuleOutcome.PASS
    over = evaluate(_facts(candidate_area_sq_m=110.01))
    assert _outcome(over, RuleCode.FOOTPRINT_WITHIN_SANCTIONED) is RuleOutcome.FAIL
    assert over.classification is Classification.EXCEEDS_SANCTIONED_PLAN
    assert over.severity is Severity.MEDIUM
    explained = next(r for r in over.results if r.rule is RuleCode.FOOTPRINT_WITHIN_SANCTIONED)
    assert explained.measured == 110.01
    assert explained.threshold == 110.0


def test_the_most_permissive_effective_permit_sets_the_limit() -> None:
    small = _permit(permit_id="a", sanctioned_footprint_area_sq_m=50.0, sanctioned_floors=1)
    large = _permit(permit_id="b", sanctioned_footprint_area_sq_m=200.0, sanctioned_floors=4)
    result = evaluate(_facts(candidate_area_sq_m=190.0, estimated_floors=4, permits=(small, large)))
    assert result.classification is Classification.NO_DISCREPANCY_FOUND


def test_floors_above_the_sanction_fail_and_unknown_floors_need_a_human() -> None:
    result = evaluate(_facts(estimated_floors=3))
    assert _outcome(result, RuleCode.FLOORS_WITHIN_SANCTIONED) is RuleOutcome.FAIL
    assert result.classification is Classification.EXCEEDS_SANCTIONED_PLAN
    unknown = evaluate(_facts(estimated_floors=None))
    assert _outcome(unknown, RuleCode.FLOORS_WITHIN_SANCTIONED) is RuleOutcome.INDETERMINATE
    assert unknown.classification is Classification.NEEDS_MANUAL_REVIEW
    assert unknown.severity is Severity.LOW


def test_boundary_encroachment_uses_the_outside_share() -> None:
    result = evaluate(_facts(outside_parcel_area_sq_m=5.0))  # exactly 5 % -> tolerated
    assert _outcome(result, RuleCode.WITHIN_PARCEL_BOUNDARY) is RuleOutcome.PASS
    result = evaluate(_facts(outside_parcel_area_sq_m=5.5))
    assert result.classification is Classification.BOUNDARY_ENCROACHMENT
    assert result.severity is Severity.MEDIUM


def test_unresolved_permit_conflicts_are_surfaced_not_resolved() -> None:
    result = evaluate(_facts(unresolved_permit_count=2))
    assert _outcome(result, RuleCode.PERMIT_RECORDS_RESOLVED) is RuleOutcome.INDETERMINATE
    assert result.classification is Classification.NEEDS_MANUAL_REVIEW


def test_the_worst_failure_decides_severity_and_classification() -> None:
    result = evaluate(_facts(permits=(), outside_parcel_area_sq_m=50.0))
    assert result.classification is Classification.UNPERMITTED_CONSTRUCTION
    assert set(result.failed_rules) == {"permit_exists", "within_parcel_boundary"}
    assert result.severity is Severity.HIGH


def test_parameters_are_recorded_and_validated() -> None:
    result = evaluate(
        _facts(candidate_area_sq_m=115.0), EvaluationParameters(footprint_tolerance_ratio=0.20)
    )
    assert result.classification is Classification.NO_DISCREPANCY_FOUND
    assert result.to_dict()["parameters"] == {
        "footprint_tolerance_ratio": 0.2,
        "boundary_tolerance_ratio": 0.05,
    }
    for bad in (-0.1, 1.0):
        with pytest.raises(ValueValidationError):
            EvaluationParameters(footprint_tolerance_ratio=bad)
        with pytest.raises(ValueValidationError):
            EvaluationParameters(boundary_tolerance_ratio=bad)


def test_facts_reject_impossible_measurements() -> None:
    with pytest.raises(ValueValidationError):
        _facts(candidate_area_sq_m=0.0)
    with pytest.raises(ValueValidationError):
        _facts(outside_parcel_area_sq_m=-1.0)


def test_evaluation_is_deterministic() -> None:
    assert (
        evaluate(_facts(estimated_floors=3)).to_dict()
        == evaluate(_facts(estimated_floors=3)).to_dict()
    )
