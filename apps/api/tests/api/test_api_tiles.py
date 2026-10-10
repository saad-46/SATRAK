"""Story 18 — Tile API endpoints (XYZ serving, metadata, cache validation, versioning)."""

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient

from app.api.v1.endpoints.earth_observation.composition import EarthObservationApi
from tests.api.eo_support import make_available_scene, make_discovered_scene, store_tile


def _tiles_base(scene_id: object) -> str:
    return f"/api/v1/eo/scenes/{scene_id}/tiles"


async def test_serve_tile_bytes_with_etag(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    client, container = eo_env
    scene = make_available_scene()
    await container.scenes.add(scene)
    await store_tile(container, scene=scene, z=2, x=3, y=1, data=b"PIXELS")

    response = await client.get(f"{_tiles_base(scene.id)}/2/3/1")
    assert response.status_code == 200
    assert response.content == b"PIXELS"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["etag"]
    assert "max-age" in response.headers["cache-control"]


async def test_conditional_request_returns_304(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    client, container = eo_env
    scene = make_available_scene()
    await container.scenes.add(scene)
    await store_tile(container, scene=scene, z=2, x=3, y=1)

    first = await client.get(f"{_tiles_base(scene.id)}/2/3/1")
    etag = first.headers["etag"]
    cached = await client.get(f"{_tiles_base(scene.id)}/2/3/1", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    assert cached.headers["etag"] == etag
    assert cached.content == b""


async def test_tile_metadata(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, container = eo_env
    scene = make_available_scene()
    await container.scenes.add(scene)
    await store_tile(container, scene=scene, z=2, x=3, y=1, data=b"ABCD")

    response = await client.get(f"{_tiles_base(scene.id)}/2/3/1/metadata")
    assert response.status_code == 200
    body = response.json()
    assert body["tile_matrix_set"] == "WebMercatorQuad"
    assert body["pipeline_version"] == "1.0.0"
    assert body["size_bytes"] == 4
    assert body["storage_key"].endswith("/2/3/1.bin")
    assert body["storage_key"].startswith(f"tiles/WebMercatorQuad/{scene.id}/v1.0.0/")


async def test_version_aware_serving(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    client, container = eo_env
    scene = make_available_scene()  # current pipeline_version = 1.0.0
    await container.scenes.add(scene)
    await store_tile(container, scene=scene, z=1, x=1, y=0, data=b"v1", version="1.0.0")
    await store_tile(container, scene=scene, z=1, x=1, y=0, data=b"v2bytes", version="2.0.0")

    default = await client.get(f"{_tiles_base(scene.id)}/1/1/0")
    assert default.content == b"v1"  # scene's current version
    pinned = await client.get(f"{_tiles_base(scene.id)}/1/1/0", params={"version": "2.0.0"})
    assert pinned.content == b"v2bytes"


async def test_missing_tile_is_404(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, container = eo_env
    scene = make_available_scene()
    await container.scenes.add(scene)  # no tiles stored
    response = await client.get(f"{_tiles_base(scene.id)}/5/1/1")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_unprocessed_scene_has_no_tiles(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    client, container = eo_env
    scene = make_discovered_scene()  # no pipeline_version
    await container.scenes.add(scene)
    response = await client.get(f"{_tiles_base(scene.id)}/2/3/1")
    assert response.status_code == 404


async def test_unknown_scene_is_404(eo_env: tuple[AsyncClient, EarthObservationApi]) -> None:
    client, _ = eo_env
    response = await client.get(f"{_tiles_base(uuid4())}/2/3/1")
    assert response.status_code == 404


async def test_out_of_range_tile_coord_is_422(
    eo_env: tuple[AsyncClient, EarthObservationApi],
) -> None:
    client, container = eo_env
    scene = make_available_scene()
    await container.scenes.add(scene)
    # At z=1 the valid x/y range is [0, 2); x=9 is out of range -> domain 422.
    response = await client.get(f"{_tiles_base(scene.id)}/1/9/0")
    assert response.status_code == 422
    assert response.json()["code"] == "value_validation_error"
