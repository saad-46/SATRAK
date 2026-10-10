"""Provider abstraction — the extension mechanism for imagery sources (ADR-0007, spec §5).

Hierarchy::

    EarthObservationProvider (domain port, Protocol)
        ProviderBase (abstract adapter skeleton, this module)
            SatelliteProvider (spaceborne family)
                Sentinel2Provider, LandsatProvider, ...  (concrete, one folder each)
            AerialProvider (manned-airborne family, future)

``ProviderBase`` owns everything common — configuration, feature discovery, health,
transport wiring — so a concrete provider implements exactly three things: its
capabilities, its search query, and its metadata normalization. Transports (catalogue
search, byte download) are Protocols injected at wiring time; **no HTTP exists here**,
which is what keeps this sprint free of download execution while the contracts are final.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from app.contexts.earth_observation.domain.ports.imagery_provider import SceneCandidate
from app.contexts.earth_observation.domain.value_objects.capabilities import ProviderCapabilities
from app.contexts.earth_observation.domain.value_objects.scene_id import ProviderSceneId
from app.contexts.earth_observation.infrastructure.providers.auth import AuthStrategy, NoAuth
from app.contexts.earth_observation.infrastructure.providers.errors import (
    ProviderConfigurationError,
    ProviderFeatureUnavailable,
)
from app.contexts.earth_observation.infrastructure.providers.policies import (
    RateLimitPolicy,
    RetryPolicy,
)
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange


class ProviderFeature(StrEnum):
    """Discoverable features of a wired provider instance."""

    SEARCH = "search"
    DOWNLOAD = "download"
    TASKING = "tasking"


class HealthState(StrEnum):
    """Operational state of a provider instance."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ProviderHealth:
    """A point-in-time health assessment with a human-readable detail."""

    state: HealthState
    detail: str


@dataclass(frozen=True)
class ProviderConfiguration:
    """Deploy-time configuration for one provider instance.

    Credential values are *not* stored here — auth is a separate strategy object built
    from the secrets layer. ``extras`` carries provider-specific settings (collection
    names, product filters) without subclassing.
    """

    name: str
    base_url: str
    enabled: bool = True
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    rate_limit: RateLimitPolicy = field(default_factory=RateLimitPolicy)
    extras: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ProviderConfigurationError("provider name is required")
        if not self.base_url.strip():
            raise ProviderConfigurationError("base_url is required")


@runtime_checkable
class SceneCatalog(Protocol):
    """Search transport: executes a catalogue query and returns raw provider items.

    The STAC/OpenSearch HTTP implementation lands with the download story; tests use
    in-memory fakes. Items are raw provider payloads — normalization is the provider's job.
    """

    async def search_items(
        self, *, area: BoundingBox, window: TimeRange, query: Mapping[str, Any]
    ) -> Sequence[Mapping[str, Any]]: ...


@runtime_checkable
class SceneDownloader(Protocol):
    """Download transport: streams a scene's bytes. Contract only in this sprint."""

    def stream(self, provider_scene_id: ProviderSceneId) -> AsyncIterator[bytes]: ...


class ProviderBase(abc.ABC):
    """Adapter skeleton satisfying the domain ``EarthObservationProvider`` port."""

    def __init__(
        self,
        *,
        config: ProviderConfiguration,
        catalog: SceneCatalog | None = None,
        downloader: SceneDownloader | None = None,
        auth: AuthStrategy | None = None,
    ) -> None:
        self._config = config
        self._catalog = catalog
        self._downloader = downloader
        self._auth: AuthStrategy = auth if auth is not None else NoAuth()
        self.validate_configuration()

    # --- Identity / configuration -------------------------------------------
    @property
    def name(self) -> str:
        return self._config.name

    @property
    def config(self) -> ProviderConfiguration:
        return self._config

    @property
    def auth(self) -> AuthStrategy:
        return self._auth

    # --- Contracts a concrete provider must fulfil ---------------------------
    @abc.abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declared capabilities (sensor types, GSD range, tasking support)."""

    @abc.abstractmethod
    def normalize_item(self, item: Mapping[str, Any]) -> SceneCandidate:
        """Map one raw provider payload to a canonical :class:`SceneCandidate`."""

    @abc.abstractmethod
    def search_query(self) -> Mapping[str, Any]:
        """The provider-specific catalogue query (collection, product filters)."""

    @abc.abstractmethod
    def validate_configuration(self) -> None:
        """Provider-specific configuration checks; called on construction and by health."""

    # --- Feature discovery ----------------------------------------------------
    def features(self) -> frozenset[ProviderFeature]:
        """What this *instance* can do right now, given its wired transports."""
        available: set[ProviderFeature] = set()
        if self._catalog is not None:
            available.add(ProviderFeature.SEARCH)
        if self._downloader is not None:
            available.add(ProviderFeature.DOWNLOAD)
        if self.capabilities().supports_tasking:
            available.add(ProviderFeature.TASKING)
        return frozenset(available)

    # --- Health ----------------------------------------------------------------
    def health(self) -> ProviderHealth:
        """Deterministic assessment from configuration + wiring (no network probe)."""
        if not self._config.enabled:
            return ProviderHealth(state=HealthState.UNAVAILABLE, detail="provider disabled")
        try:
            self.validate_configuration()
        except ProviderConfigurationError as exc:
            return ProviderHealth(state=HealthState.UNAVAILABLE, detail=exc.message)
        if self._catalog is None:
            return ProviderHealth(
                state=HealthState.DEGRADED, detail="no catalogue transport attached"
            )
        return ProviderHealth(state=HealthState.HEALTHY, detail="configured")

    # --- Domain port: search ----------------------------------------------------
    async def search(self, *, area: BoundingBox, window: TimeRange) -> Sequence[SceneCandidate]:
        if self._catalog is None:
            raise ProviderFeatureUnavailable(
                f"provider {self.name!r} has no catalogue transport attached",
                feature=ProviderFeature.SEARCH,
            )
        items = await self._catalog.search_items(
            area=area, window=window, query=self.search_query()
        )
        return tuple(self.normalize_item(item) for item in items)

    # --- Domain port: fetch (contract only — transport arrives in a later story) --
    def fetch(self, provider_scene_id: ProviderSceneId) -> AsyncIterator[bytes]:
        if self._downloader is None:
            raise ProviderFeatureUnavailable(
                f"provider {self.name!r} has no download transport attached",
                feature=ProviderFeature.DOWNLOAD,
            )
        return self._downloader.stream(provider_scene_id)


class SatelliteProvider(ProviderBase, abc.ABC):
    """Spaceborne provider family (Sentinel, Landsat, Planet, Maxar, Airbus, Cartosat, Bhuvan)."""

    family: str = "satellite"
