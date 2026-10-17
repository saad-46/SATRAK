"""Provider registry — capability-based resolution (ADR-0007, spec §5.1).

The registry answers "which provider can serve this request?" by matching declared
capabilities and discovered features, never by hard-coding provider names in consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.contexts.earth_observation.domain.enums import SensorType
from app.contexts.earth_observation.infrastructure.providers.base import (
    ProviderBase,
    ProviderFeature,
    ProviderHealth,
)
from app.contexts.earth_observation.infrastructure.providers.errors import ProviderError


@dataclass(frozen=True)
class ProviderRequirements:
    """What a caller needs from a provider (all criteria are ANDed)."""

    sensor_type: SensorType | None = None
    max_gsd_m: float | None = None
    require_tasking: bool = False
    required_features: frozenset[ProviderFeature] = field(default_factory=frozenset)

    def matched_by(self, provider: ProviderBase) -> bool:
        caps = provider.capabilities()
        if self.sensor_type is not None and not caps.supports(self.sensor_type):
            return False
        if self.max_gsd_m is not None and (
            caps.min_gsd_m is None or caps.min_gsd_m > self.max_gsd_m
        ):
            return False
        if self.require_tasking and not caps.supports_tasking:
            return False
        return self.required_features <= provider.features()


class ProviderRegistry:
    """Name-keyed provider collection with capability-driven resolution."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderBase] = {}

    def register(self, provider: ProviderBase) -> None:
        if provider.name in self._providers:
            raise ProviderError(f"provider {provider.name!r} is already registered")
        self._providers[provider.name] = provider

    def get(self, name: str) -> ProviderBase:
        try:
            return self._providers[name]
        except KeyError:
            raise ProviderError(f"no provider registered under {name!r}") from None

    def names(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def resolve(self, requirements: ProviderRequirements) -> tuple[ProviderBase, ...]:
        """Enabled providers matching the requirements, finest resolution first."""
        matches = [
            p for p in self._providers.values() if p.config.enabled and requirements.matched_by(p)
        ]
        matches.sort(key=_finest_gsd)
        return tuple(matches)

    def health_report(self) -> dict[str, ProviderHealth]:
        return {name: provider.health() for name, provider in self._providers.items()}


def _finest_gsd(provider: ProviderBase) -> float:
    """Sort key: providers with unknown resolution sort last."""
    gsd = provider.capabilities().min_gsd_m
    return gsd if gsd is not None else float("inf")
