"""Earth Observation domain events (Epic 3 Story 3).

All are immutable records subclassing :class:`~app.shared.domain.events.EntityEvent`, so
they carry ``aggregate_id`` + ``aggregate_type``. Aggregates record them; the Unit of Work
dispatches them after a successful commit (ADR-0002). Names follow spec §15.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain.events import EntityEvent


@dataclass(frozen=True, kw_only=True)
class ImageDiscovered(EntityEvent):
    """A candidate scene was discovered at a provider."""

    provider_scene_id: str


@dataclass(frozen=True, kw_only=True)
class ImageDownloaded(EntityEvent):
    """Raw bytes were fetched and checksummed."""

    checksum_sha256: str


@dataclass(frozen=True, kw_only=True)
class ImageValidated(EntityEvent):
    """The download passed integrity/format/completeness checks."""


@dataclass(frozen=True, kw_only=True)
class ImageRejected(EntityEvent):
    """The scene failed validation (or exhausted retries)."""

    reason: str


@dataclass(frozen=True, kw_only=True)
class MetadataExtracted(EntityEvent):
    """Canonical metadata was resolved for the scene."""


@dataclass(frozen=True, kw_only=True)
class ImageStored(EntityEvent):
    """The scene reference was registered/persisted."""


@dataclass(frozen=True, kw_only=True)
class SceneProcessed(EntityEvent):
    """A pipeline produced an analysis-ready product for the scene."""

    pipeline_version: str


@dataclass(frozen=True, kw_only=True)
class SceneReprocessed(EntityEvent):
    """The scene was reprocessed under a new pipeline version."""

    pipeline_version: str


@dataclass(frozen=True, kw_only=True)
class SceneProcessingFailed(EntityEvent):
    """A preprocessing/tiling stage failed (retry-able)."""

    reason: str


@dataclass(frozen=True, kw_only=True)
class TileGenerated(EntityEvent):
    """A tile set was produced for the scene."""

    tile_matrix_set: str


@dataclass(frozen=True, kw_only=True)
class SceneAvailable(EntityEvent):
    """The scene reached the ``AVAILABLE`` state."""


@dataclass(frozen=True, kw_only=True)
class ImageArchived(EntityEvent):
    """The scene was moved to cold storage."""
