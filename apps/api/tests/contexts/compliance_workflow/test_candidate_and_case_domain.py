"""The verification gate (ADR-0014) and the case state machine (PRD FR-10.6)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.contexts.compliance.domain import (
    CandidateStatus,
    ReviewDecision,
    decide_review,
    require_verified,
)
from app.contexts.compliance.domain.candidate import CandidateSource, validate_provenance
from app.contexts.inspection.domain import (
    CaseSource,
    CaseStatus,
    compute_priority,
    validate_assignment_change,
    validate_finding,
    validate_transition,
)
from app.shared.domain.errors import (
    BusinessRuleViolation,
    InvalidStateTransition,
    ValueValidationError,
    VerificationRequiredError,
)

JUSTIFICATION = "Matches the Sentinel-2 change and the field note."


def _decide(
    current: CandidateStatus = CandidateStatus.UNVERIFIED,
    decision: ReviewDecision = ReviewDecision.CONFIRM,
    *,
    justification: str = JUSTIFICATION,
    evidence_complete: bool = True,
    evaluated: bool = True,
    has_open_case: bool = False,
) -> object:
    return decide_review(
        current=current,
        decision=decision,
        justification=justification,
        evidence_complete=evidence_complete,
        evaluated=evaluated,
        has_open_case=has_open_case,
    )


def test_an_unverified_candidate_cannot_be_released() -> None:
    for status in (
        CandidateStatus.UNVERIFIED,
        CandidateStatus.NEEDS_EVIDENCE,
        CandidateStatus.REJECTED,
    ):
        with pytest.raises(VerificationRequiredError) as raised:
            require_verified(status)
        assert raised.value.details == {"status": status.value}
    require_verified(CandidateStatus.CONFIRMED)


def test_confirming_needs_complete_provenance_and_an_evaluation() -> None:
    outcome = _decide()
    assert outcome.status is CandidateStatus.CONFIRMED  # type: ignore[attr-defined]
    assert outcome.is_reversal is False  # type: ignore[attr-defined]
    with pytest.raises(BusinessRuleViolation, match="provenance"):
        _decide(evidence_complete=False)
    with pytest.raises(BusinessRuleViolation, match="evaluated"):
        _decide(evaluated=False)


def test_rejecting_or_asking_for_evidence_needs_neither() -> None:
    for decision, status in (
        (ReviewDecision.REJECT, CandidateStatus.REJECTED),
        (ReviewDecision.REQUEST_EVIDENCE, CandidateStatus.NEEDS_EVIDENCE),
    ):
        outcome = _decide(decision=decision, evidence_complete=False, evaluated=False)
        assert outcome.status is status  # type: ignore[attr-defined]


@pytest.mark.parametrize("text", ["", "   ", "too short", "x" * 4001])
def test_a_real_justification_is_mandatory(text: str) -> None:
    with pytest.raises(ValueValidationError, match="justification"):
        _decide(justification=text)


def test_a_decision_must_change_the_state() -> None:
    with pytest.raises(InvalidStateTransition, match="already"):
        _decide(CandidateStatus.CONFIRMED, ReviewDecision.CONFIRM)


def test_corrections_are_reversals_and_blocked_by_an_open_case() -> None:
    reversed_ = _decide(CandidateStatus.CONFIRMED, ReviewDecision.REJECT)
    assert reversed_.status is CandidateStatus.REJECTED  # type: ignore[attr-defined]
    assert reversed_.is_reversal is True  # type: ignore[attr-defined]
    assert _decide(CandidateStatus.REJECTED, ReviewDecision.CONFIRM).is_reversal  # type: ignore[attr-defined]
    with pytest.raises(InvalidStateTransition, match="open case"):
        _decide(CandidateStatus.CONFIRMED, ReviewDecision.REJECT, has_open_case=True)
    assert not _decide(CandidateStatus.NEEDS_EVIDENCE, ReviewDecision.CONFIRM).is_reversal  # type: ignore[attr-defined]


def _refs(**overrides: Any) -> list[dict[str, Any]]:
    ref = {"source": "sentinel-2", "reference": "S2A_T43PGP_20260215", "acquired_on": "2026-02-15"}
    ref.update(overrides)
    return [ref]


def _prov(**overrides: Any) -> None:
    values: dict[str, Any] = {
        "source": CandidateSource.AI_DETECTION,
        "model_name": "change-net",
        "model_version": "1.2.0",
        "confidence": 0.87,
        "imagery_refs": _refs(),
        "observed_on": date(2026, 3, 1),
    }
    values.update(overrides)
    validate_provenance(**values)


def test_ai_candidates_must_name_model_version_and_confidence() -> None:
    _prov()
    for bad in ({"model_name": None}, {"model_version": ""}, {"confidence": None}):
        with pytest.raises(ValueValidationError):
            _prov(**bad)
    _prov(
        source=CandidateSource.MANUAL_REPORT, model_name=None, model_version=None, confidence=None
    )


def test_provenance_rejects_bad_confidence_and_imagery() -> None:
    for confidence in (-0.01, 1.01):
        with pytest.raises(ValueValidationError, match="confidence"):
            _prov(confidence=confidence)
    for bad in (
        _refs(source=""),
        _refs(reference=""),
        _refs(acquired_on=None),
        _refs(acquired_on="15/02/2026"),
        _refs(acquired_on="2026-03-02"),  # after the observation date
    ):
        with pytest.raises(ValueValidationError) as raised:
            _prov(imagery_refs=bad)
        assert raised.value.field == "imagery_refs"


def test_the_case_state_machine_allows_only_the_defined_path() -> None:
    path = [
        (CaseStatus.CREATED, CaseStatus.ASSIGNED),
        (CaseStatus.ASSIGNED, CaseStatus.UNDER_INVESTIGATION),
        (CaseStatus.UNDER_INVESTIGATION, CaseStatus.NOTICE_ISSUED),
        (CaseStatus.NOTICE_ISSUED, CaseStatus.RESOLVED),
    ]
    for current, target in path:
        validate_transition(current, target, has_assignee=True, finding_count=1)
    for current in (CaseStatus.CREATED, CaseStatus.ASSIGNED, CaseStatus.UNDER_INVESTIGATION):
        validate_transition(current, CaseStatus.DISMISSED, has_assignee=False, finding_count=0)


def test_illegal_case_transitions_are_refused() -> None:
    illegal = [
        (CaseStatus.CREATED, CaseStatus.UNDER_INVESTIGATION),
        (CaseStatus.CREATED, CaseStatus.NOTICE_ISSUED),
        (CaseStatus.ASSIGNED, CaseStatus.NOTICE_ISSUED),
        (CaseStatus.ASSIGNED, CaseStatus.RESOLVED),
        (CaseStatus.NOTICE_ISSUED, CaseStatus.UNDER_INVESTIGATION),
        (CaseStatus.RESOLVED, CaseStatus.DISMISSED),
        (CaseStatus.DISMISSED, CaseStatus.CREATED),
    ]
    for current, target in illegal:
        with pytest.raises(InvalidStateTransition):
            validate_transition(current, target, has_assignee=True, finding_count=5)


def test_transition_guards_need_an_assignee_and_a_finding() -> None:
    with pytest.raises(InvalidStateTransition, match="assigned first"):
        validate_transition(
            CaseStatus.ASSIGNED, CaseStatus.UNDER_INVESTIGATION, has_assignee=False, finding_count=0
        )
    with pytest.raises(InvalidStateTransition, match="finding"):
        validate_transition(
            CaseStatus.UNDER_INVESTIGATION,
            CaseStatus.NOTICE_ISSUED,
            has_assignee=True,
            finding_count=0,
        )


def test_assignment_rules() -> None:
    assert validate_assignment_change(CaseStatus.CREATED) is CaseStatus.ASSIGNED
    assert validate_assignment_change(CaseStatus.UNDER_INVESTIGATION) is (
        CaseStatus.UNDER_INVESTIGATION
    )
    for closed in (CaseStatus.RESOLVED, CaseStatus.DISMISSED):
        with pytest.raises(InvalidStateTransition, match="reassigned"):
            validate_assignment_change(closed)


def test_priority_is_deterministic_and_bounded() -> None:
    assert compute_priority("high", CaseSource.AI_DETECTION) == 70
    assert compute_priority("high", CaseSource.MANUAL_REPORT) == 75
    assert compute_priority("none", CaseSource.IMPORTED) == 10
    with pytest.raises(ValueValidationError):
        compute_priority("urgent", CaseSource.AI_DETECTION)


def _evidence(**overrides: Any) -> dict[str, Any]:
    item = {
        "kind": "photo",
        "reference": "evidence://site/IMG_0001.jpg",
        "sha256": "a" * 64,
        "captured_at": datetime(2026, 3, 2, 9, 30, tzinfo=UTC),
    }
    item.update(overrides)
    return item


def test_findings_are_normalised() -> None:
    notes, measurements, evidence = validate_finding(
        "  Two storeys visible.  ",
        {"floors": 2, "note": "north wall"},
        [_evidence(sha256="A" * 64)],
    )
    assert notes == "Two storeys visible."
    assert measurements == {"floors": 2, "note": "north wall"}
    assert evidence[0].sha256 == "a" * 64
    assert evidence[0].to_dict()["captured_at"].startswith("2026-03-02T09:30")


@pytest.mark.parametrize(
    ("notes", "measurements", "evidence"),
    [
        ("", {}, []),
        ("x" * 4001, {}, []),
        ("ok", {f"m{i}": 1 for i in range(21)}, []),
        ("ok", {"": 1}, []),
        ("ok", {"a": True}, []),
        ("ok", {"a": [1]}, []),
        ("ok", {"a": "x" * 201}, []),
        ("ok", {}, [_evidence()] * 21),
        ("ok", {}, [_evidence(kind="video")]),
        ("ok", {}, [_evidence(reference=" ")]),
        ("ok", {}, [_evidence(sha256="xyz")]),
        ("ok", {}, [_evidence(captured_at=datetime(2026, 3, 2))]),
    ],
)
def test_bad_findings_are_rejected(
    notes: str, measurements: dict[str, Any], evidence: list[dict[str, Any]]
) -> None:
    with pytest.raises(ValueValidationError):
        validate_finding(notes, measurements, evidence)
