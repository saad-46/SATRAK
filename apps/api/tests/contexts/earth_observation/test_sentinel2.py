"""Story 7 — Sentinel-2 provider (discovery, normalization, capabilities, validation)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from app.contexts.earth_observation.domain.enums import SensorType
from app.contexts.earth_observation.domain.ports.imagery_provider import EarthObservationProvider
from app.contexts.earth_observation.infrastructure.providers import (
    ProviderConfiguration,
    ProviderConfigurationError,
    ProviderDataError,
)
from app.contexts.earth_observation.infrastructure.providers.satellite.sentinel2 import (
    DEFAULT_CATALOG_URL,
    DEFAULT_COLLECTION,
    PROVIDER_NAME,
    SENTINEL2_BANDS,
    Sentinel2Provider,
    default_configuration,
)
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange

_AREA = BoundingBox(min_longitude=76.0, min_latitude=12.0, max_longitude=78.0, max_latitude=14.0)
_WINDOW = TimeRange(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 12, 31, tzinfo=UTC))


def _stac_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": "S2A_MSIL2A_20240601T053221",
        "bbox": [76.9, 12.8, 78.1, 13.9],
        "properties": {
            "datetime": "2024-06-01T05:32:21Z",
            "eo:cloud_cover": 7.5,
            "view:sun_azimuth": 121.4,
            "view:sun_elevation": 67.2,
        },
    }
    item.update(overrides)
    return item


class _FakeCatalog:
    def __init__(self, items: Sequence[Mapping[str, Any]]) -> None:
        self.items = items
        self.last_query: Mapping[str, Any] | None = None

    async def search_items(
        self, *, area: BoundingBox, window: TimeRange, query: Mapping[str, Any]
    ) -> Sequence[Mapping[str, Any]]:
        self.last_query = query
        return self.items


def test_default_configuration_targets_dataspace() -> None:
    config = default_configuration()
    assert config.name == PROVIDER_NAME
    assert config.base_url == DEFAULT_CATALOG_URL
    assert config.extras["collection"] == DEFAULT_COLLECTION


def test_capabilities_and_bands() -> None:
    provider = Sentinel2Provider()
    caps = provider.capabilities()
    assert caps.supports(SensorType.OPTICAL) is True
    assert caps.supports_tasking is False
    assert (caps.min_gsd_m, caps.max_gsd_m) == (10.0, 60.0)
    assert len(SENTINEL2_BANDS) == 13
    b8a = SENTINEL2_BANDS.by_name("B8A")
    assert b8a is not None and b8a.resolution is not None
    assert b8a.resolution.gsd_m == 20.0
    assert isinstance(provider, EarthObservationProvider)


def test_validation_requires_collection() -> None:
    with pytest.raises(ProviderConfigurationError):
        Sentinel2Provider(
            config=ProviderConfiguration(name=PROVIDER_NAME, base_url=DEFAULT_CATALOG_URL)
        )


def test_validation_bounds_cloud_filter() -> None:
    with pytest.raises(ProviderConfigurationError):
        Sentinel2Provider(max_cloud_cover_pct=150.0)


def test_search_query_with_and_without_cloud_filter() -> None:
    assert Sentinel2Provider().search_query() == {"collections": [DEFAULT_COLLECTION]}
    filtered = Sentinel2Provider(max_cloud_cover_pct=10.0).search_query()
    assert filtered["filter"] == {"eo:cloud_cover": {"lte": 10.0}}


def test_normalize_full_item() -> None:
    candidate = Sentinel2Provider().normalize_item(_stac_item())
    assert candidate.provider_scene_id.provider == PROVIDER_NAME
    assert candidate.provider_scene_id.native_id == "S2A_MSIL2A_20240601T053221"
    assert candidate.bounding_box.min_longitude == 76.9
    acq = candidate.acquisition
    assert acq.acquired_at == datetime(2024, 6, 1, 5, 32, 21, tzinfo=UTC)
    assert acq.sensor_type is SensorType.OPTICAL
    assert acq.cloud_cover is not None and acq.cloud_cover.value == 7.5
    assert acq.sun_azimuth_deg == 121.4


def test_normalize_minimal_item_without_optional_fields() -> None:
    item = _stac_item(properties={"datetime": "2024-06-01T05:32:21+00:00"})
    acq = Sentinel2Provider().normalize_item(item).acquisition
    assert acq.cloud_cover is None
    assert acq.sun_azimuth_deg is None


@pytest.mark.parametrize(
    "broken",
    [
        {"id": None},
        {"bbox": [1.0, 2.0]},
        {"bbox": "not-a-bbox"},
        {"properties": {}},
        {"properties": {"datetime": "not-a-date"}},
        {"properties": {"datetime": "2024-06-01T05:32:21"}},  # naive -> domain rejects
        {"bbox": [200.0, 12.8, 78.1, 13.9]},  # out-of-range longitude
        {"properties": {"datetime": "2024-06-01T05:32:21Z", "eo:cloud_cover": 400.0}},
    ],
)
def test_normalize_rejects_malformed_items(broken: dict[str, Any]) -> None:
    item = _stac_item()
    item.update(broken)
    if broken.get("id") is None and "id" in broken:
        del item["id"]
    with pytest.raises(ProviderDataError) as exc:
        Sentinel2Provider().normalize_item(item)
    assert exc.value.provider == PROVIDER_NAME


async def test_search_end_to_end_with_fake_catalog() -> None:
    catalog = _FakeCatalog([_stac_item(), _stac_item(id="S2B_MSIL2A_20240611T053221")])
    provider = Sentinel2Provider(max_cloud_cover_pct=20.0, catalog=catalog)
    candidates = await provider.search(area=_AREA, window=_WINDOW)
    assert len(candidates) == 2
    assert catalog.last_query is not None
    assert catalog.last_query["collections"] == [DEFAULT_COLLECTION]
