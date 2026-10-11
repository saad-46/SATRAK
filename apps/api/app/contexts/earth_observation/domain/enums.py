"""Earth Observation domain enumerations.

``SensorType`` discriminates provider capabilities (optical vs SAR) so consumers branch
on capability, never on provider name. ``SceneStatus`` is the scene lifecycle; the allowed
transitions live on the :class:`~app.contexts.earth_observation.domain.aggregates.scene.Scene`
aggregate, not here.
"""

from __future__ import annotations

from enum import StrEnum


class SensorType(StrEnum):
    """The physical sensing modality of an imagery source."""

    OPTICAL = "optical"
    SAR = "sar"
    HYPERSPECTRAL = "hyperspectral"


class AssetTier(StrEnum):
    """Storage tier an imagery asset lives in (spec §7.1)."""

    RAW = "raw"
    PROCESSED = "processed"
    COG = "cog"
    TILES = "tiles"
    THUMBNAILS = "thumbnails"
    EXPORTS = "exports"
    TEMPORARY = "temporary"
    ARCHIVE = "archive"


class SceneStatus(StrEnum):
    """Lifecycle state of a scene, from discovery to availability/archival.

    Allowed transitions are enforced by the ``Scene`` aggregate (spec §6.1).
    """

    DISCOVERED = "discovered"
    DOWNLOADED = "downloaded"
    VALIDATED = "validated"
    REJECTED = "rejected"
    REGISTERED = "registered"
    PREPROCESSING = "preprocessing"
    PROCESSED = "processed"
    TILED = "tiled"
    AVAILABLE = "available"
    FAILED = "failed"
    ARCHIVED = "archived"
