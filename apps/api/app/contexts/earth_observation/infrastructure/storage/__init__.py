"""Storage key + lifecycle strategy (Epic 3 Story 9).

Pure strategy objects over the shared ``StorageProvider`` port — no storage SDKs here.
"""

from __future__ import annotations

from app.contexts.earth_observation.infrastructure.storage.keying import (
    StorageKeyStrategy,
    ensure_sha256,
    tier_of,
)
from app.contexts.earth_observation.infrastructure.storage.lifecycle import (
    LifecycleAction,
    LifecycleRule,
    StorageLifecyclePolicy,
    default_policy,
)

__all__ = [
    "LifecycleAction",
    "LifecycleRule",
    "StorageKeyStrategy",
    "StorageLifecyclePolicy",
    "default_policy",
    "ensure_sha256",
    "tier_of",
]
