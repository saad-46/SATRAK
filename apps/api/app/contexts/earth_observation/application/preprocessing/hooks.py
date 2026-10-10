"""Preprocessing extension hooks (Epic 3 Story 13).

Cloud masking and thumbnail rendering are pipeline *steps* whose science/rendering lives
elsewhere (Fmask/s2cloudless adapters, image encoders — later stories). The pipeline
invokes whatever is wired; an unwired hook whose step is requested is a configuration
error surfaced at run time, mirroring the provider feature pattern.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.infrastructure.raster.dataset import RasterDataset


@runtime_checkable
class CloudMasker(Protocol):
    """Returns the dataset with cloud/shadow pixels masked."""

    async def apply(self, dataset: RasterDataset, *, scene: Scene) -> RasterDataset: ...


@runtime_checkable
class ThumbnailRenderer(Protocol):
    """Renders and stores a quicklook; returns its storage URI."""

    async def render(self, dataset: RasterDataset, *, scene: Scene) -> str: ...


@runtime_checkable
class RasterDatasetLoader(Protocol):
    """Opens the scene's stored raster as a windowed dataset (storage/GDAL-backed later)."""

    async def load(self, scene: Scene) -> RasterDataset: ...
