"""Storage lifecycle strategy (Epic 3 Story 9, spec §7.1).

Declarative tier-retention rules evaluated as pure functions. The retention job (Story 20)
reads the policy and asks "what happens to this asset at this age?" — the policy never
touches storage itself. When a tier has several rules, the one with the highest satisfied
threshold wins (e.g. raw: archive at 90 days, delete at 3650 days).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.contexts.earth_observation.domain.enums import AssetTier
from app.shared.domain.errors import ValueValidationError


class LifecycleAction(StrEnum):
    RETAIN = "retain"
    ARCHIVE = "archive"
    DELETE = "delete"


@dataclass(frozen=True)
class LifecycleRule:
    """After ``after_days`` in ``tier``, apply ``action``."""

    tier: AssetTier
    after_days: int
    action: LifecycleAction

    def __post_init__(self) -> None:
        if self.after_days < 0:
            raise ValueValidationError("after_days must be >= 0", field="after_days")
        if self.action is LifecycleAction.RETAIN:
            raise ValueValidationError(
                "RETAIN is the implicit default; rules must archive or delete", field="action"
            )
        if self.tier is AssetTier.ARCHIVE and self.action is LifecycleAction.ARCHIVE:
            raise ValueValidationError("archive tier cannot be archived again", field="action")


@dataclass(frozen=True)
class StorageLifecyclePolicy:
    """An ordered set of lifecycle rules; duplicate (tier, action) pairs are rejected."""

    rules: tuple[LifecycleRule, ...]

    def __post_init__(self) -> None:
        seen = {(rule.tier, rule.action) for rule in self.rules}
        if len(seen) != len(self.rules):
            raise ValueValidationError("duplicate (tier, action) lifecycle rules", field="rules")

    def action_for(self, *, tier: AssetTier, age_days: int) -> LifecycleAction:
        """The strongest action whose threshold the asset's age has passed."""
        if age_days < 0:
            raise ValueValidationError("age_days must be >= 0", field="age_days")
        due = [r for r in self.rules if r.tier is tier and age_days >= r.after_days]
        if not due:
            return LifecycleAction.RETAIN
        # DELETE dominates ARCHIVE when both thresholds have passed.
        if any(r.action is LifecycleAction.DELETE for r in due):
            return LifecycleAction.DELETE
        return LifecycleAction.ARCHIVE


def default_policy() -> StorageLifecyclePolicy:
    """The spec §7.1 defaults; deployments override per jurisdiction."""
    return StorageLifecyclePolicy(
        rules=(
            LifecycleRule(tier=AssetTier.RAW, after_days=90, action=LifecycleAction.ARCHIVE),
            LifecycleRule(tier=AssetTier.EXPORTS, after_days=7, action=LifecycleAction.DELETE),
            LifecycleRule(tier=AssetTier.TEMPORARY, after_days=1, action=LifecycleAction.DELETE),
        )
    )
