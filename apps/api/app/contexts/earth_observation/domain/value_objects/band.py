"""Spectral band descriptors: Band and BandSet."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.contexts.earth_observation.domain.value_objects.resolution import Resolution
from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject


@dataclass(frozen=True)
class Band(ValueObject):
    """A single spectral band of a sensor.

    ``index`` is the band's position in the source product; ``wavelength_nm`` is the
    centre wavelength (optical/hyperspectral); ``resolution`` is the band's native GSD,
    which can differ between bands (e.g. Sentinel-2 10 m vs 20 m bands).
    """

    name: str
    index: int
    common_name: str | None = None
    wavelength_nm: float | None = None
    resolution: Resolution | None = None

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueValidationError("band name is required", field="name")
        object.__setattr__(self, "name", name)
        if self.index < 0:
            raise ValueValidationError("band index must be >= 0", field="index")
        if self.wavelength_nm is not None and (
            not math.isfinite(self.wavelength_nm) or self.wavelength_nm <= 0
        ):
            raise ValueValidationError(
                "wavelength_nm must be a finite, positive number", field="wavelength_nm"
            )


@dataclass(frozen=True)
class BandSet(ValueObject):
    """An ordered set of bands with unique names and unique indices."""

    bands: tuple[Band, ...]

    def __post_init__(self) -> None:
        bands = tuple(self.bands)
        if not bands:
            raise ValueValidationError("a BandSet must contain at least one band", field="bands")
        names = [b.name for b in bands]
        if len(set(names)) != len(names):
            raise ValueValidationError("band names must be unique", field="bands")
        indices = [b.index for b in bands]
        if len(set(indices)) != len(indices):
            raise ValueValidationError("band indices must be unique", field="bands")
        object.__setattr__(self, "bands", bands)

    def __len__(self) -> int:
        return len(self.bands)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(b.name for b in self.bands)

    def by_name(self, name: str) -> Band | None:
        return next((b for b in self.bands if b.name == name), None)
