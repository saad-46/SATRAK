"""Placeholder interfaces for the shared geospatial support package.

Epic 3 Story 1 scaffold — **no implementation**. The concrete CRS-transform boundary
(the single place national-projected <-> WGS84 transforms happen, so no service hand-rolls
a ``pyproj`` call) is implemented in a later Earth Observation story; see
``docs/epic-3-earth-observation-platform-spec.md`` §9 and ``docs/adr/0006``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CrsTransformer(Protocol):
    """Single boundary for coordinate-reference-system transforms.

    Placeholder interface: the method contract is finalized in a later story. Signatures
    below are indicative only and intentionally minimal.
    """

    def to_wgs84(self, geometry: object, *, source_srid: int) -> object:
        """Transform a geometry to WGS84 (EPSG:4326) for interchange/display."""
        ...

    def to_projected(self, geometry: object, *, target_srid: int) -> object:
        """Transform a geometry to a national projected CRS for area/distance math."""
        ...
