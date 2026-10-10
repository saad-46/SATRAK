"""EO endpoint dependencies + query-param parsing helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import Depends, Request

from app.api.deps import require_permission
from app.api.v1.endpoints.earth_observation.composition import EarthObservationApi
from app.core.authz import AccessContext
from app.shared.domain.clock import utcnow
from app.shared.domain.errors import ValueValidationError
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def get_eo(request: Request) -> EarthObservationApi:
    return cast(EarthObservationApi, request.app.state.earth_observation)


EoDep = Annotated[EarthObservationApi, Depends(get_eo)]

# Permission-checked access contexts: each resolves to the jurisdictions in which the caller
# holds that permission (403 when nowhere). Module-level so FastAPI caches one check per request.
SceneReadAccess = Annotated[AccessContext, Depends(require_permission("eo:scene:read"))]
AoiReadAccess = Annotated[AccessContext, Depends(require_permission("eo:aoi:read"))]
TileReadAccess = Annotated[AccessContext, Depends(require_permission("eo:tile:read"))]


def parse_bbox(bbox: str) -> BoundingBox:
    """Parse ``minLon,minLat,maxLon,maxLat`` into a WGS84 bounding box (422 on error)."""
    parts = [p.strip() for p in bbox.split(",")]
    if len(parts) != 4:
        raise ValueValidationError("bbox must be 'minLon,minLat,maxLon,maxLat'", field="bbox")
    try:
        values = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueValidationError("bbox values must be numbers", field="bbox") from exc
    return BoundingBox(
        min_longitude=values[0],
        min_latitude=values[1],
        max_longitude=values[2],
        max_latitude=values[3],
    )


def _ensure_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def optional_window(from_: datetime | None, to: datetime | None) -> TimeRange | None:
    if from_ is None and to is None:
        return None
    return _window(from_, to)


def default_window(from_: datetime | None, to: datetime | None) -> TimeRange:
    return _window(from_, to)


def _window(from_: datetime | None, to: datetime | None) -> TimeRange:
    start = _ensure_utc(from_) if from_ is not None else _EPOCH
    end = _ensure_utc(to) if to is not None else utcnow()
    return TimeRange(start=start, end=end)
