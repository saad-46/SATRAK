"""Imagery provider adapters — the extension mechanism (ADR-0007, Epic 3 Story 6).

Adding a provider touches only its own folder plus a registry entry (spec §5.8).
"""

from __future__ import annotations

from app.contexts.earth_observation.infrastructure.providers.auth import (
    ApiKeyAuth,
    AuthStrategy,
    NoAuth,
    StaticBearerAuth,
)
from app.contexts.earth_observation.infrastructure.providers.base import (
    HealthState,
    ProviderBase,
    ProviderConfiguration,
    ProviderFeature,
    ProviderHealth,
    SatelliteProvider,
    SceneCatalog,
    SceneDownloader,
)
from app.contexts.earth_observation.infrastructure.providers.errors import (
    ProviderConfigurationError,
    ProviderDataError,
    ProviderError,
    ProviderFeatureUnavailable,
)
from app.contexts.earth_observation.infrastructure.providers.policies import (
    RateLimitPolicy,
    RetryPolicy,
)
from app.contexts.earth_observation.infrastructure.providers.registry import (
    ProviderRegistry,
    ProviderRequirements,
)

__all__ = [
    "ApiKeyAuth",
    "AuthStrategy",
    "HealthState",
    "NoAuth",
    "ProviderBase",
    "ProviderConfiguration",
    "ProviderConfigurationError",
    "ProviderDataError",
    "ProviderError",
    "ProviderFeature",
    "ProviderFeatureUnavailable",
    "ProviderHealth",
    "ProviderRegistry",
    "ProviderRequirements",
    "RateLimitPolicy",
    "RetryPolicy",
    "SatelliteProvider",
    "SceneCatalog",
    "SceneDownloader",
    "StaticBearerAuth",
]
