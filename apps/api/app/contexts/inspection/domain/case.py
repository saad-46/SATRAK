"""Case lifecycle, assignment and field findings (PRD Module 10, FR-10.1 - FR-10.6).

A case exists only for an officer-verified candidate (ADR-0014); that gate is enforced by the
application service and, independently, by a database trigger. The state machine follows the
PRD (Created -> Assigned -> Under Investigation -> Notice Issued -> Resolved / Dismissed).
``Notice Issued`` records that a *human* has decided a notice is warranted; producing the
notice belongs to workflow automation (Module 11) and is not done here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from app.shared.domain.errors import InvalidStateTransition, ValueValidationError

MAX_NOTES_LENGTH: Final = 4_000
MAX_EVIDENCE_PER_FINDING: Final = 20
MAX_MEASUREMENTS: Final = 20
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_KINDS: Final = frozenset({"photo", "document", "drone_survey", "measurement_log"})


class CaseSource(StrEnum):
    AI_DETECTION = "ai_detection"
    MANUAL_REPORT = "manual_report"
    IMPORTED = "imported"


class CaseStatus(StrEnum):
    CREATED = "created"
    ASSIGNED = "assigned"
    UNDER_INVESTIGATION = "under_investigation"
    NOTICE_ISSUED = "notice_issued"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


TERMINAL: Final = frozenset({CaseStatus.RESOLVED, CaseStatus.DISMISSED})

_TRANSITIONS: Final = {
    CaseStatus.CREATED: {CaseStatus.ASSIGNED, CaseStatus.DISMISSED},
    CaseStatus.ASSIGNED: {CaseStatus.UNDER_INVESTIGATION, CaseStatus.DISMISSED},
    CaseStatus.UNDER_INVESTIGATION: {
        CaseStatus.NOTICE_ISSUED,
        CaseStatus.RESOLVED,
        CaseStatus.DISMISSED,
    },
    CaseStatus.NOTICE_ISSUED: {CaseStatus.RESOLVED, CaseStatus.DISMISSED},
    CaseStatus.RESOLVED: set(),
    CaseStatus.DISMISSED: set(),
}

_BASE_PRIORITY: Final = {"high": 70, "medium": 50, "low": 30, "none": 10}
_SOURCE_ADJUSTMENT: Final = {
    CaseSource.AI_DETECTION: 0,
    CaseSource.MANUAL_REPORT: 5,
    CaseSource.IMPORTED: 0,
}


def compute_priority(severity: str, source: CaseSource) -> int:
    """Priority 0-100 from evaluation severity and source (FR-10.2).

    The risk score of Module 14 does not exist yet, so it is not an input; this is a
    deterministic, explainable placeholder.
    """
    if severity not in _BASE_PRIORITY:
        raise ValueValidationError("unknown severity", field="severity")
    return min(100, _BASE_PRIORITY[severity] + _SOURCE_ADJUSTMENT[source])


def validate_transition(
    current: CaseStatus, target: CaseStatus, *, has_assignee: bool, finding_count: int
) -> None:
    """Raise ``InvalidStateTransition`` unless ``current`` -> ``target`` is allowed."""
    if target not in _TRANSITIONS[current]:
        raise InvalidStateTransition(
            f"a case that is {current.value} cannot become {target.value}",
            details={"from": current.value, "to": target.value},
        )
    if target in (CaseStatus.ASSIGNED, CaseStatus.UNDER_INVESTIGATION) and not has_assignee:
        raise InvalidStateTransition(
            "an officer must be assigned first", details={"to": target.value}
        )
    if target is CaseStatus.NOTICE_ISSUED and finding_count < 1:
        raise InvalidStateTransition(
            "at least one recorded finding is required before a notice can be issued",
            details={"to": target.value, "findings": finding_count},
        )


def available_transitions(
    current: CaseStatus, *, has_assignee: bool, finding_count: int
) -> tuple[CaseStatus, ...]:
    """Targets ``validate_transition`` would accept right now (assignment has its own operation)."""
    accepted: list[CaseStatus] = []
    for target in CaseStatus:
        if target is CaseStatus.ASSIGNED:
            continue
        try:
            validate_transition(
                current, target, has_assignee=has_assignee, finding_count=finding_count
            )
        except InvalidStateTransition:
            continue
        accepted.append(target)
    return tuple(accepted)


def validate_assignment_change(current: CaseStatus) -> CaseStatus:
    """A case can be (re)assigned until it is closed; returns the status after assignment."""
    if current in TERMINAL:
        raise InvalidStateTransition(
            f"a {current.value} case cannot be reassigned", details={"status": current.value}
        )
    return CaseStatus.ASSIGNED if current is CaseStatus.CREATED else current


@dataclass(frozen=True, slots=True)
class FindingEvidence:
    kind: str
    reference: str
    sha256: str
    captured_at: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "reference": self.reference,
            "sha256": self.sha256,
            "captured_at": self.captured_at.isoformat(),
        }


def _evidence(raw: Mapping[str, Any]) -> FindingEvidence:
    kind = str(raw.get("kind", ""))
    if kind not in EVIDENCE_KINDS:
        raise ValueValidationError(
            f"evidence kind must be one of: {', '.join(sorted(EVIDENCE_KINDS))}", field="evidence"
        )
    reference = str(raw.get("reference", "")).strip()
    if not reference or len(reference) > 512:
        raise ValueValidationError("evidence needs a reference (max 512)", field="evidence")
    digest = str(raw.get("sha256", "")).lower()
    if not _SHA256.fullmatch(digest):
        raise ValueValidationError("evidence needs a SHA-256 digest (64 hex)", field="evidence")
    captured = raw.get("captured_at")
    if not isinstance(captured, datetime) or captured.tzinfo is None:
        raise ValueValidationError("evidence captured_at must be timezone-aware", field="evidence")
    return FindingEvidence(kind=kind, reference=reference, sha256=digest, captured_at=captured)


def validate_finding(
    notes: str, measurements: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]
) -> tuple[str, dict[str, Any], list[FindingEvidence]]:
    """Normalise a field finding: notes, scalar measurements and hash-identified evidence."""
    text = notes.strip()
    if not text or len(text) > MAX_NOTES_LENGTH:
        raise ValueValidationError(
            f"notes are required (max {MAX_NOTES_LENGTH} characters)", field="notes"
        )
    if len(measurements) > MAX_MEASUREMENTS:
        raise ValueValidationError("too many measurements", field="measurements")
    for key, value in measurements.items():
        if not key or len(key) > 64:
            raise ValueValidationError(
                "measurement names are 1-64 characters", field="measurements"
            )
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            raise ValueValidationError("measurement values must be numbers or text", field=key)
        if isinstance(value, str) and len(value) > 200:
            raise ValueValidationError("measurement text is too long", field=key)
    if len(evidence) > MAX_EVIDENCE_PER_FINDING:
        raise ValueValidationError("too many evidence items", field="evidence")
    return text, dict(measurements), [_evidence(e) for e in evidence]
