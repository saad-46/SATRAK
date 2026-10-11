"""Explicit, audited-by-reason all-tenants scope for system jobs (ADR-0011 decision 6).

Never used for request handling: the web layer (``app.api``, ``app.main``) must not import
this module (import-linter contract). Each construction states why it is needed and is
logged, so system-wide reads are visible and reviewable.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.shared.domain.identifiers import EntityId
from app.shared.domain.scope import AccessScope

_logger = structlog.get_logger("shared.system_scope")


@dataclass(frozen=True, slots=True)
class SystemScope(AccessScope):
    """Every jurisdiction. Requires a non-empty ``reason`` naming the job and purpose."""

    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("a SystemScope needs a reason naming the job and its purpose")
        _logger.warning("system_scope_created", reason=self.reason[:150])

    def allows(self, jurisdiction_id: EntityId | None) -> bool:
        return True
