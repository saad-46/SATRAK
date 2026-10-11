"""Story 14 — tile matrix math, windowed rendering, and tiling orchestration."""

from __future__ import annotations

import pytest

from app.contexts.earth_observation.application.tiling.generate_tiles import (
    PyramidSpec,
    TilingError,
    TilingService,
)
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SceneStatus
from app.contexts.earth_observation.domain.events import SceneAvailable, TileGenerated
from app.contexts.earth_observation.domain.value_objects import CrsRef, TileCoord
from app.contexts.earth_observation.infrastructure.raster import InMemoryRaster, RasterGrid
from app.contexts.earth_observation.infrastructure.raster.encoding import RawFloat32Encoder
from app.contexts.earth_observation.infrastructure.storage.keying import StorageKeyStrategy
from app.contexts.earth_observation.infrastructure.tiles import (
    MAX_MERCATOR_LATITUDE,
    lonlat_to_tile,
    render_tile,
    tile_bounds_wgs84,
    tiles_covering,
)
from app.shared.domain.errors import ValueValidationError
from app.shared.domain.events import DomainEvent
from app.shared.events.bus import InMemoryEventBus
from app.shared.persistence.unit_of_work import InMemoryUnitOfWork
from app.shared.services.storage import InMemoryStorageProvider
from tests.contexts.earth_observation.fakes import BBOX, SCOPE, InMemorySceneRepository, make_scene


# --- Tile matrix math ---------------------------------------------------------------
def test_zoom_zero_is_the_world_tile() -> None:
    assert lonlat_to_tile(longitude=76.0, latitude=14.0, zoom=0) == TileCoord(z=0, x=0, y=0)
    bounds = tile_bounds_wgs84(TileCoord(z=0, x=0, y=0))
    assert bounds.min_longitude == -180.0
    assert bounds.max_longitude == 180.0
    assert bounds.max_latitude == pytest.approx(MAX_MERCATOR_LATITUDE, abs=1e-6)
    assert bounds.min_latitude == pytest.approx(-MAX_MERCATOR_LATITUDE, abs=1e-6)


def test_lonlat_to_tile_known_values() -> None:
    assert lonlat_to_tile(longitude=76.0, latitude=14.0, zoom=2) == TileCoord(z=2, x=2, y=1)
    assert lonlat_to_tile(longitude=0.0, latitude=0.0, zoom=1) == TileCoord(z=1, x=1, y=1)
    # Poles clamp to the Mercator limit instead of overflowing the row range.
    assert lonlat_to_tile(longitude=180.0, latitude=90.0, zoom=1) == TileCoord(z=1, x=1, y=0)
    assert lonlat_to_tile(longitude=-180.0, latitude=-90.0, zoom=1) == TileCoord(z=1, x=0, y=1)


def test_tile_bounds_round_trip() -> None:
    coord = TileCoord(z=5, x=22, y=13)
    bounds = tile_bounds_wgs84(coord)
    assert (
        lonlat_to_tile(longitude=bounds.center.longitude, latitude=bounds.center.latitude, zoom=5)
        == coord
    )


def test_tiles_covering_is_row_major_and_complete() -> None:
    assert list(tiles_covering(BBOX, zoom=2)) == [TileCoord(z=2, x=2, y=1)]
    z8 = list(tiles_covering(BBOX, zoom=8))
    assert len(z8) > 1
    assert z8 == sorted(z8, key=lambda t: (t.y, t.x))  # deterministic row-major order


# --- Rendering ------------------------------------------------------------------------
def _world_raster() -> InMemoryRaster:
    """4x2 raster spanning the world (90-degree pixels; one value per quadrant)."""
    grid = RasterGrid(
        width=4,
        height=2,
        band_count=1,
        crs=CrsRef.wgs84(),
        origin_x=-180.0,
        origin_y=MAX_MERCATOR_LATITUDE,
        pixel_size=90.0,
    )
    return InMemoryRaster(grid=grid, bands=[[1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0]])


def test_render_tile_samples_quadrants() -> None:
    # At z=0 with a 2x2 output, the sample centres land at (±90 lon, ±66.5 lat) —
    # one per world quadrant of the synthetic raster.
    tile = render_tile(_world_raster(), TileCoord(z=0, x=0, y=0), tile_size=2)
    assert list(tile.data[0]) == [1.0, 2.0, 3.0, 4.0]


def test_render_tile_is_deterministic() -> None:
    raster = _world_raster()
    a = render_tile(raster, TileCoord(z=1, x=0, y=0), tile_size=8)
    b = render_tile(raster, TileCoord(z=1, x=0, y=0), tile_size=8)
    assert a.checksum_sha256 == b.checksum_sha256
    assert a.data == b.data


def test_render_tile_outside_extent_is_nodata() -> None:
    grid = RasterGrid(
        width=8,
        height=8,
        band_count=1,
        crs=CrsRef.wgs84(),
        origin_x=76.0,
        origin_y=14.0,
        pixel_size=0.25,
    )
    raster = InMemoryRaster(grid=grid, bands=[[5.0] * 64])
    far_tile = render_tile(raster, TileCoord(z=2, x=0, y=0), tile_size=4, nodata=-1.0)
    assert set(far_tile.data[0]) == {-1.0}


def test_render_tile_rejects_bad_size() -> None:
    with pytest.raises(ValueValidationError):
        render_tile(_world_raster(), TileCoord(z=0, x=0, y=0), tile_size=0)


# --- Encoder ---------------------------------------------------------------------------
def test_raw_encoder_validates_and_fingerprints() -> None:
    encoder = RawFloat32Encoder()
    tile = render_tile(_world_raster(), TileCoord(z=0, x=0, y=0), tile_size=2)
    encoded = encoder.encode(width=2, height=2, bands=tile.data)
    assert encoded.size_bytes == 2 * 2 * 4  # float32
    assert (
        encoded.checksum_sha256
        == encoder.encode(width=2, height=2, bands=tile.data).checksum_sha256
    )
    with pytest.raises(ValueValidationError):
        encoder.encode(width=0, height=2, bands=tile.data)
    with pytest.raises(ValueValidationError):
        encoder.encode(width=2, height=2, bands=())
    with pytest.raises(ValueValidationError):
        encoder.encode(width=3, height=3, bands=tile.data)  # length mismatch


# --- Pyramid spec ------------------------------------------------------------------------
def test_pyramid_spec_validation() -> None:
    assert list(PyramidSpec(min_zoom=1, max_zoom=3).zooms) == [1, 2, 3]
    with pytest.raises(ValueValidationError):
        PyramidSpec(min_zoom=3, max_zoom=1)
    with pytest.raises(ValueValidationError):
        PyramidSpec(min_zoom=-1, max_zoom=1)
    with pytest.raises(ValueValidationError):
        PyramidSpec(min_zoom=0, max_zoom=0, tile_size=0)


# --- TilingService --------------------------------------------------------------------------
class _SceneLoader:
    def __init__(self, raster: InMemoryRaster) -> None:
        self._raster = raster

    async def load(self, scene: Scene) -> InMemoryRaster:
        return self._raster


def _processed_scene() -> Scene:
    scene = make_scene()
    scene.mark_downloaded(checksum_sha256="ab" * 32)
    scene.mark_validated()
    scene.register()
    scene.start_preprocessing(pipeline_version="1.0.0")
    scene.mark_processed()
    scene.pull_events()
    return scene


def _scene_raster() -> InMemoryRaster:
    grid = RasterGrid(
        width=8,
        height=8,
        band_count=1,
        crs=CrsRef.wgs84(),
        origin_x=76.0,
        origin_y=14.0,
        pixel_size=0.25,
    )
    return InMemoryRaster(grid=grid, bands=[[float(v) for v in range(64)]])


async def test_tiling_service_generates_versioned_pyramid() -> None:
    bus = InMemoryEventBus()
    published: list[DomainEvent] = []
    bus.subscribe(DomainEvent, published.append)

    scenes = InMemorySceneRepository()
    scene = _processed_scene()
    await scenes.add(scene)
    storage = InMemoryStorageProvider()

    service = TilingService(
        scenes=scenes,
        uow=InMemoryUnitOfWork(bus),
        loader=_SceneLoader(_scene_raster()),
        storage=storage,
        keys=StorageKeyStrategy(),
        encoder=RawFloat32Encoder(),
        pyramid=PyramidSpec(min_zoom=1, max_zoom=2, tile_size=4),
    )
    result = await service.generate(scene_id=scene.id, scope=SCOPE)

    assert result.count == 2  # one tile at z=1, one at z=2 for this footprint
    assert result.tile_matrix_set == "WebMercatorQuad"
    assert result.pipeline_version == "1.0.0"
    prefix = f"tiles/WebMercatorQuad/{scene.id}/v1.0.0/"
    for record in result.tiles:
        assert record.storage_key.startswith(prefix)
        assert await storage.exists(record.storage_key)
        assert record.size_bytes == 4 * 4 * 4
    assert scene.status is SceneStatus.AVAILABLE
    kinds = [type(e) for e in published]
    assert TileGenerated in kinds
    assert SceneAvailable in kinds


async def test_tiling_is_deterministic_across_runs() -> None:
    async def run_once() -> tuple[str, ...]:
        scenes = InMemorySceneRepository()
        scene = _processed_scene()
        await scenes.add(scene)
        service = TilingService(
            scenes=scenes,
            uow=InMemoryUnitOfWork(),
            loader=_SceneLoader(_scene_raster()),
            storage=InMemoryStorageProvider(),
            keys=StorageKeyStrategy(),
            encoder=RawFloat32Encoder(),
            pyramid=PyramidSpec(min_zoom=1, max_zoom=2, tile_size=4),
        )
        result = await service.generate(scene_id=scene.id, scope=SCOPE)
        return tuple(record.checksum_sha256 for record in result.tiles)

    assert await run_once() == await run_once()


async def test_tiling_rejects_processed_scene_without_pipeline_version() -> None:
    scenes = InMemorySceneRepository()
    scene = _processed_scene()
    scene.pipeline_version = None  # inconsistent persisted state; must fail with a domain error
    await scenes.add(scene)
    service = TilingService(
        scenes=scenes,
        uow=InMemoryUnitOfWork(),
        loader=_SceneLoader(_scene_raster()),
        storage=InMemoryStorageProvider(),
        keys=StorageKeyStrategy(),
        encoder=RawFloat32Encoder(),
        pyramid=PyramidSpec(min_zoom=1, max_zoom=1),
    )
    with pytest.raises(TilingError, match="pipeline_version"):
        await service.generate(scene_id=scene.id, scope=SCOPE)


async def test_tiling_requires_processed_scene() -> None:
    scenes = InMemorySceneRepository()
    scene = make_scene()
    scene.pull_events()
    await scenes.add(scene)
    service = TilingService(
        scenes=scenes,
        uow=InMemoryUnitOfWork(),
        loader=_SceneLoader(_scene_raster()),
        storage=InMemoryStorageProvider(),
        keys=StorageKeyStrategy(),
        encoder=RawFloat32Encoder(),
        pyramid=PyramidSpec(min_zoom=1, max_zoom=1),
    )
    with pytest.raises(TilingError):
        await service.generate(scene_id=scene.id, scope=SCOPE)
