"""Versioned, declarative preprocessing pipeline specification (Epic 3 Story 13).

A ``PipelineSpec`` names *what* runs and in *which order*; its ``spec_hash`` is the
lineage fingerprint recorded with every run so a reprocessed scene is traceable to the
exact pipeline definition that produced it (spec §6 determinism, §13
``processing_runs.pipeline_spec_hash``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from app.shared.domain.errors import ValueValidationError


class PipelineStep(StrEnum):
    CLOUD_MASK = "cloud_mask"
    BAND_SELECTION = "band_selection"
    NORMALIZE = "normalize"
    THUMBNAIL = "thumbnail"


@dataclass(frozen=True)
class PipelineSpec:
    """An ordered, duplicate-free set of steps under a semantic version label."""

    version: str
    steps: tuple[PipelineStep, ...]
    band_selection: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueValidationError("pipeline version is required", field="version")
        if not self.steps:
            raise ValueValidationError("a pipeline needs at least one step", field="steps")
        if len(set(self.steps)) != len(self.steps):
            raise ValueValidationError("pipeline steps must be unique", field="steps")
        if PipelineStep.BAND_SELECTION in self.steps and not self.band_selection:
            raise ValueValidationError(
                "band_selection step requires band indexes", field="band_selection"
            )
        if self.band_selection is not None and any(b < 0 for b in self.band_selection):
            raise ValueValidationError("band indexes must be >= 0", field="band_selection")

    @property
    def spec_hash(self) -> str:
        """Deterministic fingerprint of the full definition (lineage key)."""
        canonical = "|".join(
            (
                self.version,
                ",".join(step.value for step in self.steps),
                ",".join(str(b) for b in self.band_selection or ()),
            )
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
