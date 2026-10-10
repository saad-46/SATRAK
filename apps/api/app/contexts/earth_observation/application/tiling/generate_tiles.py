"""Tile generation orchestration (Epic 3 Story 14).

Cuts a PROCESSED scene into a multi-resolution XYZ pyramid: for every zoom in the
pyramid spec, tiles covering the scene footprint are rendered window-by-window, encoded
deterministically, and stored under their versioned cache keys (Story 9 —
``tiles/{tms}/{scene}/v{pipeline}/{z}/{x}/{y}``, so a reprocessed scene invalidates
cleanly). On completion the scene transitions TILED -> AVAILABLE, emitting
``TileGenerated`` (the ``tiles.ready`` trigger, ADR-0009) and ``SceneAvailable`` via the
Unit of Work.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.contexts.earth_observation.application.preprocessing.hooks import RasterDatasetLoader
from app.contexts.earth_observation.domain.enums import SceneStatus
from app.contexts.earth_observation.domain.ports.repositories import SceneRepository
from app.contexts.earth_observation.domain.value_objects.tile import TileCoord, TileMatrixSetRef
from app.contexts.earth_observation.infrastructure.raster.encoding import ImageEncoder
from app.contexts.earth_observation.infrastructure.storage.keying import StorageKeyStrategy
from app.contexts.earth_observation.infrastructure.tiles.renderer import render_tile
from app.contexts.earth_observation.infrastructure.tiles.tile_matrix import tiles_covering
from app.shared.domain.errors import BusinessRuleViolation, ValueValidationError
from app.shared.domain.identifiers import EntityId
from app.shared.persistence.unit_of_work import UnitOfWork
from app.shared.services.storage import StorageProvider

_MAX_ZOOM = 30


class TilingError(BusinessRuleViolation):
    """The scene is not in a tileable state."""

    code = "tiling_error"


@dataclass(frozen=True)
class PyramidSpec:
    """The zoom range and tile size of the generated pyramid."""

    min_zoom: int
    max_zoom: int
    tile_size: int = 256

    def __post_init__(self) -> None:
        if not 0 <= self.min_zoom <= self.max_zoom <= _MAX_ZOOM:
            raise ValueValidationError(
                f"zoom range must satisfy 0 <= min <= max <= {_MAX_ZOOM}", field="zoom"
            )
        if self.tile_size < 1:
            raise ValueValidationError("tile_size must be >= 1", field="tile_size")

    @property
    def zooms(self) -> range:
        return range(self.min_zoom, self.max_zoom + 1)


@dataclass(frozen=True)
class TileRecord:
    """Metadata for one stored tile (the tile_index row source, spec §13)."""

    coord: TileCoord
    storage_key: str
    checksum_sha256: str
    size_bytes: int


@dataclass(frozen=True)
class TilingResult:
    scene_id: EntityId
    tile_matrix_set: str
    pipeline_version: str
    tiles: tuple[TileRecord, ...]

    @property
    def count(self) -> int:
        return len(self.tiles)


class TilingService:
    """Generates, stores, and registers the tile pyramid for one processed scene."""

    def __init__(
        self,
        *,
        scenes: SceneRepository,
        uow: UnitOfWork,
        loader: RasterDatasetLoader,
        storage: StorageProvider,
        keys: StorageKeyStrategy,
        encoder: ImageEncoder,
        pyramid: PyramidSpec,
        tile_matrix_set: TileMatrixSetRef | None = None,
    ) -> None:
        self._scenes = scenes
        self._uow = uow
        self._loader = loader
        self._storage = storage
        self._keys = keys
        self._encoder = encoder
        self._pyramid = pyramid
        self._tms = (
            tile_matrix_set if tile_matrix_set is not None else TileMatrixSetRef.web_mercator_quad()
        )

    async def generate(self, *, scene_id: EntityId) -> TilingResult:
        scene = await self._scenes.require(scene_id)
        if scene.status is not SceneStatus.PROCESSED:
            raise TilingError(f"scene {scene_id} is {scene.status}, expected PROCESSED")
        # PROCESSED implies a pipeline_version (aggregate invariant), but the scene may come
        # from storage: fail with a domain error rather than tile under an unknown version.
        version = scene.pipeline_version
        if version is None:
            raise TilingError(f"scene {scene_id} is PROCESSED but has no pipeline_version")

        dataset = await self._loader.load(scene)
        records: list[TileRecord] = []
        for zoom in self._pyramid.zooms:
            for coord in tiles_covering(scene.bounding_box, zoom=zoom):
                tile = render_tile(dataset, coord, tile_size=self._pyramid.tile_size)
                encoded = self._encoder.encode(
                    width=self._pyramid.tile_size,
                    height=self._pyramid.tile_size,
                    bands=tile.data,
                )
                key = self._keys.tile_key(
                    tile_matrix_set=self._tms,
                    scene_id=scene.id,
                    pipeline_version=version,
                    tile=coord,
                    extension=encoded.extension,
                )
                await self._storage.save(
                    key,
                    encoded.data,
                    content_type=encoded.content_type,
                    filename=f"{coord.z}-{coord.x}-{coord.y}.{encoded.extension}",
                )
                records.append(
                    TileRecord(
                        coord=coord,
                        storage_key=key,
                        checksum_sha256=encoded.checksum_sha256,
                        size_bytes=encoded.size_bytes,
                    )
                )

        scene.mark_tiled(tile_matrix_set=self._tms)
        scene.mark_available()
        await self._scenes.update(scene)
        self._uow.track(scene)
        await self._uow.commit()
        return TilingResult(
            scene_id=scene.id,
            tile_matrix_set=self._tms.identifier,
            pipeline_version=version,
            tiles=tuple(records),
        )
