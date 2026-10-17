"""Deterministic evaluation of a construction-change candidate against permit records.

Every outcome carries a machine-readable explanation (which rule, which measured value, which
threshold; PRD FR-6.3) and the effective date used (FR-6.2). The result is a *discrepancy
classification for human review*, never an enforcement decision (FR-6.7, ADR-0014): nothing
here can issue a notice or declare a property illegal.

The tolerances are explicit parameters recorded with every evaluation. Their defaults are
engineering placeholders, not approved municipal rules; rules-as-data with Legal/Compliance
sign-off (FR-6.1, FR-6.5) is a later module, and each result says so.

Limitation: the candidate's footprint is compared with the permit's *sanctioned footprint* as a
whole, i.e. the candidate is taken to describe the structure, not only an increment to it.
Existing-building data (Module 3 building detection) is needed to separate the two.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Final

from app.shared.domain.errors import ValueValidationError

RULES_VERSION: Final = "2026-10-11.placeholder"
CAVEAT: Final = (
    "Discrepancy classification for officer review. Thresholds are placeholder defaults pending"
    " approved municipal rules (PRD FR-6.1, FR-6.5). Not an enforcement decision."
)


class RuleCode(StrEnum):
    PARCEL_RESOLVED = "parcel_resolved"
    WITHIN_PARCEL_BOUNDARY = "within_parcel_boundary"
    PERMIT_EXISTS = "permit_exists"
    PERMIT_EFFECTIVE = "permit_effective"
    FOOTPRINT_WITHIN_SANCTIONED = "footprint_within_sanctioned"
    FLOORS_WITHIN_SANCTIONED = "floors_within_sanctioned"
    PERMIT_RECORDS_RESOLVED = "permit_records_resolved"


class RuleOutcome(StrEnum):
    PASS = "pass"  # nosec B105
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    INDETERMINATE = "indeterminate"


class Classification(StrEnum):
    PARCEL_UNRESOLVED = "parcel_unresolved"
    UNPERMITTED_CONSTRUCTION = "unpermitted_construction"
    PERMIT_NOT_IN_EFFECT = "permit_not_in_effect"
    EXCEEDS_SANCTIONED_PLAN = "exceeds_sanctioned_plan"
    BOUNDARY_ENCROACHMENT = "boundary_encroachment"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    NO_DISCREPANCY_FOUND = "no_discrepancy_found"


class Severity(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_SEVERITY_RANK: Final = {Severity.NONE: 0, Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 3}
# Severity of a failed rule. Reported severity is the highest among the failed rules (LOW when
# the evaluation can only say a human must look; NONE when nothing failed).
_RULE_SEVERITY: Final = {
    RuleCode.PARCEL_RESOLVED: Severity.LOW,
    RuleCode.PERMIT_EXISTS: Severity.HIGH,
    RuleCode.PERMIT_EFFECTIVE: Severity.HIGH,
    RuleCode.FOOTPRINT_WITHIN_SANCTIONED: Severity.MEDIUM,
    RuleCode.FLOORS_WITHIN_SANCTIONED: Severity.MEDIUM,
    RuleCode.WITHIN_PARCEL_BOUNDARY: Severity.MEDIUM,
}


@dataclass(frozen=True, slots=True)
class EvaluationParameters:
    """Tolerances; recorded with every evaluation so a result can be reproduced and audited."""

    footprint_tolerance_ratio: float = 0.10
    boundary_tolerance_ratio: float = 0.05

    def __post_init__(self) -> None:
        for name in ("footprint_tolerance_ratio", "boundary_tolerance_ratio"):
            if not 0.0 <= getattr(self, name) < 1.0:
                raise ValueValidationError(f"{name} must be in [0, 1)", field=name)

    def to_dict(self) -> dict[str, float]:
        return {
            "footprint_tolerance_ratio": self.footprint_tolerance_ratio,
            "boundary_tolerance_ratio": self.boundary_tolerance_ratio,
        }


@dataclass(frozen=True, slots=True)
class PermitFacts:
    """A permit record matched to the candidate's parcel, as of the observation date."""

    permit_id: str
    permit_number: str
    status: str
    ineffective_reason: str | None  # None means in effect on the observation date
    sanctioned_floors: int
    sanctioned_footprint_area_sq_m: float

    @property
    def in_effect(self) -> bool:
        return self.ineffective_reason is None


@dataclass(frozen=True, slots=True)
class EvaluationFacts:
    observed_on: date
    candidate_area_sq_m: float
    estimated_floors: int | None
    parcel_id: str | None
    parcel_code: str | None
    outside_parcel_area_sq_m: float
    permits: tuple[PermitFacts, ...] = ()
    unresolved_permit_count: int = 0

    def __post_init__(self) -> None:
        if self.candidate_area_sq_m <= 0:
            raise ValueValidationError("candidate area must be positive", field="footprint")
        if self.outside_parcel_area_sq_m < 0:
            raise ValueValidationError("outside area must not be negative", field="footprint")


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule: RuleCode
    outcome: RuleOutcome
    explanation: str
    measured: float | None = None
    threshold: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule.value,
            "outcome": self.outcome.value,
            "measured": self.measured,
            "threshold": self.threshold,
            "explanation": self.explanation,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    classification: Classification
    severity: Severity
    results: tuple[RuleResult, ...]
    effective_date: date
    parameters: EvaluationParameters

    @property
    def failed_rules(self) -> tuple[str, ...]:
        return tuple(r.rule.value for r in self.results if r.outcome is RuleOutcome.FAIL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "severity": self.severity.value,
            "effective_date": self.effective_date.isoformat(),
            "rules_version": RULES_VERSION,
            "parameters": self.parameters.to_dict(),
            "results": [r.to_dict() for r in self.results],
            "caveat": CAVEAT,
        }


def _na(rule: RuleCode, why: str) -> RuleResult:
    return RuleResult(rule, RuleOutcome.NOT_APPLICABLE, why)


def _classify(failed: set[RuleCode], any_indeterminate: bool) -> Classification:
    if RuleCode.PARCEL_RESOLVED in failed:
        return Classification.PARCEL_UNRESOLVED
    if RuleCode.PERMIT_EXISTS in failed:
        return Classification.UNPERMITTED_CONSTRUCTION
    if RuleCode.PERMIT_EFFECTIVE in failed:
        return Classification.PERMIT_NOT_IN_EFFECT
    if failed & {RuleCode.FOOTPRINT_WITHIN_SANCTIONED, RuleCode.FLOORS_WITHIN_SANCTIONED}:
        return Classification.EXCEEDS_SANCTIONED_PLAN
    if RuleCode.WITHIN_PARCEL_BOUNDARY in failed:
        return Classification.BOUNDARY_ENCROACHMENT
    if any_indeterminate:
        return Classification.NEEDS_MANUAL_REVIEW
    return Classification.NO_DISCREPANCY_FOUND


def evaluate(
    facts: EvaluationFacts, params: EvaluationParameters | None = None
) -> EvaluationResult:
    """Evaluate ``facts`` and explain every rule; pure and deterministic."""
    params = params or EvaluationParameters()
    results: list[RuleResult] = []

    parcel_ok = facts.parcel_id is not None
    results.append(
        RuleResult(
            RuleCode.PARCEL_RESOLVED,
            RuleOutcome.PASS if parcel_ok else RuleOutcome.FAIL,
            f"candidate lies on parcel {facts.parcel_code}"
            if parcel_ok
            else "candidate does not overlap any registered parcel in this jurisdiction",
            detail={"parcel_id": facts.parcel_id, "parcel_code": facts.parcel_code},
        )
    )
    if not parcel_ok:
        for rule in list(RuleCode)[1:]:
            results.append(_na(rule, "no parcel was resolved"))
        return _result(facts, params, results)

    outside_ratio = facts.outside_parcel_area_sq_m / facts.candidate_area_sq_m
    boundary_fail = outside_ratio > params.boundary_tolerance_ratio
    results.append(
        RuleResult(
            RuleCode.WITHIN_PARCEL_BOUNDARY,
            RuleOutcome.FAIL if boundary_fail else RuleOutcome.PASS,
            f"{outside_ratio:.1%} of the footprint lies outside the parcel"
            f" (tolerance {params.boundary_tolerance_ratio:.1%})",
            measured=round(outside_ratio, 6),
            threshold=params.boundary_tolerance_ratio,
            detail={"outside_area_sq_m": round(facts.outside_parcel_area_sq_m, 2)},
        )
    )

    has_permits = bool(facts.permits)
    results.append(
        RuleResult(
            RuleCode.PERMIT_EXISTS,
            RuleOutcome.PASS if has_permits else RuleOutcome.FAIL,
            f"{len(facts.permits)} permit record(s) matched to the parcel"
            if has_permits
            else "no permit record is matched to this parcel",
            measured=float(len(facts.permits)),
            threshold=1.0,
        )
    )
    effective = [p for p in facts.permits if p.in_effect]
    if not has_permits:
        results.append(_na(RuleCode.PERMIT_EFFECTIVE, "no permit record"))
        results.append(_na(RuleCode.FOOTPRINT_WITHIN_SANCTIONED, "no permit record"))
        results.append(_na(RuleCode.FLOORS_WITHIN_SANCTIONED, "no permit record"))
    else:
        results.append(
            RuleResult(
                RuleCode.PERMIT_EFFECTIVE,
                RuleOutcome.PASS if effective else RuleOutcome.FAIL,
                f"{len(effective)} permit(s) in effect on {facts.observed_on.isoformat()}"
                if effective
                else f"no permit was in effect on {facts.observed_on.isoformat()}",
                measured=float(len(effective)),
                threshold=1.0,
                detail={
                    "permits": [
                        {
                            "permit_number": p.permit_number,
                            "status": p.status,
                            "in_effect": p.in_effect,
                            "reason": p.ineffective_reason,
                        }
                        for p in facts.permits
                    ]
                },
            )
        )
        if not effective:
            results.append(_na(RuleCode.FOOTPRINT_WITHIN_SANCTIONED, "no permit in effect"))
            results.append(_na(RuleCode.FLOORS_WITHIN_SANCTIONED, "no permit in effect"))
        else:
            allowed = max(p.sanctioned_footprint_area_sq_m for p in effective)
            limit = allowed * (1.0 + params.footprint_tolerance_ratio)
            results.append(
                RuleResult(
                    RuleCode.FOOTPRINT_WITHIN_SANCTIONED,
                    RuleOutcome.FAIL if facts.candidate_area_sq_m > limit else RuleOutcome.PASS,
                    f"footprint {facts.candidate_area_sq_m:.1f} m2 against sanctioned"
                    f" {allowed:.1f} m2 (+{params.footprint_tolerance_ratio:.0%} tolerance)",
                    measured=round(facts.candidate_area_sq_m, 2),
                    threshold=round(limit, 2),
                    detail={"sanctioned_footprint_area_sq_m": round(allowed, 2)},
                )
            )
            if facts.estimated_floors is None:
                results.append(
                    RuleResult(
                        RuleCode.FLOORS_WITHIN_SANCTIONED,
                        RuleOutcome.INDETERMINATE,
                        "the number of floors was not estimated",
                    )
                )
            else:
                floors_allowed = max(p.sanctioned_floors for p in effective)
                results.append(
                    RuleResult(
                        RuleCode.FLOORS_WITHIN_SANCTIONED,
                        RuleOutcome.FAIL
                        if facts.estimated_floors > floors_allowed
                        else RuleOutcome.PASS,
                        f"{facts.estimated_floors} floor(s) estimated against"
                        f" {floors_allowed} sanctioned",
                        measured=float(facts.estimated_floors),
                        threshold=float(floors_allowed),
                    )
                )

    unresolved = facts.unresolved_permit_count
    results.append(
        RuleResult(
            RuleCode.PERMIT_RECORDS_RESOLVED,
            RuleOutcome.PASS if unresolved == 0 else RuleOutcome.INDETERMINATE,
            "all permit records on the parcel are matched"
            if unresolved == 0
            else f"{unresolved} permit record(s) on this parcel are in conflict and unresolved",
            measured=float(unresolved),
            threshold=0.0,
        )
    )
    return _result(facts, params, results)


def _result(
    facts: EvaluationFacts, params: EvaluationParameters, results: list[RuleResult]
) -> EvaluationResult:
    failed = {r.rule for r in results if r.outcome is RuleOutcome.FAIL}
    indeterminate = any(r.outcome is RuleOutcome.INDETERMINATE for r in results)
    classification = _classify(failed, indeterminate)
    severity = max(
        (_RULE_SEVERITY[rule] for rule in failed),
        key=_SEVERITY_RANK.__getitem__,
        default=Severity.LOW if indeterminate else Severity.NONE,
    )
    return EvaluationResult(
        classification=classification,
        severity=severity,
        results=tuple(results),
        effective_date=facts.observed_on,
        parameters=params,
    )
