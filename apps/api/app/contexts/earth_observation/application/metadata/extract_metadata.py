"""Canonical metadata extraction + scene registration (Epic 3 Story 11).

Reads ground-truth metadata from the stored raw asset through the ``MetadataExtractor``
port, merges it with the provider's claims (file wins; provider fills gaps), and
registers the scene — emitting ``MetadataExtracted`` and ``ImageStored`` via the
aggregate. Normalization across providers already happened at discovery
(``normalize_item``); this service reconciles those claims with what the file itself
says.
"""

from __future__ import annotations

from app.contexts.earth_observation.domain.ports.metadata_extractor import (
    ExtractedMetadata,
    MetadataExtractor,
)
from app.contexts.earth_observation.domain.ports.repositories import SceneRepository
from app.contexts.earth_observation.domain.value_objects.band import BandSet
from app.contexts.earth_observation.domain.value_objects.crs import CrsRef
from app.shared.domain.identifiers import EntityId
from app.shared.persistence.unit_of_work import UnitOfWork


def merge_bands(claimed: BandSet | None, extracted: BandSet | None) -> BandSet | None:
    """The file is ground truth; the provider claim is the fallback."""
    return extracted if extracted is not None else claimed


def merge_crs(claimed: CrsRef | None, extracted: CrsRef | None) -> CrsRef | None:
    return extracted if extracted is not None else claimed


class MetadataExtractionService:
    """Extracts canonical metadata from the stored asset and registers the scene."""

    def __init__(
        self, *, extractor: MetadataExtractor, scenes: SceneRepository, uow: UnitOfWork
    ) -> None:
        self._extractor = extractor
        self._scenes = scenes
        self._uow = uow

    async def extract_and_register(
        self, *, scene_id: EntityId, source_uri: str
    ) -> ExtractedMetadata:
        scene = await self._scenes.require(scene_id)
        extracted = await self._extractor.extract(source_uri=source_uri)
        scene.register(
            crs=merge_crs(scene.crs, extracted.crs),
            bands=merge_bands(scene.bands, extracted.bands),
        )
        await self._scenes.update(scene)
        self._uow.track(scene)
        await self._uow.commit()
        return extracted
