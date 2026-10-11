"""Thumbnail generation (Epic 3 Story 15).

Generates aspect-preserving previews in one or more sizes, stored under deterministic
names (Story 9: ``thumbnails/{scene_id}/{variant}.{ext}``). ``ThumbnailService``
satisfies the preprocessing pipeline's ``ThumbnailRenderer`` hook (Story 13), so wiring
it into ``PreprocessingService`` makes previews automatic; it also runs standalone from
the thumbnail job. Rendering is provider-independent: pixels go through the
``ImageEncoder`` seam (raw float32 today; PNG/WEBP adapters later, same Protocol).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.infrastructure.raster.dataset import RasterDataset
from app.contexts.earth_observation.infrastructure.raster.encoding import ImageEncoder
from app.contexts.earth_observation.infrastructure.raster.resample import downsample_to_fit
from app.contexts.earth_observation.infrastructure.storage.keying import StorageKeyStrategy
from app.shared.domain.errors import ValueValidationError
from app.shared.services.storage import StorageProvider


@dataclass(frozen=True)
class ThumbnailSpec:
    """One preview variant: a deterministic name and a bounding dimension."""

    variant: str
    max_dimension: int

    def __post_init__(self) -> None:
        if not self.variant.strip():
            raise ValueValidationError("variant is required", field="variant")
        if self.max_dimension < 1:
            raise ValueValidationError("max_dimension must be >= 1", field="max_dimension")


DEFAULT_THUMBNAIL_SPECS: tuple[ThumbnailSpec, ...] = (
    ThumbnailSpec(variant="quicklook", max_dimension=512),
    ThumbnailSpec(variant="preview", max_dimension=128),
)


@dataclass(frozen=True)
class ThumbnailRecord:
    """Metadata for one stored thumbnail."""

    variant: str
    width: int
    height: int
    storage_key: str
    checksum_sha256: str
    size_bytes: int


class ThumbnailService:
    """Renders and stores every configured preview size for a scene's dataset."""

    def __init__(
        self,
        *,
        storage: StorageProvider,
        keys: StorageKeyStrategy,
        encoder: ImageEncoder,
        specs: tuple[ThumbnailSpec, ...] = DEFAULT_THUMBNAIL_SPECS,
    ) -> None:
        if not specs:
            raise ValueValidationError("at least one thumbnail spec is required", field="specs")
        if len({spec.variant for spec in specs}) != len(specs):
            raise ValueValidationError("thumbnail variants must be unique", field="specs")
        self._storage = storage
        self._keys = keys
        self._encoder = encoder
        self._specs = specs

    async def generate(
        self, dataset: RasterDataset, *, scene: Scene
    ) -> tuple[ThumbnailRecord, ...]:
        """Store all variants; deterministic keys and content for identical inputs."""
        records: list[ThumbnailRecord] = []
        for spec in self._specs:
            width, height, bands = downsample_to_fit(dataset, max_dimension=spec.max_dimension)
            encoded = self._encoder.encode(width=width, height=height, bands=bands)
            key = self._keys.thumbnail_key(
                scene_id=scene.id, variant=spec.variant, extension=encoded.extension
            )
            await self._storage.save(
                key,
                encoded.data,
                content_type=encoded.content_type,
                filename=f"{spec.variant}.{encoded.extension}",
            )
            records.append(
                ThumbnailRecord(
                    variant=spec.variant,
                    width=width,
                    height=height,
                    storage_key=key,
                    checksum_sha256=encoded.checksum_sha256,
                    size_bytes=encoded.size_bytes,
                )
            )
        return tuple(records)

    async def render(self, dataset: RasterDataset, *, scene: Scene) -> str:
        """The ``ThumbnailRenderer`` pipeline hook: generate all sizes, return the primary."""
        records = await self.generate(dataset, scene=scene)
        return records[0].storage_key
