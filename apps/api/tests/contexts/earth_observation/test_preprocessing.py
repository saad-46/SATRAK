"""Story 13 — preprocessing pipeline: spec, quality scoring, orchestration."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.contexts.earth_observation.application.preprocessing.pipeline_spec import (
    PipelineSpec,
    PipelineStep,
)
from app.contexts.earth_observation.application.preprocessing.preprocess_scene import (
    HookNotConfiguredError,
    PreprocessingError,
    PreprocessingService,
    score_quality,
)
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SceneStatus, SensorType
from app.contexts.earth_observation.domain.events import (
    SceneProcessed,
    SceneProcessingFailed,
    SceneReprocessed,
)
from app.contexts.earth_observation.domain.value_objects import (
    AcquisitionMetadata,
    CloudCoverPercentage,
    CrsRef,
    TileMatrixSetRef,
)
from app.contexts.earth_observation.infrastructure.raster import (
    InMemoryRaster,
    RasterDataset,
    RasterGrid,
)
from app.shared.domain.errors import ValueValidationError
from app.shared.domain.events import DomainEvent
from app.shared.events.bus import InMemoryEventBus
from app.shared.persistence.unit_of_work import InMemoryUnitOfWork
from tests.contexts.earth_observation.fakes import SCOPE, InMemorySceneRepository, make_scene

_GRID = RasterGrid(
    width=2, height=2, band_count=2, crs=CrsRef.wgs84(), origin_x=0.0, origin_y=2.0, pixel_size=1.0
)


def _dataset() -> InMemoryRaster:
    return InMemoryRaster(grid=_GRID, bands=[[0.0, 1.0, 2.0, 3.0], [4.0, 5.0, 6.0, 7.0]])


class _Loader:
    def __init__(self, dataset: RasterDataset | None = None, error: Exception | None = None):
        self._dataset = dataset
        self._error = error

    async def load(self, scene: Scene) -> RasterDataset:
        if self._error is not None:
            raise self._error
        assert self._dataset is not None
        return self._dataset


class _Masker:
    def __init__(self) -> None:
        self.applied = 0

    async def apply(self, dataset: RasterDataset, *, scene: Scene) -> RasterDataset:
        self.applied += 1
        return dataset


class _Thumbnailer:
    def __init__(self) -> None:
        self.rendered_band_counts: list[int] = []

    async def render(self, dataset: RasterDataset, *, scene: Scene) -> str:
        self.rendered_band_counts.append(dataset.grid.band_count)
        return f"thumbnails/{scene.id}/quicklook.webp"


def _registered_scene(*, cloud_pct: float | None = 10.0) -> Scene:
    scene = make_scene(cloud_pct=cloud_pct)
    scene.mark_downloaded(checksum_sha256="ab" * 32)
    scene.mark_validated()
    scene.register()
    scene.pull_events()
    return scene


def _spec(*steps: PipelineStep, bands: tuple[int, ...] | None = None) -> PipelineSpec:
    return PipelineSpec(version="1.0.0", steps=steps, band_selection=bands)


# --- PipelineSpec -------------------------------------------------------------------
def test_spec_validation_and_hash_stability() -> None:
    spec = _spec(PipelineStep.NORMALIZE, PipelineStep.THUMBNAIL)
    assert spec.spec_hash == _spec(PipelineStep.NORMALIZE, PipelineStep.THUMBNAIL).spec_hash
    assert spec.spec_hash != _spec(PipelineStep.NORMALIZE).spec_hash
    assert len(spec.spec_hash) == 64

    with pytest.raises(ValueValidationError):
        PipelineSpec(version="  ", steps=(PipelineStep.NORMALIZE,))
    with pytest.raises(ValueValidationError):
        PipelineSpec(version="v1", steps=())
    with pytest.raises(ValueValidationError):
        PipelineSpec(version="v1", steps=(PipelineStep.NORMALIZE, PipelineStep.NORMALIZE))
    with pytest.raises(ValueValidationError):
        PipelineSpec(version="v1", steps=(PipelineStep.BAND_SELECTION,))
    with pytest.raises(ValueValidationError):
        PipelineSpec(version="v1", steps=(PipelineStep.BAND_SELECTION,), band_selection=(-1,))


# --- Quality scoring -----------------------------------------------------------------
def test_score_quality() -> None:
    optical = AcquisitionMetadata(
        acquired_at=datetime(2024, 6, 1, tzinfo=UTC),
        sensor_type=SensorType.OPTICAL,
        cloud_cover=CloudCoverPercentage(value=25.0),
    )
    assert score_quality(optical).value == pytest.approx(0.75)

    unknown = AcquisitionMetadata(
        acquired_at=datetime(2024, 6, 1, tzinfo=UTC), sensor_type=SensorType.OPTICAL
    )
    assert score_quality(unknown).value == pytest.approx(0.75)

    sar = AcquisitionMetadata(
        acquired_at=datetime(2024, 6, 1, tzinfo=UTC), sensor_type=SensorType.SAR
    )
    assert score_quality(sar).value == 1.0


# --- Orchestration ----------------------------------------------------------------------
async def test_full_pipeline_reaches_processed_with_hooks() -> None:
    bus = InMemoryEventBus()
    published: list[DomainEvent] = []
    bus.subscribe(DomainEvent, published.append)

    scenes = InMemorySceneRepository()
    scene = _registered_scene(cloud_pct=20.0)
    await scenes.add(scene)

    masker = _Masker()
    thumbnailer = _Thumbnailer()
    service = PreprocessingService(
        scenes=scenes,
        uow=InMemoryUnitOfWork(bus),
        spec=_spec(
            PipelineStep.CLOUD_MASK,
            PipelineStep.BAND_SELECTION,
            PipelineStep.NORMALIZE,
            PipelineStep.THUMBNAIL,
            bands=(0,),
        ),
        loader=_Loader(_dataset()),
        cloud_masker=masker,
        thumbnailer=thumbnailer,
    )

    result = await service.preprocess(scene_id=scene.id, scope=SCOPE)

    assert scene.status is SceneStatus.PROCESSED
    assert result.status is SceneStatus.PROCESSED
    assert result.pipeline_version == "1.0.0"
    assert result.quality is not None and result.quality.value == pytest.approx(0.8)
    assert scene.quality == result.quality
    assert result.thumbnail_uri == f"thumbnails/{scene.id}/quicklook.webp"
    assert masker.applied == 1
    assert thumbnailer.rendered_band_counts == [1]  # thumbnail sees the band-selected raster
    assert any(isinstance(e, SceneProcessed) for e in published)


async def test_reprocess_from_available_uses_new_version() -> None:
    bus = InMemoryEventBus()
    published: list[DomainEvent] = []
    bus.subscribe(DomainEvent, published.append)

    scenes = InMemorySceneRepository()
    scene = _registered_scene()
    scene.start_preprocessing(pipeline_version="0.9.0")
    scene.mark_processed()
    scene.mark_tiled(tile_matrix_set=TileMatrixSetRef.web_mercator_quad())
    scene.mark_available()
    scene.pull_events()
    await scenes.add(scene)

    service = PreprocessingService(
        scenes=scenes,
        uow=InMemoryUnitOfWork(bus),
        spec=_spec(PipelineStep.NORMALIZE),
        loader=_Loader(_dataset()),
    )
    result = await service.preprocess(scene_id=scene.id, scope=SCOPE)

    assert result.pipeline_version == "1.0.0"
    assert scene.pipeline_version == "1.0.0"
    assert any(isinstance(e, SceneReprocessed) for e in published)
    assert scene.status is SceneStatus.PROCESSED


async def test_failure_marks_failed_and_raises() -> None:
    bus = InMemoryEventBus()
    published: list[DomainEvent] = []
    bus.subscribe(DomainEvent, published.append)

    scenes = InMemorySceneRepository()
    scene = _registered_scene()
    await scenes.add(scene)

    service = PreprocessingService(
        scenes=scenes,
        uow=InMemoryUnitOfWork(bus),
        spec=_spec(PipelineStep.NORMALIZE),
        loader=_Loader(error=RuntimeError("corrupt raster")),
    )
    with pytest.raises(PreprocessingError) as exc:
        await service.preprocess(scene_id=scene.id, scope=SCOPE)

    assert "corrupt raster" in str(exc.value)
    assert scene.status is SceneStatus.FAILED
    failed = [e for e in published if isinstance(e, SceneProcessingFailed)]
    assert failed and "corrupt raster" in failed[0].reason


def test_missing_hooks_fail_at_construction() -> None:
    with pytest.raises(HookNotConfiguredError):
        PreprocessingService(
            scenes=InMemorySceneRepository(),
            uow=InMemoryUnitOfWork(),
            spec=_spec(PipelineStep.CLOUD_MASK),
            loader=_Loader(_dataset()),
        )
    with pytest.raises(HookNotConfiguredError):
        PreprocessingService(
            scenes=InMemorySceneRepository(),
            uow=InMemoryUnitOfWork(),
            spec=_spec(PipelineStep.THUMBNAIL),
            loader=_Loader(_dataset()),
        )


@pytest.mark.parametrize(
    ("step", "attr", "needle"),
    [
        (PipelineStep.CLOUD_MASK, "_cloud_masker", "CloudMasker"),
        (PipelineStep.THUMBNAIL, "_thumbnailer", "ThumbnailRenderer"),
    ],
)
async def test_hook_removed_after_construction_fails_with_domain_error(
    step: PipelineStep, attr: str, needle: str
) -> None:
    scenes = InMemorySceneRepository()
    scene = _registered_scene()
    await scenes.add(scene)
    service = PreprocessingService(
        scenes=scenes,
        uow=InMemoryUnitOfWork(),
        spec=_spec(step),
        loader=_Loader(_dataset()),
        cloud_masker=_Masker(),
        thumbnailer=_Thumbnailer(),
    )
    setattr(service, attr, None)  # wiring drift after construction must not rely on `assert`
    with pytest.raises(PreprocessingError, match=needle):
        await service.preprocess(scene_id=scene.id, scope=SCOPE)
    assert scene.status is SceneStatus.FAILED


async def test_band_selection_without_indexes_fails_with_domain_error() -> None:
    scenes = InMemorySceneRepository()
    scene = _registered_scene()
    await scenes.add(scene)
    spec = _spec(PipelineStep.BAND_SELECTION, bands=(0,))
    object.__setattr__(spec, "band_selection", None)  # bypass the frozen VO validation
    service = PreprocessingService(
        scenes=scenes, uow=InMemoryUnitOfWork(), spec=spec, loader=_Loader(_dataset())
    )
    with pytest.raises(PreprocessingError, match="band_selection"):
        await service.preprocess(scene_id=scene.id, scope=SCOPE)
