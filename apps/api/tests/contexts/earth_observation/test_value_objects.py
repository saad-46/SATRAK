"""Story 2 — Earth Observation value objects."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.contexts.earth_observation.domain.enums import SensorType
from app.contexts.earth_observation.domain.value_objects import (
    WEB_MERCATOR_QUAD,
    AcquisitionMetadata,
    Band,
    BandSet,
    CloudCoverPercentage,
    CrsRef,
    ProviderCapabilities,
    ProviderSceneId,
    QualityScore,
    Resolution,
    TileCoord,
    TileMatrixSetRef,
)
from app.shared.domain.errors import ValueValidationError


# --- ProviderSceneId ---------------------------------------------------------
def test_provider_scene_id_strips_and_str() -> None:
    psid = ProviderSceneId(provider="  sentinel-2  ", native_id=" S2A_123 ")
    assert psid.provider == "sentinel-2"
    assert psid.native_id == "S2A_123"
    assert str(psid) == "sentinel-2:S2A_123"


@pytest.mark.parametrize(("provider", "native"), [("", "x"), ("p", ""), ("   ", "x")])
def test_provider_scene_id_requires_both(provider: str, native: str) -> None:
    with pytest.raises(ValueValidationError):
        ProviderSceneId(provider=provider, native_id=native)


# --- Resolution --------------------------------------------------------------
def test_resolution_valid() -> None:
    r = Resolution(gsd_m=0.5)
    assert r.gsd_cm == 50.0
    assert r.is_sub_meter is True
    assert Resolution(gsd_m=10.0).is_sub_meter is False
    assert r.is_finer_than(Resolution(gsd_m=10.0)) is True


@pytest.mark.parametrize("gsd", [0.0, -1.0, float("inf"), float("nan")])
def test_resolution_invalid(gsd: float) -> None:
    with pytest.raises(ValueValidationError):
        Resolution(gsd_m=gsd)


# --- Band / BandSet ----------------------------------------------------------
def test_band_valid_and_strip() -> None:
    b = Band(name="  B04 ", index=3, common_name="red", wavelength_nm=665.0)
    assert b.name == "B04"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "", "index": 0},
        {"name": "B1", "index": -1},
        {"name": "B1", "index": 0, "wavelength_nm": 0.0},
        {"name": "B1", "index": 0, "wavelength_nm": -5.0},
    ],
)
def test_band_invalid(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueValidationError):
        Band(**kwargs)  # type: ignore[arg-type]


def test_bandset_valid_helpers() -> None:
    bs = BandSet(bands=(Band(name="B02", index=1), Band(name="B03", index=2)))
    assert len(bs) == 2
    assert bs.names == ("B02", "B03")
    assert bs.by_name("B03") is not None
    assert bs.by_name("missing") is None


def test_bandset_accepts_list_and_is_hashable() -> None:
    bs = BandSet(bands=[Band(name="B1", index=0)])  # type: ignore[arg-type]
    assert isinstance(bs.bands, tuple)
    assert hash(bs)  # frozen + tuple => hashable


def test_bandset_rejects_empty_and_duplicates() -> None:
    with pytest.raises(ValueValidationError):
        BandSet(bands=())
    with pytest.raises(ValueValidationError):
        BandSet(bands=(Band(name="B1", index=0), Band(name="B1", index=1)))
    with pytest.raises(ValueValidationError):
        BandSet(bands=(Band(name="B1", index=0), Band(name="B2", index=0)))


# --- CrsRef ------------------------------------------------------------------
def test_crs_ref() -> None:
    assert CrsRef.wgs84().is_wgs84 is True
    assert CrsRef.wgs84().authority_code == "EPSG:4326"
    assert CrsRef.web_mercator().epsg == 3857
    assert CrsRef(epsg=32643).is_wgs84 is False


def test_crs_ref_invalid() -> None:
    with pytest.raises(ValueValidationError):
        CrsRef(epsg=0)


# --- TileCoord / TileMatrixSetRef -------------------------------------------
def test_tile_coord_and_parent() -> None:
    t = TileCoord(z=2, x=3, y=1)
    assert str(t) == "2/3/1"
    assert t.parent() == TileCoord(z=1, x=1, y=0)
    assert TileCoord(z=0, x=0, y=0).parent() is None


@pytest.mark.parametrize(("z", "x", "y"), [(-1, 0, 0), (1, 2, 0), (1, 0, 2), (0, 1, 0)])
def test_tile_coord_invalid(z: int, x: int, y: int) -> None:
    with pytest.raises(ValueValidationError):
        TileCoord(z=z, x=x, y=y)


def test_tile_matrix_set_ref() -> None:
    tms = TileMatrixSetRef.web_mercator_quad()
    assert tms.identifier == WEB_MERCATOR_QUAD
    assert tms.crs.epsg == 3857
    with pytest.raises(ValueValidationError):
        TileMatrixSetRef(identifier="  ", crs=CrsRef.web_mercator())


# --- Quality -----------------------------------------------------------------
def test_cloud_cover() -> None:
    c = CloudCoverPercentage(value=8.0)
    assert c.fraction == pytest.approx(0.08)
    assert c.is_clear() is True
    assert CloudCoverPercentage(value=50.0).is_clear() is False


@pytest.mark.parametrize("value", [-0.1, 100.1, float("nan")])
def test_cloud_cover_invalid(value: float) -> None:
    with pytest.raises(ValueValidationError):
        CloudCoverPercentage(value=value)


def test_quality_score() -> None:
    assert QualityScore(value=0.0).value == 0.0
    assert QualityScore(value=1.0).value == 1.0
    with pytest.raises(ValueValidationError):
        QualityScore(value=1.5)


# --- AcquisitionMetadata -----------------------------------------------------
def _aware() -> datetime:
    return datetime(2024, 6, 1, 10, 30, tzinfo=UTC)


def test_acquisition_optical_valid() -> None:
    meta = AcquisitionMetadata(
        acquired_at=_aware(),
        sensor_type=SensorType.OPTICAL,
        cloud_cover=CloudCoverPercentage(value=5.0),
        sun_azimuth_deg=150.0,
        sun_elevation_deg=45.0,
        off_nadir_deg=10.0,
    )
    assert meta.sensor_type is SensorType.OPTICAL


def test_acquisition_sar_valid_without_optical_fields() -> None:
    meta = AcquisitionMetadata(acquired_at=_aware(), sensor_type=SensorType.SAR)
    assert meta.cloud_cover is None


def test_acquisition_requires_tz_aware() -> None:
    with pytest.raises(ValueValidationError):
        AcquisitionMetadata(acquired_at=datetime(2024, 6, 1), sensor_type=SensorType.OPTICAL)


def test_acquisition_sar_rejects_optical_fields() -> None:
    with pytest.raises(ValueValidationError):
        AcquisitionMetadata(
            acquired_at=_aware(),
            sensor_type=SensorType.SAR,
            cloud_cover=CloudCoverPercentage(value=1.0),
        )
    with pytest.raises(ValueValidationError):
        AcquisitionMetadata(
            acquired_at=_aware(), sensor_type=SensorType.SAR, sun_elevation_deg=30.0
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sun_azimuth_deg": 400.0},
        {"sun_elevation_deg": -120.0},
        {"off_nadir_deg": 200.0},
    ],
)
def test_acquisition_bad_angles(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueValidationError):
        AcquisitionMetadata(acquired_at=_aware(), sensor_type=SensorType.OPTICAL, **kwargs)


# --- ProviderCapabilities ----------------------------------------------------
def test_provider_capabilities() -> None:
    caps = ProviderCapabilities(
        provider="planet",
        sensor_types=frozenset({SensorType.OPTICAL}),
        supports_tasking=True,
        min_gsd_m=3.0,
        max_gsd_m=5.0,
    )
    assert caps.supports(SensorType.OPTICAL) is True
    assert caps.supports(SensorType.SAR) is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"provider": "", "sensor_types": frozenset({SensorType.OPTICAL})},
        {"provider": "p", "sensor_types": frozenset()},
        {"provider": "p", "sensor_types": frozenset({SensorType.OPTICAL}), "min_gsd_m": 0.0},
        {
            "provider": "p",
            "sensor_types": frozenset({SensorType.OPTICAL}),
            "min_gsd_m": 5.0,
            "max_gsd_m": 3.0,
        },
    ],
)
def test_provider_capabilities_invalid(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueValidationError):
        ProviderCapabilities(**kwargs)  # type: ignore[arg-type]
