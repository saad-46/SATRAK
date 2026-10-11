"""Persistence mapping contracts (Epic 3 Story 8).

Records + mappers only — persistence-agnostic. Concrete repositories/ORM arrive in the
SQLAlchemy story; nothing here imports a database library.
"""

from __future__ import annotations

from app.contexts.earth_observation.infrastructure.persistence.in_memory import (
    InMemoryAoiRepository,
    InMemorySceneRepository,
)
from app.contexts.earth_observation.infrastructure.persistence.mappers import (
    aoi_from_record,
    aoi_to_record,
    scene_from_record,
    scene_to_record,
)
from app.contexts.earth_observation.infrastructure.persistence.records import (
    AoiRecord,
    AuditFields,
    BandRecord,
    BoundingBoxRecord,
    SceneAssetRecord,
    SceneRecord,
)

__all__ = [
    "AoiRecord",
    "AuditFields",
    "BandRecord",
    "BoundingBoxRecord",
    "InMemoryAoiRepository",
    "InMemorySceneRepository",
    "SceneAssetRecord",
    "SceneRecord",
    "aoi_from_record",
    "aoi_to_record",
    "scene_from_record",
    "scene_to_record",
]
