"""Content-addressed storage key strategy (Epic 3 Story 9, spec §7.2).

Deterministic object keys per tier::

    raw/{provider}/{sensor}/{yyyy}/{mm}/{dd}/{native_id}/{sha[:2]}/{sha}.{ext}
    processed/{provider}/{sensor}/{yyyy}/{mm}/{dd}/{scene_id}/v{pipeline}/{product}.{ext}
    cog/  == processed/ (logical alias; COG is the processed format, ADR-0006)
    tiles/{tile_matrix_set}/{scene_id}/v{pipeline}/{z}/{x}/{y}.{ext}
    thumbnails/{scene_id}/{variant}.{ext}
    exports/{request_id}/{artifact}.{ext}
    temporary/{job_id}/{name}
    archive/{original key}

Content-addressing (checksum in the raw path) gives dedup + integrity for free; the
``v{pipeline_version}`` segment isolates reprocessing variants so nothing is ever
overwritten. Pure string construction — no storage SDK anywhere near this module; keys
feed the shared ``StorageProvider`` port.
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from app.contexts.earth_observation.domain.enums import AssetTier, SensorType
from app.contexts.earth_observation.domain.value_objects.scene_id import ProviderSceneId
from app.contexts.earth_observation.domain.value_objects.tile import TileCoord, TileMatrixSetRef
from app.shared.domain.errors import ValueValidationError

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def ensure_sha256(checksum: str) -> str:
    """Validate + normalize a SHA-256 hex digest (lowercase)."""
    normalized = checksum.strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueValidationError(
            "checksum must be a 64-character SHA-256 hex digest", field="checksum_sha256"
        )
    return normalized


def _segment(value: str, field: str) -> str:
    """Validate a single path segment (no separators, no traversal, no spaces)."""
    if not _SEGMENT_RE.fullmatch(value):
        raise ValueValidationError(f"{field} is not a valid key segment: {value!r}", field=field)
    return value


def _date_segments(moment: datetime) -> str:
    return f"{moment.year:04d}/{moment.month:02d}/{moment.day:02d}"


def _version_segment(pipeline_version: str) -> str:
    return f"v{_segment(pipeline_version, 'pipeline_version')}"


class StorageKeyStrategy:
    """Builds every object key the EO platform writes. Stateless and deterministic."""

    def raw_key(
        self,
        *,
        provider_scene_id: ProviderSceneId,
        sensor_type: SensorType,
        acquired_at: datetime,
        checksum_sha256: str,
        extension: str,
    ) -> str:
        sha = ensure_sha256(checksum_sha256)
        return "/".join(
            (
                AssetTier.RAW.value,
                _segment(provider_scene_id.provider, "provider"),
                sensor_type.value,
                _date_segments(acquired_at),
                _segment(provider_scene_id.native_id, "native_id"),
                sha[:2],
                f"{sha}.{_segment(extension, 'extension')}",
            )
        )

    def processed_key(
        self,
        *,
        provider: str,
        sensor_type: SensorType,
        acquired_at: datetime,
        scene_id: UUID,
        pipeline_version: str,
        product: str,
        extension: str = "tif",
    ) -> str:
        return "/".join(
            (
                AssetTier.PROCESSED.value,
                _segment(provider, "provider"),
                sensor_type.value,
                _date_segments(acquired_at),
                str(scene_id),
                _version_segment(pipeline_version),
                f"{_segment(product, 'product')}.{_segment(extension, 'extension')}",
            )
        )

    def cog_key(
        self,
        *,
        provider: str,
        sensor_type: SensorType,
        acquired_at: datetime,
        scene_id: UUID,
        pipeline_version: str,
        product: str,
    ) -> str:
        """COG is the processed format — same layout, ``.tif``, one source of truth."""
        return self.processed_key(
            provider=provider,
            sensor_type=sensor_type,
            acquired_at=acquired_at,
            scene_id=scene_id,
            pipeline_version=pipeline_version,
            product=product,
            extension="tif",
        )

    def tile_key(
        self,
        *,
        tile_matrix_set: TileMatrixSetRef,
        scene_id: UUID,
        pipeline_version: str,
        tile: TileCoord,
        extension: str = "png",
    ) -> str:
        return "/".join(
            (
                AssetTier.TILES.value,
                _segment(tile_matrix_set.identifier, "tile_matrix_set"),
                str(scene_id),
                _version_segment(pipeline_version),
                str(tile.z),
                str(tile.x),
                f"{tile.y}.{_segment(extension, 'extension')}",
            )
        )

    def thumbnail_key(
        self, *, scene_id: UUID, variant: str = "quicklook", extension: str = "webp"
    ) -> str:
        return "/".join(
            (
                AssetTier.THUMBNAILS.value,
                str(scene_id),
                f"{_segment(variant, 'variant')}.{_segment(extension, 'extension')}",
            )
        )

    def export_key(self, *, request_id: UUID, artifact: str, extension: str) -> str:
        return "/".join(
            (
                AssetTier.EXPORTS.value,
                str(request_id),
                f"{_segment(artifact, 'artifact')}.{_segment(extension, 'extension')}",
            )
        )

    def temporary_key(self, *, job_id: UUID, name: str) -> str:
        return "/".join((AssetTier.TEMPORARY.value, str(job_id), _segment(name, "name")))

    def archive_key(self, *, original_key: str) -> str:
        """Cold-tier key mirroring the original layout (spec §7.1)."""
        tier = tier_of(original_key)
        if tier in (AssetTier.ARCHIVE, AssetTier.TEMPORARY):
            raise ValueValidationError(
                f"{tier.value} assets cannot be archived", field="original_key"
            )
        return f"{AssetTier.ARCHIVE.value}/{original_key}"


def tier_of(key: str) -> AssetTier:
    """The storage tier a key belongs to (its first path segment)."""
    prefix, _, rest = key.partition("/")
    if not rest:
        raise ValueValidationError(f"not a valid storage key: {key!r}", field="key")
    try:
        return AssetTier(prefix)
    except ValueError:
        raise ValueValidationError(
            f"unknown storage tier {prefix!r} in key {key!r}", field="key"
        ) from None
