"""Timeline provider port.

Contract for querying imagery history over a geometry and time window (spec §10). The
query is a read over scene references; the concrete adapter lands with persistence
(Stories 8/19). No implementation here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.shared.domain.scope import AccessScope
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange


@runtime_checkable
class TimelineProvider(Protocol):
    """Returns scenes intersecting an area within a time window, ordered by acquisition."""

    async def timeline(
        self,
        *,
        area: BoundingBox,
        window: TimeRange,
        scope: AccessScope,
    ) -> Sequence[Scene]: ...
