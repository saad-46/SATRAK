"""Shared builders for the Earth Observation API tests (Stories 17-19).

The ``eo_env`` client/container fixture lives in ``tests/api/conftest.py`` (auto-discovered
by pytest); these are the plain data builders test modules import.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.api.v1.endpoints.earth_observation.composition import EarthObservationApi
from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SensorType
from app.contexts.earth_observation.domain.value_objects import (
    AcquisitionMetadata,
    Band,
    BandSet,
    CloudCoverPercentage,
    CrsRef,
    ProviderSceneId,
    QualityScore,
    Resolution,
    TileCoord,
    TileMatrixSetRef,
)
from app.shared.value_objects.geo import BoundingBox

# Jurisdictions: the default test user holds the EO permissions in HOME only.
HOME = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
OTHER = uuid.UUID("00000000-0000-4000-8000-0000000000b2")

# An AOI/scene footprint over southern India; a disjoint far box for negative filters.
AOI_BBOX = BoundingBox(min_longitude=76.0, min_latitude=12.0, max_longitude=78.0, max_latitude=14.0)
FAR_BBOX = BoundingBox(
    min_longitude=100.0, min_latitude=40.0, max_longitude=101.0, max_latitude=41.0
)


def make_available_scene(
    *,
    native_id: str = "S2A_1",
    provider: str = "sentinel-2",
    acquired_at: datetime | None = None,
    bbox: BoundingBox = AOI_BBOX,
    cloud_pct: float = 7.5,
    pipeline_version: str = "1.0.0",
    jurisdiction_id: uuid.UUID = HOME,
) -> Scene:
    """A fully-processed, AVAILABLE scene with bands, CRS, quality, and sun geometry."""
    scene = Scene.create(
        provider_scene_id=ProviderSceneId(provider=provider, native_id=native_id),
        bounding_box=bbox,
        jurisdiction_id=jurisdiction_id,
        acquisition=AcquisitionMetadata(
            acquired_at=acquired_at or datetime(2024, 6, 1, 5, 32, tzinfo=UTC),
            sensor_type=SensorType.OPTICAL,
            cloud_cover=CloudCoverPercentage(value=cloud_pct),
            sun_azimuth_deg=121.4,
            sun_elevation_deg=67.2,
        ),
        bands=BandSet(
            bands=(
                Band(name="B04", index=3, wavelength_nm=665.0, resolution=Resolution(gsd_m=10.0)),
            )
        ),
    )
    scene.mark_downloaded(checksum_sha256="ab" * 32)
    scene.mark_validated()
    scene.register(crs=CrsRef(epsg=32643), quality=QualityScore(value=0.9))
    scene.start_preprocessing(pipeline_version=pipeline_version)
    scene.mark_processed()
    scene.mark_tiled(tile_matrix_set=TileMatrixSetRef.web_mercator_quad())
    scene.mark_available()
    scene.pull_events()
    return scene


def make_discovered_scene(
    native_id: str = "S2A_new",
    *,
    bbox: BoundingBox = AOI_BBOX,
    jurisdiction_id: uuid.UUID = HOME,
) -> Scene:
    scene = Scene.create(
        provider_scene_id=ProviderSceneId(provider="sentinel-2", native_id=native_id),
        bounding_box=bbox,
        jurisdiction_id=jurisdiction_id,
        acquisition=AcquisitionMetadata(
            acquired_at=datetime(2024, 1, 15, tzinfo=UTC), sensor_type=SensorType.OPTICAL
        ),
    )
    scene.pull_events()
    return scene


def make_aoi(
    name: str = "Ward 12", *, bbox: BoundingBox = AOI_BBOX, jurisdiction_id: uuid.UUID = HOME
) -> AreaOfInterest:
    aoi = AreaOfInterest.create(name=name, bounding_box=bbox, jurisdiction_id=jurisdiction_id)
    aoi.pull_events()
    return aoi


async def store_tile(
    container: EarthObservationApi,
    *,
    scene: Scene,
    z: int,
    x: int,
    y: int,
    data: bytes = b"tile-bytes",
    version: str = "1.0.0",
) -> str:
    key = container.keys.tile_key(
        tile_matrix_set=TileMatrixSetRef.web_mercator_quad(),
        scene_id=scene.id,
        pipeline_version=version,
        tile=TileCoord(z=z, x=x, y=y),
        extension="bin",
    )
    await container.storage.save(
        key, data, content_type="application/octet-stream", filename="tile.bin"
    )
    return key
