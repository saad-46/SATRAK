"""Story 17 — Scene & Status API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from httpx import AsyncClient

from app.api.v1.endpoints.earth_observation.composition import EarthObservationApi
from tests.api.eo_support import make_available_scene

_BASE = "/api/v1/eo/scenes"


async def _seed(container: EarthObservationApi) -> tuple[str, str]:
    older = make_available_scene(
        native_id="OLD", acquired_at=datetime(2024, 1, 1, tzinfo=UTC), cloud_pct=5.0
    )
    newer = make_available_scene(
        native_id="NEW", acquired_at=datetime(2024, 8, 1, tzinfo=UTC), cloud_pct=40.0
    )
    await container.scenes.add(older)
    await container.scenes.add(newer)
    return str(older.id), str(newer.id)


async def test_search_returns_scenes_newest_first(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    client, container = eo_env
    old_id, new_id = await _seed(container)

    response = await client.get(_BASE)
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 2
    assert [item["id"] for item in body["items"]] == [new_id, old_id]  # newest first
    assert body["items"][0]["status"] == "available"
    assert body["items"][0]["provider"] == "sentinel-2"


async def test_search_filters(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, container = eo_env
    _, new_id = await _seed(container)

    # Cloud filter keeps only the clear (older) scene.
    clear = await client.get(_BASE, params={"max_cloud": 10})
    assert [i["id"] for i in clear.json()["items"]] != [new_id]
    assert clear.json()["meta"]["total"] == 1

    # Date filter keeps only the newer scene.
    from_2024_06 = await client.get(_BASE, params={"from": "2024-06-01T00:00:00Z"})
    assert from_2024_06.json()["meta"]["total"] == 1
    assert from_2024_06.json()["items"][0]["id"] == new_id

    # bbox disjoint from the footprints -> empty.
    far = await client.get(
        _BASE,
        params={"bbox": "100.0,40.0,101.0,41.0"},
    )
    assert far.json()["meta"]["total"] == 0

    # status + provider filters.
    assert (await client.get(_BASE, params={"status": "discovered"})).json()["meta"]["total"] == 0
    assert (await client.get(_BASE, params={"provider": "landsat"})).json()["meta"]["total"] == 0
    assert (await client.get(_BASE, params={"sensor_type": "sar"})).json()["meta"]["total"] == 0


async def test_search_pagination(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, container = eo_env
    await _seed(container)
    page1 = await client.get(_BASE, params={"page": 1, "size": 1})
    assert page1.json()["meta"]["total"] == 2
    assert page1.json()["meta"]["total_pages"] == 2
    assert page1.json()["meta"]["has_next"] is True
    assert len(page1.json()["items"]) == 1


async def test_search_rejects_bad_bbox(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    client, _ = eo_env
    response = await client.get(_BASE, params={"bbox": "1,2,3"})
    assert response.status_code == 422
    assert response.json()["code"] == "value_validation_error"


async def test_scene_detail(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, container = eo_env
    scene = make_available_scene()
    aoi_ref = uuid4()
    scene.link_aoi(aoi_ref)
    scene.pull_events()
    await container.scenes.add(scene)

    response = await client.get(f"{_BASE}/{scene.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(scene.id)
    assert body["crs_epsg"] == 32643
    assert body["pipeline_version"] == "1.0.0"
    assert body["quality_score"] == 0.9
    assert body["checksum_sha256"] == "ab" * 32
    assert str(aoi_ref) in body["aoi_ids"]
    assert body["bounding_box"]["min_longitude"] == 76.0


async def test_scene_status(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, container = eo_env
    scene = make_available_scene()
    await container.scenes.add(scene)
    response = await client.get(f"{_BASE}/{scene.id}/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["is_available"] is True
    assert body["is_terminal"] is False
    assert body["pipeline_version"] == "1.0.0"


async def test_scene_metadata(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, container = eo_env
    scene = make_available_scene()
    await container.scenes.add(scene)
    response = await client.get(f"{_BASE}/{scene.id}/metadata")
    assert response.status_code == 200
    body = response.json()
    assert body["sensor_type"] == "optical"
    assert body["cloud_cover_pct"] == 7.5
    assert body["sun_azimuth_deg"] == 121.4
    assert body["bands"][0]["name"] == "B04"
    assert body["bands"][0]["gsd_m"] == 10.0
    assert body["crs_epsg"] == 32643


async def test_unknown_scene_is_404(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, _ = eo_env
    missing = uuid4()
    assert (await client.get(f"{_BASE}/{missing}")).status_code == 404
    assert (await client.get(f"{_BASE}/{missing}/status")).status_code == 404
    assert (await client.get(f"{_BASE}/{missing}/metadata")).status_code == 404
    assert (await client.get(f"{_BASE}/{missing}")).json()["code"] == "not_found"


async def test_search_rejects_non_numeric_bbox(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    client, _ = eo_env
    response = await client.get(_BASE, params={"bbox": "a,b,c,d"})
    assert response.status_code == 422
    assert response.json()["code"] == "value_validation_error"
