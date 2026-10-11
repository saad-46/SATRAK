"""Scene aggregate — the consistency boundary for one unit of imagery.

A ``Scene`` owns its lifecycle (``SceneStatus``), its capture-time metadata, and the
references produced as it flows discovery -> available (spec §6). It records domain events
but knows nothing about persistence, storage, or providers (those are ports/adapters).
Allowed state transitions are enforced here — the single chokepoint that keeps a scene from
ever being observed in an inconsistent state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.contexts.earth_observation.domain.enums import SceneStatus
from app.contexts.earth_observation.domain.events import (
    ImageArchived,
    ImageDiscovered,
    ImageDownloaded,
    ImageRejected,
    ImageStored,
    ImageValidated,
    MetadataExtracted,
    SceneAvailable,
    SceneProcessed,
    SceneProcessingFailed,
    SceneReprocessed,
    TileGenerated,
)
from app.contexts.earth_observation.domain.value_objects.acquisition import AcquisitionMetadata
from app.contexts.earth_observation.domain.value_objects.band import BandSet
from app.contexts.earth_observation.domain.value_objects.crs import CrsRef
from app.contexts.earth_observation.domain.value_objects.quality import QualityScore
from app.contexts.earth_observation.domain.value_objects.scene_id import ProviderSceneId
from app.contexts.earth_observation.domain.value_objects.tile import TileMatrixSetRef
from app.shared.domain.entity import AggregateRoot
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.identifiers import EntityId
from app.shared.value_objects.geo import BoundingBox

# Allowed lifecycle transitions (spec §6.1). A target absent from a state's set is illegal.
_TRANSITIONS: dict[SceneStatus, frozenset[SceneStatus]] = {
    SceneStatus.DISCOVERED: frozenset({SceneStatus.DOWNLOADED, SceneStatus.REJECTED}),
    SceneStatus.DOWNLOADED: frozenset({SceneStatus.VALIDATED, SceneStatus.REJECTED}),
    SceneStatus.VALIDATED: frozenset({SceneStatus.REGISTERED, SceneStatus.REJECTED}),
    SceneStatus.REGISTERED: frozenset({SceneStatus.PREPROCESSING}),
    SceneStatus.PREPROCESSING: frozenset({SceneStatus.PROCESSED, SceneStatus.FAILED}),
    SceneStatus.PROCESSED: frozenset({SceneStatus.TILED, SceneStatus.FAILED}),
    SceneStatus.TILED: frozenset({SceneStatus.AVAILABLE, SceneStatus.FAILED}),
    SceneStatus.FAILED: frozenset({SceneStatus.PREPROCESSING}),
    SceneStatus.AVAILABLE: frozenset({SceneStatus.PREPROCESSING, SceneStatus.ARCHIVED}),
    SceneStatus.ARCHIVED: frozenset({SceneStatus.AVAILABLE}),
    SceneStatus.REJECTED: frozenset(),
}

_PROCESSED_STATES = frozenset({SceneStatus.PROCESSED, SceneStatus.TILED, SceneStatus.AVAILABLE})


@dataclass(kw_only=True, eq=False)
class Scene(AggregateRoot):
    """A single scene of satellite/aerial imagery and its processing lifecycle."""

    provider_scene_id: ProviderSceneId
    bounding_box: BoundingBox
    acquisition: AcquisitionMetadata
    jurisdiction_id: EntityId
    status: SceneStatus = SceneStatus.DISCOVERED
    bands: BandSet | None = None
    crs: CrsRef | None = None
    quality: QualityScore | None = None
    checksum_sha256: str | None = None
    pipeline_version: str | None = None
    rejection_reason: str | None = None
    aoi_ids: set[EntityId] = field(default_factory=set)

    # --- Invariants ----------------------------------------------------------
    def _check_invariants(self) -> None:
        super()._check_invariants()
        if self.status is SceneStatus.REJECTED and not self.rejection_reason:
            raise InvariantViolation("a rejected scene requires a rejection_reason")
        if self.status in _PROCESSED_STATES and self.pipeline_version is None:
            raise InvariantViolation(f"scene in {self.status} requires a pipeline_version")

    # --- Factory -------------------------------------------------------------
    @classmethod
    def create(
        cls,
        *,
        provider_scene_id: ProviderSceneId,
        bounding_box: BoundingBox,
        acquisition: AcquisitionMetadata,
        jurisdiction_id: EntityId,
        bands: BandSet | None = None,
        crs: CrsRef | None = None,
        actor: EntityId | None = None,
    ) -> Scene:
        scene = cls(
            provider_scene_id=provider_scene_id,
            bounding_box=bounding_box,
            acquisition=acquisition,
            jurisdiction_id=jurisdiction_id,
            bands=bands,
            crs=crs,
            created_by=actor,
            updated_by=actor,
        )
        scene.record_event(
            ImageDiscovered(
                aggregate_id=scene.id,
                aggregate_type=cls.__name__,
                provider_scene_id=str(provider_scene_id),
            )
        )
        return scene

    # --- Transition helper ---------------------------------------------------
    def _transition(self, target: SceneStatus, *, actor: EntityId | None = None) -> None:
        if target not in _TRANSITIONS[self.status]:
            raise InvariantViolation(f"invalid scene transition: {self.status} -> {target}")
        self.status = target
        self.touch(actor=actor)  # bumps version and re-checks invariants

    # --- Lifecycle -----------------------------------------------------------
    def mark_downloaded(self, *, checksum_sha256: str, actor: EntityId | None = None) -> None:
        if not checksum_sha256.strip():
            raise InvariantViolation("checksum_sha256 is required to mark downloaded")
        self.checksum_sha256 = checksum_sha256
        self._transition(SceneStatus.DOWNLOADED, actor=actor)
        self.record_event(
            ImageDownloaded(
                aggregate_id=self.id,
                aggregate_type=type(self).__name__,
                checksum_sha256=checksum_sha256,
            )
        )

    def mark_validated(self, *, actor: EntityId | None = None) -> None:
        self._transition(SceneStatus.VALIDATED, actor=actor)
        self.record_event(ImageValidated(aggregate_id=self.id, aggregate_type=type(self).__name__))

    def reject(self, *, reason: str, actor: EntityId | None = None) -> None:
        if not reason.strip():
            raise InvariantViolation("a rejection reason is required")
        self.rejection_reason = reason
        self._transition(SceneStatus.REJECTED, actor=actor)
        self.record_event(
            ImageRejected(aggregate_id=self.id, aggregate_type=type(self).__name__, reason=reason)
        )

    def register(
        self,
        *,
        crs: CrsRef | None = None,
        quality: QualityScore | None = None,
        bands: BandSet | None = None,
        actor: EntityId | None = None,
    ) -> None:
        if crs is not None:
            self.crs = crs
        if quality is not None:
            self.quality = quality
        if bands is not None:
            self.bands = bands
        self._transition(SceneStatus.REGISTERED, actor=actor)
        agg_type = type(self).__name__
        self.record_event(MetadataExtracted(aggregate_id=self.id, aggregate_type=agg_type))
        self.record_event(ImageStored(aggregate_id=self.id, aggregate_type=agg_type))

    def start_preprocessing(self, *, pipeline_version: str, actor: EntityId | None = None) -> None:
        if not pipeline_version.strip():
            raise InvariantViolation("pipeline_version is required to preprocess")
        self.pipeline_version = pipeline_version
        self._transition(SceneStatus.PREPROCESSING, actor=actor)

    def mark_processed(
        self, *, quality: QualityScore | None = None, actor: EntityId | None = None
    ) -> None:
        if quality is not None:
            self.quality = quality
        self._transition(SceneStatus.PROCESSED, actor=actor)
        # pipeline_version is set by start_preprocessing/reprocess; guard explicitly so the
        # check survives ``python -O`` and narrows the type for the event payload.
        if self.pipeline_version is None:
            raise InvariantViolation("cannot mark processed without a pipeline_version")
        self.record_event(
            SceneProcessed(
                aggregate_id=self.id,
                aggregate_type=type(self).__name__,
                pipeline_version=self.pipeline_version,
            )
        )

    def mark_tiled(
        self, *, tile_matrix_set: TileMatrixSetRef, actor: EntityId | None = None
    ) -> None:
        self._transition(SceneStatus.TILED, actor=actor)
        self.record_event(
            TileGenerated(
                aggregate_id=self.id,
                aggregate_type=type(self).__name__,
                tile_matrix_set=tile_matrix_set.identifier,
            )
        )

    def mark_available(self, *, actor: EntityId | None = None) -> None:
        self._transition(SceneStatus.AVAILABLE, actor=actor)
        self.record_event(SceneAvailable(aggregate_id=self.id, aggregate_type=type(self).__name__))

    def mark_failed(self, *, reason: str, actor: EntityId | None = None) -> None:
        if not reason.strip():
            raise InvariantViolation("a failure reason is required")
        self._transition(SceneStatus.FAILED, actor=actor)
        self.record_event(
            SceneProcessingFailed(
                aggregate_id=self.id, aggregate_type=type(self).__name__, reason=reason
            )
        )

    def reprocess(self, *, pipeline_version: str, actor: EntityId | None = None) -> None:
        """Re-run processing under a new pipeline version (from ``AVAILABLE``)."""
        if not pipeline_version.strip():
            raise InvariantViolation("pipeline_version is required to reprocess")
        if pipeline_version == self.pipeline_version:
            raise InvariantViolation("reprocess requires a new pipeline_version")
        self.pipeline_version = pipeline_version
        self._transition(SceneStatus.PREPROCESSING, actor=actor)
        self.record_event(
            SceneReprocessed(
                aggregate_id=self.id,
                aggregate_type=type(self).__name__,
                pipeline_version=pipeline_version,
            )
        )

    def archive(self, *, actor: EntityId | None = None) -> None:
        self._transition(SceneStatus.ARCHIVED, actor=actor)
        self.record_event(ImageArchived(aggregate_id=self.id, aggregate_type=type(self).__name__))

    def restore_from_archive(self, *, actor: EntityId | None = None) -> None:
        self._transition(SceneStatus.AVAILABLE, actor=actor)
        self.record_event(SceneAvailable(aggregate_id=self.id, aggregate_type=type(self).__name__))

    # --- Relationships -------------------------------------------------------
    def link_aoi(self, aoi_id: EntityId, *, actor: EntityId | None = None) -> None:
        """Record that this scene intersects the given AOI (spec §10 timeline)."""
        if aoi_id in self.aoi_ids:
            return
        self.aoi_ids.add(aoi_id)
        self.touch(actor=actor)

    # --- Queries -------------------------------------------------------------
    @property
    def is_available(self) -> bool:
        return self.status is SceneStatus.AVAILABLE

    @property
    def is_terminal(self) -> bool:
        return not _TRANSITIONS[self.status]
