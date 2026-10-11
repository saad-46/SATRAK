"""Story 3 — server-side permission enforcement on routes (A2, A3, A8)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import require_permission
from app.core.authz import AccessContext, AccessUser
from app.core.config import Settings
from app.main import create_app
from tests.auth_support import TEST_ISSUER, TestIdp
from tests.authz_support import NOW, InMemoryAccessStore, MemoryWorld

PERM = "eo:scene:read"


@dataclass
class Env:
    client: AsyncClient
    idp: TestIdp
    world: MemoryWorld
    jurisdictions: dict[str, uuid.UUID]
    app: FastAPI

    def headers(self, subject: str) -> dict[str, str]:
        return self.idp.bearer(claims={"sub": subject})


def _add_probe_routes(app: FastAPI, objects: dict[str, uuid.UUID]) -> None:
    @app.get("/__probe/list")
    async def list_objects(
        ctx: AccessContext = Depends(require_permission(PERM)),
    ) -> dict[str, list[str]]:
        return {"visible": sorted(k for k, v in objects.items() if ctx.allows(v))}

    @app.get("/__probe/object/{name}")
    async def get_object(
        name: str, ctx: AccessContext = Depends(require_permission(PERM))
    ) -> dict[str, str]:
        ctx.require(objects.get(name))
        return {"name": name}


@pytest_asyncio.fixture
async def env(settings: Settings, idp: TestIdp) -> AsyncIterator[Env]:
    world = MemoryWorld()
    nat = await world.jurisdiction("IN", "national")
    s1 = await world.jurisdiction("S1", "state", nat)
    c1 = await world.jurisdiction("C1", "city", s1)
    c2 = await world.jurisdiction("C2", "city", s1)
    c3 = await world.jurisdiction("C3", "city", await world.jurisdiction("S2", "state", nat))
    viewer = await world.role("viewer", [PERM])
    # Local users are keyed by (issuer, subject); the token's subject selects the user.
    for subject, where in (("alice", c1), ("bob", s1), ("carol", c3)):
        uid = await world.user(subject)
        world.store.users[uid] = (TEST_ISSUER, subject, "active")
        await world.assign(uid, viewer, where)
    jurisdictions = {"c1": c1, "c2": c2, "c3": c3, "s1": s1}
    app = create_app(
        settings, auth=idp.runtime(settings.auth), access=world.store, audit=world.audit
    )
    _add_probe_routes(app, jurisdictions)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield Env(client, idp, world, jurisdictions, app)


async def test_unauthenticated_is_401_not_403(env: Env) -> None:
    assert (await env.client.get("/__probe/list")).status_code == 401


async def test_user_without_any_grant_gets_403_and_is_provisioned_pending(env: Env) -> None:
    response = await env.client.get("/__probe/list", headers=env.headers("stranger"))
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    stored = [u for u in env.world.store.users.values() if u[1] == "stranger"]
    assert stored and stored[0][2] == "pending_role_assignment"


async def test_lists_are_limited_to_permitted_jurisdictions(env: Env) -> None:
    alice = await env.client.get("/__probe/list", headers=env.headers("alice"))
    bob = await env.client.get("/__probe/list", headers=env.headers("bob"))
    carol = await env.client.get("/__probe/list", headers=env.headers("carol"))
    assert alice.json()["visible"] == ["c1"]
    assert bob.json()["visible"] == ["c1", "c2", "s1"]
    assert carol.json()["visible"] == ["c3"]


async def test_cross_jurisdiction_object_access_is_403(env: Env) -> None:
    ok = await env.client.get("/__probe/object/c1", headers=env.headers("alice"))
    assert ok.status_code == 200
    for name in ("c2", "c3", "s1", "does-not-exist"):
        denied = await env.client.get(f"/__probe/object/{name}", headers=env.headers("alice"))
        assert denied.status_code == 403, name
        body = denied.json()
        # The denial never describes the object (the random request id is excluded: it can
        # contain any short hex string by chance).
        assert (
            name
            not in {k: v for k, v in body.items() if k not in {"instance", "request_id"}}.values()
        )
        assert "detail" in body and name not in body["detail"]


async def test_disabled_account_is_403(env: Env) -> None:
    uid = await env.world.user("dave", status="disabled")
    env.world.store.users[uid] = (TEST_ISSUER, "dave", "disabled")
    response = await env.client.get("/__probe/list", headers=env.headers("dave"))
    assert response.status_code == 403
    assert response.json()["code"] == "account_disabled"


@pytest.mark.parametrize(
    "spoof",
    [
        {"X-Jurisdiction-Id": "everything"},
        {"X-Tenant-Id": "S2"},
        {"X-User-Id": "bob"},
        {"X-Forwarded-User": "bob"},
    ],
)
async def test_client_supplied_identity_or_jurisdiction_headers_are_ignored(
    env: Env, spoof: dict[str, str]
) -> None:
    response = await env.client.get("/__probe/list", headers={**env.headers("alice"), **spoof})
    assert response.json()["visible"] == ["c1"]
    query = await env.client.get(
        "/__probe/list?jurisdiction_id=all&tenant_id=x", headers=env.headers("alice")
    )
    assert query.json()["visible"] == ["c1"]


async def test_token_claims_do_not_grant_permissions(env: Env) -> None:
    claims = {"sub": "stranger2", "roles": ["admin"], "permissions": [PERM], "scope": PERM}
    response = await env.client.get("/__probe/list", headers=env.idp.bearer(claims=claims))
    assert response.status_code == 403


async def test_store_failure_fails_closed_with_503(env: Env) -> None:
    class Broken(InMemoryAccessStore):
        async def permitted_jurisdictions(self, **kwargs: object):  # type: ignore[no-untyped-def]
            raise RuntimeError("db down")

    env.app.state.access = Broken(
        users=env.world.store.users,
        parents=env.world.store.parents,
        roles=env.world.store.roles,
        assignments=env.world.store.assignments,
    )
    response = await env.client.get("/__probe/list", headers=env.headers("alice"))
    assert response.status_code == 503
    assert response.json()["code"] == "authz_unavailable"


async def test_missing_store_fails_closed(env: Env) -> None:
    env.app.state.access = None
    response = await env.client.get("/__probe/list", headers=env.headers("alice"))
    assert response.status_code == 503


def test_access_context_defaults_to_deny() -> None:
    ctx = AccessContext(uuid.uuid4(), PERM, frozenset())
    assert not ctx.allows(None)
    assert not ctx.allows(uuid.uuid4())
    assert ctx.visible([None, uuid.uuid4()]) == []
    assert AccessUser(uuid.uuid4(), "disabled").is_disabled
    assert NOW.tzinfo is not None
