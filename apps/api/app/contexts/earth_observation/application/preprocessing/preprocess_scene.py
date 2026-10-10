"""Preprocessing orchestration (Epic 3 Story 13).

Drives one scene through the versioned pipeline: transition to ``PREPROCESSING``
(fresh run or reprocess), execute the spec's steps over the windowed raster engine,
score quality, and land on ``PROCESSED`` — or ``FAILED`` with the cause recorded and
re-raised for the job layer's retry policy. ``SceneProcessed`` (the future AI trigger,
ADR-0009) and ``SceneProcessingFailed`` dispatch through the Unit of Work.

No AI, no detection — the pipeline ends where analysis-ready imagery begins.
"""

from __future__ import annotations

from app.contexts.earth_observation.application.dto import PreprocessingResult
from app.contexts.earth_observation.application.preprocessing.hooks import (
    CloudMasker,
    RasterDatasetLoader,
    ThumbnailRenderer,
)
from app.contexts.earth_observation.application.preprocessing.pipeline_spec import (
    PipelineSpec,
    PipelineStep,
)
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SceneStatus, SensorType
from app.contexts.earth_observation.domain.ports.repositories import SceneRepository
from app.contexts.earth_observation.domain.value_objects.acquisition import AcquisitionMetadata
from app.contexts.earth_observation.domain.value_objects.quality import QualityScore
from app.contexts.earth_observation.infrastructure.raster.dataset import RasterDataset
from app.contexts.earth_observation.infrastructure.raster.ops import (
    minmax_normalize,
    select_bands,
)
from app.shared.domain.errors import BusinessRuleViolation
from app.shared.domain.identifiers import EntityId
from app.shared.domain.scope import AccessScope
from app.shared.persistence.scoped import ScopedRepository
from app.shared.persistence.unit_of_work import UnitOfWork

_UNKNOWN_CLOUD_QUALITY = 0.75


class PreprocessingError(BusinessRuleViolation):
    """A pipeline step failed; the scene was moved to FAILED (retry-able)."""

    code = "preprocessing_failed"


class HookNotConfiguredError(BusinessRuleViolation):
    """The spec requests a step whose hook is not wired."""

    code = "preprocessing_hook_missing"


def score_quality(acquisition: AcquisitionMetadata) -> QualityScore:
    """Deterministic capture-quality score.

    Optical: clear-sky fraction (1 - cloud); unknown cloud cover is penalized rather
    than trusted. SAR is weather-independent and scores full.
    """
    if acquisition.sensor_type is not SensorType.OPTICAL:
        return QualityScore(value=1.0)
    if acquisition.cloud_cover is None:
        return QualityScore(value=_UNKNOWN_CLOUD_QUALITY)
    return QualityScore(value=round(1.0 - acquisition.cloud_cover.fraction, 6))


class PreprocessingService:
    """Executes the versioned preprocessing pipeline for one scene."""

    def __init__(
        self,
        *,
        scenes: SceneRepository,
        uow: UnitOfWork,
        spec: PipelineSpec,
        loader: RasterDatasetLoader,
        cloud_masker: CloudMasker | None = None,
        thumbnailer: ThumbnailRenderer | None = None,
    ) -> None:
        self._scenes = scenes
        self._uow = uow
        self._spec = spec
        self._loader = loader
        self._cloud_masker = cloud_masker
        self._thumbnailer = thumbnailer
        self._require_hooks()

    def _require_hooks(self) -> None:
        """Spec/wiring mismatches fail at construction, not mid-pipeline."""
        if PipelineStep.CLOUD_MASK in self._spec.steps and self._cloud_masker is None:
            raise HookNotConfiguredError("spec includes cloud_mask but no CloudMasker is wired")
        if PipelineStep.THUMBNAIL in self._spec.steps and self._thumbnailer is None:
            raise HookNotConfiguredError(
                "spec includes thumbnail but no ThumbnailRenderer is wired"
            )

    async def preprocess(self, *, scene_id: EntityId, scope: AccessScope) -> PreprocessingResult:
        scenes = ScopedRepository(self._scenes, scope)
        scene = await scenes.require(scene_id)
        if scene.status is SceneStatus.AVAILABLE:
            scene.reprocess(pipeline_version=self._spec.version)
        else:
            scene.start_preprocessing(pipeline_version=self._spec.version)
        await scenes.update(scene)
        self._uow.track(scene)
        await self._uow.commit()

        try:
            thumbnail_uri = await self._run_steps(scene)
        except Exception as exc:
            scene.mark_failed(reason=str(exc))
            await scenes.update(scene)
            self._uow.track(scene)
            await self._uow.commit()
            raise PreprocessingError(
                f"pipeline {self._spec.version} failed for scene {scene_id}: {exc}"
            ) from exc

        quality = score_quality(scene.acquisition)
        scene.mark_processed(quality=quality)
        await scenes.update(scene)
        self._uow.track(scene)
        await self._uow.commit()
        return PreprocessingResult(
            scene_id=scene.id,
            status=scene.status,
            pipeline_version=self._spec.version,
            quality=quality,
            thumbnail_uri=thumbnail_uri,
        )

    async def _run_steps(self, scene: Scene) -> str | None:
        dataset: RasterDataset = await self._loader.load(scene)
        thumbnail_uri: str | None = None
        for step in self._spec.steps:
            if step is PipelineStep.CLOUD_MASK:
                if self._cloud_masker is None:
                    raise HookNotConfiguredError("cloud_mask step has no CloudMasker wired")
                dataset = await self._cloud_masker.apply(dataset, scene=scene)
            elif step is PipelineStep.BAND_SELECTION:
                if not self._spec.band_selection:
                    raise PreprocessingError("band_selection step has no band indexes")
                dataset = select_bands(dataset, bands=self._spec.band_selection)
            elif step is PipelineStep.NORMALIZE:
                dataset = minmax_normalize(dataset)
            else:  # PipelineStep.THUMBNAIL
                if self._thumbnailer is None:
                    raise HookNotConfiguredError("thumbnail step has no ThumbnailRenderer wired")
                thumbnail_uri = await self._thumbnailer.render(dataset, scene=scene)
        return thumbnail_uri
