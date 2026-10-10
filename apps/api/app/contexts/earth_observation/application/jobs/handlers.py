"""Default job handlers wiring the pipeline services (Epic 3 Story 16).

Each handler adapts one application service to the ``JobHandler`` contract: it reads the
job payload, invokes the service, reports coarse progress, and contributes any payload
fields the next chain stage needs (e.g. ingest hands the raw asset URI to metadata
extraction). A validation rejection *halts* the chain instead of failing the job — a
rejected scene is a business outcome, not an execution error.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.contexts.earth_observation.application.ingestion.download_scene import (
    SceneDownloadService,
)
from app.contexts.earth_observation.application.ingestion.validate_scene import (
    ValidateSceneService,
)
from app.contexts.earth_observation.application.jobs.runner import (
    TASK_EXTRACT_METADATA,
    TASK_GENERATE_THUMBNAIL,
    TASK_GENERATE_TILES,
    TASK_INGEST_SCENE,
    TASK_PREPROCESS_SCENE,
    TASK_VALIDATE_SCENE,
    HandlerResult,
    JobHandler,
    ProgressReporter,
    require_field,
)
from app.contexts.earth_observation.application.metadata.extract_metadata import (
    MetadataExtractionService,
)
from app.contexts.earth_observation.application.preprocessing.hooks import RasterDatasetLoader
from app.contexts.earth_observation.application.preprocessing.preprocess_scene import (
    PreprocessingService,
)
from app.contexts.earth_observation.application.preprocessing.thumbnails import ThumbnailService
from app.contexts.earth_observation.application.tiling.generate_tiles import TilingService
from app.contexts.earth_observation.domain.ports.repositories import SceneRepository
from app.shared.domain.identifiers import parse_id


def build_default_handlers(
    *,
    download: SceneDownloadService,
    validation: ValidateSceneService,
    metadata: MetadataExtractionService,
    preprocessing: PreprocessingService,
    tiling: TilingService,
    thumbnails: ThumbnailService,
    scenes: SceneRepository,
    loader: RasterDatasetLoader,
) -> dict[str, JobHandler]:
    """The task-name -> handler map for the spec §12 job catalogue."""

    async def ingest(payload: Mapping[str, str], *, progress: ProgressReporter) -> HandlerResult:
        scene_id = parse_id(require_field(payload, "scene_id"))
        reference = await download.download(scene_id=scene_id)
        await progress(1.0)
        return HandlerResult(payload_update={"source_uri": reference.storage_key})

    async def validate(payload: Mapping[str, str], *, progress: ProgressReporter) -> HandlerResult:
        scene_id = parse_id(require_field(payload, "scene_id"))
        report = await validation.validate(
            scene_id=scene_id,
            expected_checksum_sha256=payload.get("expected_checksum_sha256"),
        )
        await progress(1.0)
        # Rejection is an outcome: stop the pipeline, don't retry.
        return HandlerResult(
            payload_update={"source_uri": require_field(payload, "source_uri")},
            halt_chain=not report.ok,
        )

    async def extract(payload: Mapping[str, str], *, progress: ProgressReporter) -> HandlerResult:
        scene_id = parse_id(require_field(payload, "scene_id"))
        await metadata.extract_and_register(
            scene_id=scene_id, source_uri=require_field(payload, "source_uri")
        )
        await progress(1.0)
        return HandlerResult()

    async def preprocess(
        payload: Mapping[str, str], *, progress: ProgressReporter
    ) -> HandlerResult:
        scene_id = parse_id(require_field(payload, "scene_id"))
        await progress(0.1)
        await preprocessing.preprocess(scene_id=scene_id)
        await progress(1.0)
        return HandlerResult()

    async def tiles(payload: Mapping[str, str], *, progress: ProgressReporter) -> HandlerResult:
        scene_id = parse_id(require_field(payload, "scene_id"))
        await progress(0.1)
        await tiling.generate(scene_id=scene_id)
        await progress(1.0)
        return HandlerResult()

    async def thumbnail(payload: Mapping[str, str], *, progress: ProgressReporter) -> HandlerResult:
        """Standalone thumbnail (re-)generation outside the pipeline chain."""
        scene_id = parse_id(require_field(payload, "scene_id"))
        scene = await scenes.require(scene_id)
        dataset = await loader.load(scene)
        await thumbnails.generate(dataset, scene=scene)
        await progress(1.0)
        return HandlerResult()

    return {
        TASK_INGEST_SCENE: ingest,
        TASK_VALIDATE_SCENE: validate,
        TASK_EXTRACT_METADATA: extract,
        TASK_PREPROCESS_SCENE: preprocess,
        TASK_GENERATE_TILES: tiles,
        TASK_GENERATE_THUMBNAIL: thumbnail,
    }
