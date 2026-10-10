"""Story 15 — thumbnail generation: sizing, naming, metadata, pipeline integration."""

from __future__ import annotations

import pytest

from app.contexts.earth_observation.application.preprocessing.pipeline_spec import (
    PipelineSpec,
    PipelineStep,
)
from app.contexts.earth_observation.application.preprocessing.preprocess_scene import (
    PreprocessingService,
)
from app.contexts.earth_observation.application.preprocessing.thumbnails import (
    DEFAULT_THUMBNAIL_SPECS,
    ThumbnailService,
    ThumbnailSpec,
)
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SceneStatus
from app.contexts.earth_observation.domain.value_objects import CrsRef
from app.contexts.earth_observation.infrastructure.raster import InMemoryRaster, RasterGrid
from app.contexts.earth_observation.infrastructure.raster.encoding import RawFloat32Encoder
from app.contexts.earth_observation.infrastructure.raster.resample import downsample_to_fit
from app.contexts.earth_observation.infrastructure.storage.keying import StorageKeyStrategy
from app.shared.domain.errors import ValueValidationError
from app.shared.persistence.unit_of_work import InMemoryUnitOfWork
from app.shared.services.storage import InMemoryStorageProvider
from tests.contexts.earth_observation.fakes import InMemorySceneRepository, make_scene


def _raster(width: int = 8, height: int = 4) -> InMemoryRaster:
    grid = RasterGrid(
        width=width,
        height=height,
        band_count=1,
        crs=CrsRef.wgs84(),
        origin_x=76.0,
        origin_y=14.0,
        pixel_size=0.25,
    )
    return InMemoryRaster(grid=grid, bands=[[float(v) for v in range(width * height)]])


def _service(
    storage: InMemoryStorageProvider, specs: tuple[ThumbnailSpec, ...]
) -> ThumbnailService:
    return ThumbnailService(
        storage=storage, keys=StorageKeyStrategy(), encoder=RawFloat32Encoder(), specs=specs
    )


# --- Downsampling ---------------------------------------------------------------------
def test_downsample_preserves_aspect_ratio() -> None:
    width, height, bands = downsample_to_fit(_raster(8, 4), max_dimension=4)
    assert (width, height) == (4, 2)
    assert len(bands[0]) == 8


def test_downsample_never_upscales() -> None:
    width, height, _ = downsample_to_fit(_raster(8, 4), max_dimension=100)
    assert (width, height) == (8, 4)


def test_downsample_validates_dimension() -> None:
    with pytest.raises(ValueValidationError):
        downsample_to_fit(_raster(), max_dimension=0)


def test_downsample_nearest_neighbour_values() -> None:
    # 4x2 -> 2x1: columns sample sources 0 and 2; the row samples source row 0.
    grid = RasterGrid(
        width=4,
        height=2,
        band_count=1,
        crs=CrsRef.wgs84(),
        origin_x=0.0,
        origin_y=2.0,
        pixel_size=1.0,
    )
    raster = InMemoryRaster(grid=grid, bands=[[10.0, 11.0, 12.0, 13.0, 20.0, 21.0, 22.0, 23.0]])
    width, height, bands = downsample_to_fit(raster, max_dimension=2)
    assert (width, height) == (2, 1)
    assert list(bands[0]) == [10.0, 12.0]


# --- ThumbnailService --------------------------------------------------------------------
async def test_generate_stores_all_variants_with_metadata() -> None:
    storage = InMemoryStorageProvider()
    scene = make_scene()
    scene.pull_events()
    specs = (
        ThumbnailSpec(variant="quicklook", max_dimension=4),
        ThumbnailSpec(variant="preview", max_dimension=2),
    )
    records = await _service(storage, specs).generate(_raster(8, 4), scene=scene)

    assert [r.variant for r in records] == ["quicklook", "preview"]
    assert [(r.width, r.height) for r in records] == [(4, 2), (2, 1)]
    for record in records:
        assert record.storage_key == f"thumbnails/{scene.id}/{record.variant}.bin"
        assert await storage.exists(record.storage_key)
        assert record.size_bytes == record.width * record.height * 4


async def test_generation_is_deterministic() -> None:
    scene = make_scene()
    scene.pull_events()
    specs = (ThumbnailSpec(variant="quicklook", max_dimension=4),)
    first = await _service(InMemoryStorageProvider(), specs).generate(_raster(), scene=scene)
    second = await _service(InMemoryStorageProvider(), specs).generate(_raster(), scene=scene)
    assert first[0].checksum_sha256 == second[0].checksum_sha256
    assert first[0].storage_key == second[0].storage_key


async def test_render_hook_returns_primary_uri() -> None:
    storage = InMemoryStorageProvider()
    scene = make_scene()
    scene.pull_events()
    uri = await _service(storage, DEFAULT_THUMBNAIL_SPECS).render(_raster(), scene=scene)
    assert uri == f"thumbnails/{scene.id}/quicklook.bin"
    assert await storage.exists(f"thumbnails/{scene.id}/preview.bin")


def test_spec_and_service_validation() -> None:
    with pytest.raises(ValueValidationError):
        ThumbnailSpec(variant="  ", max_dimension=4)
    with pytest.raises(ValueValidationError):
        ThumbnailSpec(variant="x", max_dimension=0)
    with pytest.raises(ValueValidationError):
        _service(InMemoryStorageProvider(), ())
    duplicate = ThumbnailSpec(variant="same", max_dimension=4)
    with pytest.raises(ValueValidationError):
        _service(InMemoryStorageProvider(), (duplicate, duplicate))


# --- Preprocessing pipeline integration ------------------------------------------------------
class _Loader:
    async def load(self, scene: Scene) -> InMemoryRaster:
        return _raster(8, 4)


async def test_pipeline_generates_thumbnails_automatically() -> None:
    scenes = InMemorySceneRepository()
    scene = make_scene()
    scene.mark_downloaded(checksum_sha256="ab" * 32)
    scene.mark_validated()
    scene.register()
    scene.pull_events()
    await scenes.add(scene)

    storage = InMemoryStorageProvider()
    service = PreprocessingService(
        scenes=scenes,
        uow=InMemoryUnitOfWork(),
        spec=PipelineSpec(version="1.0.0", steps=(PipelineStep.NORMALIZE, PipelineStep.THUMBNAIL)),
        loader=_Loader(),
        thumbnailer=_service(
            storage,
            (
                ThumbnailSpec(variant="quicklook", max_dimension=4),
                ThumbnailSpec(variant="preview", max_dimension=2),
            ),
        ),
    )
    result = await service.preprocess(scene_id=scene.id)

    assert scene.status is SceneStatus.PROCESSED
    assert result.thumbnail_uri == f"thumbnails/{scene.id}/quicklook.bin"
    assert await storage.exists(f"thumbnails/{scene.id}/preview.bin")
