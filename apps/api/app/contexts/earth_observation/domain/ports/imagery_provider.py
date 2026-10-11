"""Imagery provider port — the extension mechanism (ADR-0007).

Concrete adapters (Sentinel-2, Landsat, ...) live in ``infrastructure/providers`` and
satisfy this Protocol; the application layer depends only on the port.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.contexts.earth_observation.domain.value_objects.acquisition import AcquisitionMetadata
from app.contexts.earth_observation.domain.value_objects.capabilities import ProviderCapabilities
from app.contexts.earth_observation.domain.value_objects.scene_id import ProviderSceneId
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange


@dataclass(frozen=True)
class SceneCandidate:
    """A discovered-but-not-yet-fetched scene returned by provider search."""

    provider_scene_id: ProviderSceneId
    bounding_box: BoundingBox
    acquisition: AcquisitionMetadata


@runtime_checkable
class EarthObservationProvider(Protocol):
    """Capability-driven contract for an imagery source."""

    def capabilities(self) -> ProviderCapabilities: ...

    async def search(self, *, area: BoundingBox, window: TimeRange) -> Sequence[SceneCandidate]: ...

    def fetch(self, provider_scene_id: ProviderSceneId) -> AsyncIterator[bytes]: ...
