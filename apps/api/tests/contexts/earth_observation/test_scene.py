"""Story 3 — Scene aggregate lifecycle, invariants, and events."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SceneStatus, SensorType
from app.contexts.earth_observation.domain.events import (
    ImageArchived,
    ImageDiscovered,
    ImageDownloaded,
    ImageRejected,
    SceneAvailable,
    SceneProcessed,
    SceneReprocessed,
    TileGenerated,
)
from app.contexts.earth_observation.domain.value_objects import (
    AcquisitionMetadata,
    CrsRef,
    ProviderSceneId,
    QualityScore,
    TileMatrixSetRef,
)
from app.shared.domain.errors import InvariantViolation
from app.shared.value_objects.geo import BoundingBox


def _make_scene() -> Scene:
    return Scene.create(
        provider_scene_id=ProviderSceneId(provider="sentinel-2", native_id="S2A_1"),
        bounding_box=BoundingBox(
            min_longitude=10.0, min_latitude=10.0, max_longitude=11.0, max_latitude=11.0
        ),
        acquisition=AcquisitionMetadata(
            acquired_at=datetime(2024, 6, 1, tzinfo=UTC), sensor_type=SensorType.OPTICAL
        ),
    )


def _advance_to_available(scene: Scene) -> None:
    scene.mark_downloaded(checksum_sha256="abc")
    scene.mark_validated()
    scene.register()
    scene.start_preprocessing(pipeline_version="v1")
    scene.mark_processed()
    scene.mark_tiled(tile_matrix_set=TileMatrixSetRef.web_mercator_quad())
    scene.mark_available()


def test_create_records_discovered_event() -> None:
    scene = _make_scene()
    assert scene.status is SceneStatus.DISCOVERED
    events = scene.pull_events()
    assert len(events) == 1
    assert isinstance(events[0], ImageDiscovered)
    assert events[0].provider_scene_id == "sentinel-2:S2A_1"
    assert scene.has_pending_events is False


def test_happy_path_reaches_available_with_events() -> None:
    scene = _make_scene()
    scene.pull_events()  # discard discovered
    _advance_to_available(scene)
    assert scene.is_available is True
    assert scene.pipeline_version == "v1"
    assert scene.checksum_sha256 == "abc"
    kinds = [type(e) for e in scene.pull_events()]
    assert ImageDownloaded in kinds
    assert SceneProcessed in kinds
    assert TileGenerated in kinds
    assert SceneAvailable in kinds


def test_version_bumps_on_transition() -> None:
    scene = _make_scene()
    assert scene.version == 1
    scene.mark_downloaded(checksum_sha256="abc")
    assert scene.version == 2


def test_invalid_transition_rejected() -> None:
    scene = _make_scene()
    with pytest.raises(InvariantViolation):
        scene.mark_validated()  # cannot validate straight from DISCOVERED


def test_reject_requires_reason_and_is_terminal() -> None:
    scene = _make_scene()
    with pytest.raises(InvariantViolation):
        scene.reject(reason="  ")
    scene.reject(reason="corrupt download")
    assert scene.status is SceneStatus.REJECTED
    assert scene.is_terminal is True
    assert any(isinstance(e, ImageRejected) for e in scene.pull_events())
    with pytest.raises(InvariantViolation):
        scene.mark_downloaded(checksum_sha256="abc")  # no transitions out of REJECTED


def test_mark_downloaded_requires_checksum() -> None:
    scene = _make_scene()
    with pytest.raises(InvariantViolation):
        scene.mark_downloaded(checksum_sha256="   ")


def test_failure_then_retry() -> None:
    scene = _make_scene()
    scene.mark_downloaded(checksum_sha256="abc")
    scene.mark_validated()
    scene.register()
    scene.start_preprocessing(pipeline_version="v1")
    scene.mark_failed(reason="gdal error")
    assert scene.status is SceneStatus.FAILED
    scene.start_preprocessing(pipeline_version="v1")  # retry
    assert scene.status is SceneStatus.PREPROCESSING


def test_reprocess_from_available() -> None:
    scene = _make_scene()
    _advance_to_available(scene)
    scene.pull_events()
    scene.reprocess(pipeline_version="v2")
    assert scene.status is SceneStatus.PREPROCESSING
    assert scene.pipeline_version == "v2"
    assert any(isinstance(e, SceneReprocessed) for e in scene.pull_events())


def test_reprocess_requires_new_version() -> None:
    scene = _make_scene()
    _advance_to_available(scene)
    with pytest.raises(InvariantViolation):
        scene.reprocess(pipeline_version="v1")


def test_archive_and_restore() -> None:
    scene = _make_scene()
    _advance_to_available(scene)
    scene.pull_events()
    scene.archive()
    assert scene.status is SceneStatus.ARCHIVED
    assert any(isinstance(e, ImageArchived) for e in scene.pull_events())
    scene.restore_from_archive()
    assert scene.is_available is True


def test_link_aoi_is_idempotent() -> None:
    from app.shared.domain.identifiers import new_id

    scene = _make_scene()
    aoi_id = new_id()
    scene.link_aoi(aoi_id)
    v = scene.version
    scene.link_aoi(aoi_id)  # no-op
    assert scene.aoi_ids == {aoi_id}
    assert scene.version == v


def test_register_sets_crs_and_quality() -> None:
    scene = _make_scene()
    scene.mark_downloaded(checksum_sha256="abc")
    scene.mark_validated()
    scene.register(crs=CrsRef.wgs84(), quality=QualityScore(value=0.9))
    assert scene.crs == CrsRef.wgs84()
    assert scene.quality == QualityScore(value=0.9)


@pytest.mark.parametrize("blank", ["", "   "])
def test_empty_string_guards(blank: str) -> None:
    scene = _make_scene()
    scene.mark_downloaded(checksum_sha256="abc")
    scene.mark_validated()
    scene.register()
    with pytest.raises(InvariantViolation):
        scene.start_preprocessing(pipeline_version=blank)
    scene.start_preprocessing(pipeline_version="v1")
    with pytest.raises(InvariantViolation):
        scene.mark_failed(reason=blank)


def test_reprocess_requires_non_blank_version() -> None:
    scene = _make_scene()
    _advance_to_available(scene)
    with pytest.raises(InvariantViolation):
        scene.reprocess(pipeline_version="   ")


def test_processed_state_requires_pipeline_version_invariant() -> None:
    with pytest.raises(InvariantViolation):
        Scene(
            provider_scene_id=ProviderSceneId(provider="p", native_id="n"),
            bounding_box=BoundingBox(
                min_longitude=0.0, min_latitude=0.0, max_longitude=1.0, max_latitude=1.0
            ),
            acquisition=AcquisitionMetadata(
                acquired_at=datetime(2024, 6, 1, tzinfo=UTC), sensor_type=SensorType.OPTICAL
            ),
            status=SceneStatus.PROCESSED,  # missing pipeline_version
        )


def test_mark_processed_without_pipeline_version_raises_explicitly() -> None:
    scene = _make_scene()
    scene.mark_downloaded(checksum_sha256="ab" * 32)
    scene.mark_validated()
    scene.register()
    scene.start_preprocessing(pipeline_version="1.0.0")
    scene.pipeline_version = None  # simulate inconsistent state; must not rely on `assert`
    with pytest.raises(InvariantViolation):
        scene.mark_processed()


def test_rejected_state_requires_reason_invariant() -> None:
    with pytest.raises(InvariantViolation):
        Scene(
            provider_scene_id=ProviderSceneId(provider="p", native_id="n"),
            bounding_box=BoundingBox(
                min_longitude=0.0, min_latitude=0.0, max_longitude=1.0, max_latitude=1.0
            ),
            acquisition=AcquisitionMetadata(
                acquired_at=datetime(2024, 6, 1, tzinfo=UTC), sensor_type=SensorType.OPTICAL
            ),
            status=SceneStatus.REJECTED,  # missing rejection_reason
        )
