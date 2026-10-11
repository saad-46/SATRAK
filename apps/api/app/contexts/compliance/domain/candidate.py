"""Construction-change candidates and the officer-verification gate (ADR-0014).

A candidate is a *claim* that something was built or changed. Whatever produced it (an AI
detection, a manual report, an import) it starts ``unverified`` and may be shown only to
authorised reviewers. Only an officer's recorded ``confirm`` decision makes it eligible to
enter an enforcement-related workflow (a case). Decisions are appended to a history; a
correction is a new decision, never an edit (ADR-0014 §6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Final

from app.shared.domain.errors import (
    BusinessRuleViolation,
    InvalidStateTransition,
    ValueValidationError,
    VerificationRequiredError,
)

MIN_JUSTIFICATION_LENGTH: Final = 10
MAX_JUSTIFICATION_LENGTH: Final = 4_000


class CandidateSource(StrEnum):
    AI_DETECTION = "ai_detection"
    MANUAL_REPORT = "manual_report"
    IMPORTED = "imported"


class CandidateStatus(StrEnum):
    UNVERIFIED = "unverified"
    NEEDS_EVIDENCE = "needs_evidence"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"
    REQUEST_EVIDENCE = "request_evidence"


_OUTCOME: Final = {
    ReviewDecision.CONFIRM: CandidateStatus.CONFIRMED,
    ReviewDecision.REJECT: CandidateStatus.REJECTED,
    ReviewDecision.REQUEST_EVIDENCE: CandidateStatus.NEEDS_EVIDENCE,
}


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    status: CandidateStatus
    is_reversal: bool


def validate_provenance(
    *,
    source: CandidateSource,
    model_name: str | None,
    model_version: str | None,
    confidence: float | None,
    imagery_refs: list[dict[str, Any]],
    observed_on: date,
) -> None:
    """Structural provenance checks done when a candidate is registered (ADR-0014 §2)."""
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        raise ValueValidationError("confidence must be between 0 and 1", field="confidence")
    if source is CandidateSource.AI_DETECTION and not (model_name and model_version):
        raise ValueValidationError(
            "an AI detection must name the model and its version", field="model_version"
        )
    if source is CandidateSource.AI_DETECTION and confidence is None:
        raise ValueValidationError("an AI detection must carry a confidence", field="confidence")
    for ref in imagery_refs:
        acquired = ref.get("acquired_on")
        if not ref.get("source") or not ref.get("reference") or not isinstance(acquired, str):
            raise ValueValidationError(
                "each imagery reference needs source, reference and acquired_on",
                field="imagery_refs",
            )
        try:
            acquired_date = date.fromisoformat(acquired)
        except ValueError as exc:
            raise ValueValidationError(
                "acquired_on must be an ISO date", field="imagery_refs"
            ) from exc
        if acquired_date > observed_on:
            raise ValueValidationError(
                "imagery cannot be acquired after the observation date", field="imagery_refs"
            )


def decide_review(
    *,
    current: CandidateStatus,
    decision: ReviewDecision,
    justification: str,
    evidence_complete: bool,
    evaluated: bool,
    has_open_case: bool,
) -> ReviewOutcome:
    """Apply the verification rules and return the resulting status.

    ``evidence_complete`` is the provenance requirement (imagery with acquisition dates, plus
    model, version and confidence for AI detections); ``evaluated`` means a rule evaluation
    (permit information, ADR-0014 §2) has been recorded. Both are required to *confirm*.
    A decision that undoes an earlier one is a reversal; reversing a confirmation is refused
    while a case is open, because the case already rests on it.
    """
    text = justification.strip()
    if len(text) < MIN_JUSTIFICATION_LENGTH:
        raise ValueValidationError(
            f"a justification of at least {MIN_JUSTIFICATION_LENGTH} characters is required",
            field="justification",
        )
    if len(text) > MAX_JUSTIFICATION_LENGTH:
        raise ValueValidationError("the justification is too long", field="justification")
    target = _OUTCOME[decision]
    if target is current:
        raise InvalidStateTransition(
            f"the candidate is already {current.value}",
            details={"status": current.value},
        )
    if decision is ReviewDecision.CONFIRM:
        if not evidence_complete:
            raise BusinessRuleViolation(
                "evidence provenance is incomplete: imagery references with acquisition dates"
                " (and model, version and confidence for an AI detection) are required",
                details={"missing": "provenance"},
            )
        if not evaluated:
            raise BusinessRuleViolation(
                "the candidate has not been evaluated against permit records",
                details={"missing": "evaluation"},
            )
    is_reversal = current in (CandidateStatus.CONFIRMED, CandidateStatus.REJECTED)
    if current is CandidateStatus.CONFIRMED and has_open_case:
        raise InvalidStateTransition(
            "a confirmed candidate with an open case cannot be changed; resolve or dismiss the"
            " case first",
            details={"status": current.value},
        )
    return ReviewOutcome(status=target, is_reversal=is_reversal)


def available_decisions(
    *, current: CandidateStatus, has_open_case: bool
) -> tuple[ReviewDecision, ...]:
    """Decisions the status rules would accept next (justification and provenance aside).

    Mirrors ``decide_review`` so a client can offer only what the server could accept; the server
    still validates every submission.
    """
    if current is CandidateStatus.CONFIRMED and has_open_case:
        return ()
    return tuple(d for d in ReviewDecision if _OUTCOME[d] is not current)


def require_verified(status: CandidateStatus) -> None:
    """The release gate: only a confirmed candidate may enter an enforcement workflow."""
    if status is not CandidateStatus.CONFIRMED:
        raise VerificationRequiredError(
            "only an officer-verified finding can be released into a case",
            details={"status": status.value},
        )
