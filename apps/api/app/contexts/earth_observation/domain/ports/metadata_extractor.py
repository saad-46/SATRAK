"""Metadata extraction port.

Reads geo-metadata from a stored raster and returns canonical domain values. The concrete
GDAL-backed adapter lands in ``infrastructure`` (Story 11).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.contexts.earth_observation.domain.value_objects.acquisition import AcquisitionMetadata
from app.contexts.earth_observation.domain.value_objects.band import BandSet
from app.contexts.earth_observation.domain.value_objects.crs import CrsRef


@dataclass(frozen=True)
class ExtractedMetadata:
    """Canonical metadata resolved from a stored raster asset."""

    acquisition: AcquisitionMetadata
    bands: BandSet | None = None
    crs: CrsRef | None = None


@runtime_checkable
class MetadataExtractor(Protocol):
    """Extracts canonical metadata from a stored raster identified by URI."""

    async def extract(self, *, source_uri: str) -> ExtractedMetadata: ...
