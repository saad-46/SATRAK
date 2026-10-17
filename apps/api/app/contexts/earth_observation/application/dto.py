"""Application-layer DTOs (framework-free result objects)."""

from __future__ import annotations

from dataclasses import dataclass

from app.contexts.earth_observation.domain.enums import SceneStatus
from app.contexts.earth_observation.domain.value_objects.quality import QualityScore
from app.shared.domain.identifiers import EntityId


@dataclass(frozen=True)
class DiscoveryResult:
    """Outcome of one discovery pass over an AOI."""

    scene_ids: tuple[EntityId, ...]
    duplicates: int
    filtered_out: int

    @property
    def created(self) -> int:
        return len(self.scene_ids)


@dataclass(frozen=True)
class PreprocessingResult:
    """Outcome of one preprocessing run for a scene."""

    scene_id: EntityId
    status: SceneStatus
    pipeline_version: str
    quality: QualityScore | None = None
    thumbnail_uri: str | None = None
