"""Placeholder imagery-provider interface hierarchy — the extension mechanism (ADR-0007).

Epic 3 Story 1 scaffold — **no implementation**. Concrete providers (Sentinel-2, Landsat,
Planet, Maxar, Airbus, Cartosat, Bhuvan, ...) are NOT implemented here; they arrive in the
provider stories. Drone/UAV imagery is deliberately excluded — it belongs to the ``drone``
bounded context (ADR-0010). This module establishes only the abstract hierarchy so the
architecture is prepared without locking method signatures prematurely.
"""

from __future__ import annotations

import abc


class EarthObservationProvider(abc.ABC):
    """Base extension point for any Earth Observation imagery provider.

    Placeholder — the concrete contract (capabilities / search / task / fetch / normalize)
    is defined in the provider stories (spec §5). No members are declared yet.
    """


class SatelliteProvider(EarthObservationProvider, abc.ABC):
    """Spaceborne imagery providers (Sentinel, Landsat, Planet, Maxar, Airbus, Cartosat, Bhuvan)."""


class AerialProvider(EarthObservationProvider, abc.ABC):
    """Manned airborne / aerial-orthophoto imagery providers."""
