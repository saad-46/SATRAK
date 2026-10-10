"""Story 11 — scene validation rules and metadata extraction/registration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.contexts.earth_observation.application.ingestion.validate_scene import (
    SceneValidator,
    ValidateSceneService,
    ValidationContext,
    ValidationPolicy,
    issues_summary,
)
from app.contexts.earth_observation.application.metadata.extract_metadata import (
    MetadataExtractionService,
    merge_bands,
    merge_crs,
)
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SceneStatus, SensorType
from app.contexts.earth_observation.domain.events import ImageStored, MetadataExtracted
from app.contexts.earth_observation.domain.ports.metadata_extractor import ExtractedMetadata
from app.contexts.earth_observation.domain.value_objects import (
    AcquisitionMetadata,
    Band,
    BandSet,
    CrsRef,
    ProviderSceneId,
    Resolution,
)
from app.shared.domain.clock import utcnow
from app.shared.domain.events import DomainEvent
from app.shared.events.bus import InMemoryEventBus
from app.shared.persistence.unit_of_work import InMemoryUnitOfWork
from app.shared.value_objects.geo import BoundingBox
from tests.contexts.earth_observation.fakes import InMemorySceneRepository, make_scene

_SHA = "ab" * 32


def _downloaded_scene(native_id: str = "S2A_1", *, cloud_pct: float | None = 5.0) -> Scene:
    scene = make_scene(native_id, cloud_pct=cloud_pct)
    scene.mark_downloaded(checksum_sha256=_SHA)
    scene.pull_events()
    return scene


def _ctx(scene: Scene, **kwargs: object) -> ValidationContext:
    return ValidationContext(scene=scene, now=utcnow(), **kwargs)  # type: ignore[arg-type]


# --- Individual rules through the validator ---------------------------------------
def test_valid_scene_passes_all_default_rules() -> None:
    report = SceneValidator().validate(_ctx(_downloaded_scene(), expected_provider="sentinel-2"))
    assert report.ok is True
    assert report.codes == ()


def test_provider_mismatch() -> None:
    report = SceneValidator().validate(_ctx(_downloaded_scene(), expected_provider="landsat"))
    assert "provider_mismatch" in report.codes


def test_acquisition_in_future() -> None:
    scene = _downloaded_scene()
    ctx = ValidationContext(scene=scene, now=scene.acquisition.acquired_at - timedelta(days=1))
    report = SceneValidator().validate(ctx)
    assert "acquisition_in_future" in report.codes


def test_missing_bands_and_resolution_rules() -> None:
    scene = _downloaded_scene()
    report = SceneValidator().validate(_ctx(scene, required_band_names=("B04", "B08")))
    assert "missing_bands" in report.codes

    coarse = BandSet(bands=(Band(name="B01", index=0, resolution=Resolution(gsd_m=60.0)),))
    scene_with_bands = _downloaded_scene("S2A_2")
    scene_with_bands.bands = coarse
    report = SceneValidator().validate(_ctx(scene_with_bands, max_gsd_m=10.0))
    assert "resolution_too_coarse" in report.codes


def test_cloud_cover_exceeded() -> None:
    scene = _downloaded_scene(cloud_pct=45.0)
    report = SceneValidator().validate(_ctx(scene, max_cloud_cover_pct=20.0))
    assert "cloud_cover_exceeded" in report.codes


def test_checksum_rules() -> None:
    not_downloaded = make_scene("fresh")
    not_downloaded.pull_events()
    assert "missing_checksum" in SceneValidator().validate(_ctx(not_downloaded)).codes

    malformed = make_scene("bad-sum")
    malformed.mark_downloaded(checksum_sha256="not-a-digest")
    malformed.pull_events()
    assert "malformed_checksum" in SceneValidator().validate(_ctx(malformed)).codes

    mismatch = SceneValidator().validate(
        _ctx(_downloaded_scene("S2A_3"), expected_checksum_sha256="cd" * 32)
    )
    assert "checksum_mismatch" in mismatch.codes

    match = SceneValidator().validate(
        _ctx(_downloaded_scene("S2A_4"), expected_checksum_sha256=_SHA.upper())
    )
    assert "checksum_mismatch" not in match.codes


def test_sar_scene_valid_without_cloud() -> None:
    scene = Scene.create(
        provider_scene_id=ProviderSceneId(provider="sentinel-1", native_id="S1A_1"),
        bounding_box=BoundingBox(
            min_longitude=0.0, min_latitude=0.0, max_longitude=1.0, max_latitude=1.0
        ),
        acquisition=AcquisitionMetadata(
            acquired_at=datetime(2024, 6, 1, tzinfo=UTC), sensor_type=SensorType.SAR
        ),
    )
    scene.mark_downloaded(checksum_sha256=_SHA)
    scene.pull_events()
    assert SceneValidator().validate(_ctx(scene)).ok is True


def test_issues_summary_formats_lines() -> None:
    report = SceneValidator().validate(_ctx(make_scene("summary")))
    lines = issues_summary(report)
    assert lines and all(":" in line for line in lines)


# --- Service behaviour ---------------------------------------------------------------
async def test_service_marks_validated_on_pass() -> None:
    scenes = InMemorySceneRepository()
    scene = _downloaded_scene()
    await scenes.add(scene)
    service = ValidateSceneService(
        scenes=scenes,
        uow=InMemoryUnitOfWork(),
        policy=ValidationPolicy(expected_provider="sentinel-2"),
    )
    report = await service.validate(scene_id=scene.id)
    assert report.ok is True
    assert scene.status is SceneStatus.VALIDATED


async def test_service_rejects_on_failure_with_codes() -> None:
    scenes = InMemorySceneRepository()
    scene = _downloaded_scene(cloud_pct=90.0)
    await scenes.add(scene)
    service = ValidateSceneService(
        scenes=scenes,
        uow=InMemoryUnitOfWork(),
        policy=ValidationPolicy(max_cloud_cover_pct=10.0),
    )
    report = await service.validate(scene_id=scene.id)
    assert report.ok is False
    assert scene.status is SceneStatus.REJECTED
    assert scene.rejection_reason is not None
    assert "cloud_cover_exceeded" in scene.rejection_reason


# --- Metadata extraction ----------------------------------------------------------------
class _FakeExtractor:
    def __init__(self, extracted: ExtractedMetadata) -> None:
        self.extracted = extracted
        self.requested_uris: list[str] = []

    async def extract(self, *, source_uri: str) -> ExtractedMetadata:
        self.requested_uris.append(source_uri)
        return self.extracted


async def test_extraction_merges_and_registers() -> None:
    bus = InMemoryEventBus()
    published: list[DomainEvent] = []
    bus.subscribe(DomainEvent, published.append)

    scenes = InMemorySceneRepository()
    scene = _downloaded_scene()
    scene.mark_validated()
    scene.pull_events()
    await scenes.add(scene)

    file_bands = BandSet(bands=(Band(name="B04", index=0, resolution=Resolution(gsd_m=10.0)),))
    extractor = _FakeExtractor(
        ExtractedMetadata(acquisition=scene.acquisition, bands=file_bands, crs=CrsRef(epsg=32643))
    )
    service = MetadataExtractionService(
        extractor=extractor, scenes=scenes, uow=InMemoryUnitOfWork(bus)
    )

    extracted = await service.extract_and_register(scene_id=scene.id, source_uri="raw/x/y.zip")

    assert extractor.requested_uris == ["raw/x/y.zip"]
    assert extracted.crs == CrsRef(epsg=32643)
    assert scene.status is SceneStatus.REGISTERED
    assert scene.crs == CrsRef(epsg=32643)
    assert scene.bands == file_bands
    kinds = [type(e) for e in published]
    assert MetadataExtracted in kinds
    assert ImageStored in kinds


def test_merge_prefers_extracted_and_falls_back_to_claims() -> None:
    claimed = BandSet(bands=(Band(name="claimed", index=0),))
    extracted = BandSet(bands=(Band(name="extracted", index=0),))
    assert merge_bands(claimed, extracted) is extracted
    assert merge_bands(claimed, None) is claimed
    assert merge_crs(None, CrsRef.wgs84()) == CrsRef.wgs84()
    assert merge_crs(CrsRef.wgs84(), None) == CrsRef.wgs84()


def test_passing_band_crs_and_resolution_branches() -> None:
    scene = _downloaded_scene("S2A_pass")
    scene.bands = BandSet(bands=(Band(name="B04", index=0, resolution=Resolution(gsd_m=10.0)),))
    scene.crs = CrsRef(epsg=32643)
    report = SceneValidator().validate(_ctx(scene, required_band_names=("B04",), max_gsd_m=20.0))
    assert report.ok is True


def test_degenerate_bounding_box_rule() -> None:
    scene = Scene.create(
        provider_scene_id=ProviderSceneId(provider="p", native_id="line"),
        bounding_box=BoundingBox(
            min_longitude=10.0, min_latitude=10.0, max_longitude=10.0, max_latitude=11.0
        ),
        acquisition=AcquisitionMetadata(
            acquired_at=datetime(2024, 6, 1, tzinfo=UTC), sensor_type=SensorType.OPTICAL
        ),
    )
    scene.mark_downloaded(checksum_sha256=_SHA)
    scene.pull_events()
    assert "degenerate_bounding_box" in SceneValidator().validate(_ctx(scene)).codes
