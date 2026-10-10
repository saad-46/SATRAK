"""Story 19 — AOI & Timeline API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from httpx import AsyncClient

from app.api.v1.endpoints.earth_observation.composition import EarthObservationApi
from tests.api.eo_support import (
    FAR_BBOX,
    make_aoi,
    make_available_scene,
    make_discovered_scene,
)

_AOI = "/api/v1/eo/aoi"
_TIMELINE = "/api/v1/eo/timeline"


async def test_list_aois_active_only(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    client, container = eo_env
    active = make_aoi(name="Ward A")
    inactive = make_aoi(name="Ward B")
    inactive.deactivate()
    inactive.pull_events()
    await container.aois.add(active)
    await container.aois.add(inactive)

    default = await client.get(_AOI)
    assert default.status_code == 200
    assert [a["name"] for a in default.json()["items"]] == ["Ward A"]
    assert default.json()["meta"]["total"] == 1

    including = await client.get(_AOI, params={"active_only": "false"})
    assert including.json()["meta"]["total"] == 2


async def test_aoi_detail(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, container = eo_env
    aoi = make_aoi()
    aoi.set_revisit_cadence(7)
    aoi.pull_events()
    await container.aois.add(aoi)

    response = await client.get(f"{_AOI}/{aoi.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Ward 12"
    assert body["priority"] == "medium"
    assert body["revisit_cadence_days"] == 7
    assert body["bounding_box"]["max_latitude"] == 14.0


async def test_aoi_timeline(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, container = eo_env
    aoi = make_aoi()
    await container.aois.add(aoi)
    older = make_available_scene(native_id="OLD", acquired_at=datetime(2024, 1, 1, tzinfo=UTC))
    newer = make_available_scene(native_id="NEW", acquired_at=datetime(2024, 8, 1, tzinfo=UTC))
    off_site = make_available_scene(native_id="OFF", bbox=FAR_BBOX)
    discovered = make_discovered_scene(native_id="PENDING")  # not AVAILABLE -> excluded
    for scene in (older, newer, off_site, discovered):
        await container.scenes.add(scene)

    response = await client.get(f"{_AOI}/{aoi.id}/timeline")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2  # two available scenes over the AOI, off-site + pending excluded
    assert [s["provider_scene_id"] for s in body["scenes"]] == [
        "sentinel-2:NEW",
        "sentinel-2:OLD",
    ]
    assert body["area"]["min_longitude"] == 76.0


async def test_aoi_timeline_date_filter(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    client, container = eo_env
    aoi = make_aoi()
    await container.aois.add(aoi)
    await container.scenes.add(
        make_available_scene(native_id="OLD", acquired_at=datetime(2024, 1, 1, tzinfo=UTC))
    )
    await container.scenes.add(
        make_available_scene(native_id="NEW", acquired_at=datetime(2024, 8, 1, tzinfo=UTC))
    )
    response = await client.get(
        f"{_AOI}/{aoi.id}/timeline", params={"from": "2024-06-01T00:00:00Z"}
    )
    assert response.json()["count"] == 1
    assert response.json()["scenes"][0]["provider_scene_id"] == "sentinel-2:NEW"


async def test_area_timeline_property_hook(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    """The bbox timeline the property context calls with a parcel's bounding box."""
    client, container = eo_env
    await container.scenes.add(make_available_scene(native_id="COVERS"))
    await container.scenes.add(make_available_scene(native_id="FAR", bbox=FAR_BBOX))

    response = await client.get(_TIMELINE, params={"bbox": "76.5,12.5,77.5,13.5"})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["scenes"][0]["provider_scene_id"] == "sentinel-2:COVERS"


async def test_area_timeline_requires_bbox(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    client, _ = eo_env
    response = await client.get(_TIMELINE)
    assert response.status_code == 422  # bbox is required


async def test_unknown_aoi_is_404(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, _ = eo_env
    assert (await client.get(f"{_AOI}/{uuid4()}")).status_code == 404
    assert (await client.get(f"{_AOI}/{uuid4()}/timeline")).status_code == 404
