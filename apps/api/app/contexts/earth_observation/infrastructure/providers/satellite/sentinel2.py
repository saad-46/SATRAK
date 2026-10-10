"""Sentinel-2 provider (Copernicus Dataspace ecosystem).

Targets the Copernicus Dataspace STAC catalogue (the successor to the retired Open Access
Hub); the same normalization works for any STAC-compliant Sentinel-2 source, so future
Copernicus APIs plug in as alternative ``SceneCatalog`` transports without touching this
class. Discovery, normalization, capability reporting, and validation are implemented;
byte download is deferred to the transport story (spec §19).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.contexts.earth_observation.domain.enums import SensorType
from app.contexts.earth_observation.domain.ports.imagery_provider import SceneCandidate
from app.contexts.earth_observation.domain.value_objects.acquisition import AcquisitionMetadata
from app.contexts.earth_observation.domain.value_objects.band import Band, BandSet
from app.contexts.earth_observation.domain.value_objects.capabilities import ProviderCapabilities
from app.contexts.earth_observation.domain.value_objects.quality import CloudCoverPercentage
from app.contexts.earth_observation.domain.value_objects.resolution import Resolution
from app.contexts.earth_observation.domain.value_objects.scene_id import ProviderSceneId
from app.contexts.earth_observation.infrastructure.providers.base import (
    ProviderConfiguration,
    SatelliteProvider,
)
from app.contexts.earth_observation.infrastructure.providers.errors import (
    ProviderConfigurationError,
    ProviderDataError,
)
from app.shared.domain.errors import ValueValidationError
from app.shared.value_objects.geo import BoundingBox

PROVIDER_NAME = "sentinel-2"
DEFAULT_CATALOG_URL = "https://catalogue.dataspace.copernicus.eu/stac"
DEFAULT_COLLECTION = "sentinel-2-l2a"

# MSI band layout: (name, common name, centre wavelength nm, native GSD m).
_MSI_BANDS: tuple[tuple[str, str, float, float], ...] = (
    ("B01", "coastal", 443.0, 60.0),
    ("B02", "blue", 490.0, 10.0),
    ("B03", "green", 560.0, 10.0),
    ("B04", "red", 665.0, 10.0),
    ("B05", "rededge1", 705.0, 20.0),
    ("B06", "rededge2", 740.0, 20.0),
    ("B07", "rededge3", 783.0, 20.0),
    ("B08", "nir", 842.0, 10.0),
    ("B8A", "nir08", 865.0, 20.0),
    ("B09", "nir09", 945.0, 60.0),
    ("B10", "cirrus", 1375.0, 60.0),
    ("B11", "swir16", 1610.0, 20.0),
    ("B12", "swir22", 2190.0, 20.0),
)

SENTINEL2_BANDS = BandSet(
    bands=tuple(
        Band(
            name=name,
            index=index,
            common_name=common,
            wavelength_nm=wavelength,
            resolution=Resolution(gsd_m=gsd),
        )
        for index, (name, common, wavelength, gsd) in enumerate(_MSI_BANDS)
    )
)


def default_configuration() -> ProviderConfiguration:
    """Open-access Dataspace defaults; overridable per deployment."""
    return ProviderConfiguration(
        name=PROVIDER_NAME,
        base_url=DEFAULT_CATALOG_URL,
        extras={"collection": DEFAULT_COLLECTION},
    )


class Sentinel2Provider(SatelliteProvider):
    """ESA Sentinel-2 (MSI) — free, high-revisit optical baseline monitoring."""

    def __init__(self, *, max_cloud_cover_pct: float | None = None, **kwargs: Any) -> None:
        self._max_cloud_cover_pct = max_cloud_cover_pct
        kwargs.setdefault("config", default_configuration())
        super().__init__(**kwargs)

    # --- Capability reporting -------------------------------------------------
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=PROVIDER_NAME,
            sensor_types=frozenset({SensorType.OPTICAL}),
            supports_tasking=False,
            min_gsd_m=10.0,
            max_gsd_m=60.0,
        )

    # --- Validation -------------------------------------------------------------
    def validate_configuration(self) -> None:
        collection = self.config.extras.get("collection", "")
        if not collection.strip():
            raise ProviderConfigurationError("sentinel-2 requires a 'collection' extra")
        if self._max_cloud_cover_pct is not None and not 0.0 <= self._max_cloud_cover_pct <= 100.0:
            raise ProviderConfigurationError("max_cloud_cover_pct must be in [0, 100]")

    # --- Discovery query ----------------------------------------------------------
    def search_query(self) -> Mapping[str, Any]:
        query: dict[str, Any] = {"collections": [self.config.extras["collection"]]}
        if self._max_cloud_cover_pct is not None:
            query["filter"] = {"eo:cloud_cover": {"lte": self._max_cloud_cover_pct}}
        return query

    # --- Metadata normalization (STAC Item -> canonical) ---------------------------
    def normalize_item(self, item: Mapping[str, Any]) -> SceneCandidate:
        try:
            native_id = str(item["id"])
            bbox_raw = item["bbox"]
            properties: Mapping[str, Any] = item["properties"]
            timestamp = str(properties["datetime"])
        except (KeyError, TypeError) as exc:
            raise ProviderDataError(
                f"malformed STAC item: missing {exc}", provider=PROVIDER_NAME
            ) from exc
        if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) != 4:
            raise ProviderDataError(
                "malformed STAC item: bbox must be [west, south, east, north]",
                provider=PROVIDER_NAME,
            )
        try:
            acquired_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            west, south, east, north = (float(v) for v in bbox_raw)
            cloud_raw = properties.get("eo:cloud_cover")
            sun_azimuth = properties.get("view:sun_azimuth")
            sun_elevation = properties.get("view:sun_elevation")
            return SceneCandidate(
                provider_scene_id=ProviderSceneId(provider=PROVIDER_NAME, native_id=native_id),
                bounding_box=BoundingBox(
                    min_longitude=west,
                    min_latitude=south,
                    max_longitude=east,
                    max_latitude=north,
                ),
                acquisition=AcquisitionMetadata(
                    acquired_at=acquired_at,
                    sensor_type=SensorType.OPTICAL,
                    cloud_cover=(
                        CloudCoverPercentage(value=float(cloud_raw))
                        if cloud_raw is not None
                        else None
                    ),
                    sun_azimuth_deg=float(sun_azimuth) if sun_azimuth is not None else None,
                    sun_elevation_deg=(float(sun_elevation) if sun_elevation is not None else None),
                ),
            )
        except (ValueError, ValueValidationError) as exc:
            raise ProviderDataError(
                f"invalid STAC item {native_id!r}: {exc}", provider=PROVIDER_NAME
            ) from exc
