"""Story 5 — revocation takes effect on the next request, everywhere; every outcome is audited
(A5, A6, A7; ADR-0013 E/F)."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.security_audit import (
    ACCESS_DENIED,
    SESSION_REVOKED,
    USER_LOGGED_IN,
    USER_LOGIN_FAILED,
    canonical_fields,
)
from app.main import create_app
from tests.auth_support import TEST_ISSUER, TestIdp
from tests.authz_support import MemoryWorld

PROBE = "/api/v1/system/info"  # authentication-only route
ADMIN_ROLE = ["session:revoke"]


@dataclass
class Env:
    world: MemoryWorld
    idp: TestIdp
    app: FastAPI
    client: AsyncClient
    users: dict[str, uuid.UUID]
    jurisdictions: dict[str, uuid.UUID]

    def token(self, subject: str, **claims: object) -> dict[str, str]:
        return self.idp.bearer(claims={"sub": subject, **claims})

    def second_instance(self, settings: Settings) -> AsyncClient:
        """A separate app instance sharing only the (external) store and audit log."""
        other = create_app(
            settings,
            auth=self.idp.runtime(settings.auth),
            access=self.world.store,
            audit=self.world.audit,
        )
        return AsyncClient(transport=ASGITransport(app=other), base_url="http://test")


@pytest_asyncio.fixture
async def env(settings: Settings, idp: TestIdp) -> AsyncIterator[Env]:
    world = MemoryWorld()
    nat = await world.jurisdiction("IN", "national")
    s1 = await world.jurisdiction("S1", "state", nat)
    s2 = await world.jurisdiction("S2", "state", nat)
    admin_role = await world.role("session-admin", ADMIN_ROLE)
    plain_role = await world.role("officer", ["eo:scene:read"])
    users: dict[str, uuid.UUID] = {}
    for subject, role, where in (
        ("admin-s1", admin_role, s1),
        ("officer-s1", plain_role, s1),
        ("officer-s2", plain_role, s2),
        ("plain", plain_role, s1),
    ):
        uid = await world.user(subject)
        world.store.users[uid] = (TEST_ISSUER, subject, "active")
        await world.assign(uid, role, where)
        users[subject] = uid
    loner = await world.user("unassigned")
    world.store.users[loner] = (TEST_ISSUER, "unassigned", "active")
    users["unassigned"] = loner
    app = create_app(
        settings, auth=idp.runtime(settings.auth), access=world.store, audit=world.audit
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield Env(world, idp, app, client, users, {"s1": s1, "s2": s2})


# --- Logout / self revocation ---------------------------------------------------------------
async def test_logout_rejects_that_session_on_its_next_request(env: Env) -> None:
    mine = env.token("officer-s1", sid="session-a")
    other_session = env.token("officer-s1", sid="session-b")
    assert (await env.client.get(PROBE, headers=mine)).status_code == 200

    assert (await env.client.post("/api/v1/auth/logout", headers=mine)).status_code == 204

    revoked = await env.client.get(PROBE, headers=mine)
    assert revoked.status_code == 401
    assert revoked.json()["code"] == "invalid_token"
    assert 'error="invalid_token"' in revoked.headers["www-authenticate"]
    assert (await env.client.get(PROBE, headers=other_session)).status_code == 200


async def test_logout_without_session_id_revokes_by_token_id(env: Env) -> None:
    headers = env.token("officer-s1", jti="only-jti")
    assert (await env.client.get(PROBE, headers=headers)).status_code == 200
    await env.client.post("/api/v1/auth/logout", headers=headers)
    assert (await env.client.get(PROBE, headers=headers)).status_code == 401


async def test_revocation_response_does_not_reveal_why(env: Env) -> None:
    headers = env.token("officer-s1", sid="s")
    await env.client.get(PROBE, headers=headers)
    await env.client.post("/api/v1/auth/logout", headers=headers)
    revoked = await env.client.get(PROBE, headers=headers)
    assert "revoked" not in revoked.text.lower()


# --- Administrator revocation ---------------------------------------------------------------
async def test_admin_revokes_all_of_a_users_existing_tokens(env: Env) -> None:
    before = [env.token("officer-s1", sid=f"s{i}") for i in range(3)]
    for headers in before:
        assert (await env.client.get(PROBE, headers=headers)).status_code == 200

    started = time.monotonic()
    response = await env.client.post(
        f"/api/v1/admin/users/{env.users['officer-s1']}/revoke-sessions",
        json={"reason": "lost laptop"},
        headers=env.token("admin-s1"),
    )
    assert response.status_code == 204
    for headers in before:
        assert (await env.client.get(PROBE, headers=headers)).status_code == 401
    propagation = time.monotonic() - started  # measured, not assumed (NFR-18.2: < 60 s)
    assert propagation < 5.0

    # A token issued after the revocation instant works again (new login at the IdP).
    later = env.token("officer-s1", sid="fresh", iat=int(time.time()) + 3)
    assert (await env.client.get(PROBE, headers=later)).status_code == 200
    # Other users are unaffected.
    assert (await env.client.get(PROBE, headers=env.token("plain"))).status_code == 200


async def test_admin_revokes_a_single_session_even_before_it_is_first_used(env: Env) -> None:
    response = await env.client.post(
        "/api/v1/admin/sessions/revoke",
        json={
            "user_id": str(env.users["officer-s1"]),
            "session_key": "pre-revoked",
            "reason": "stolen device",
        },
        headers=env.token("admin-s1"),
    )
    assert response.status_code == 204
    headers = env.token("officer-s1", sid="pre-revoked")
    assert (await env.client.get(PROBE, headers=headers)).status_code == 401
    assert not [
        e
        for e in env.world.audit.of_type(USER_LOGGED_IN)
        if e.actor_user_id == env.users["officer-s1"]
    ]


async def test_revocation_is_visible_to_a_second_application_instance(
    env: Env, settings: Settings
) -> None:
    headers = env.token("officer-s1", sid="shared")
    async with env.second_instance(settings) as other:
        assert (await other.get(PROBE, headers=headers)).status_code == 200
        assert (await env.client.get(PROBE, headers=headers)).status_code == 200
        await env.client.post("/api/v1/auth/logout", headers=headers)
        assert (await other.get(PROBE, headers=headers)).status_code == 401


async def test_a_session_key_cannot_be_borrowed_by_another_user(env: Env) -> None:
    assert (
        await env.client.get(PROBE, headers=env.token("officer-s1", sid="x"))
    ).status_code == 200
    assert (
        await env.client.get(PROBE, headers=env.token("officer-s2", sid="x"))
    ).status_code == 401


# --- Who may revoke --------------------------------------------------------------------------
async def test_only_session_admins_in_scope_may_revoke(env: Env) -> None:
    path = lambda who: f"/api/v1/admin/users/{env.users[who]}/revoke-sessions"  # noqa: E731
    body = {"reason": "testing"}
    # No session:revoke anywhere.
    denied = await env.client.post(path("officer-s1"), json=body, headers=env.token("plain"))
    assert denied.status_code == 403
    # Admin of S1 may not revoke a user assigned only in S2, nor an unassigned account.
    for target in ("officer-s2", "unassigned"):
        denied = await env.client.post(path(target), json=body, headers=env.token("admin-s1"))
        assert denied.status_code == 403, target
    # Unauthenticated callers never reach the handler.
    assert (await env.client.post(path("officer-s1"), json=body)).status_code == 401
    # Nothing was revoked by the failed attempts.
    assert env.world.store.revoked_before == {}


async def test_revocation_requires_a_reason(env: Env) -> None:
    response = await env.client.post(
        f"/api/v1/admin/users/{env.users['officer-s1']}/revoke-sessions",
        json={"reason": ""},
        headers=env.token("admin-s1"),
    )
    assert response.status_code == 422


# --- Fail closed ------------------------------------------------------------------------------
class _BrokenSessions:
    """Wraps the memory store but fails session lookups, as a database outage would."""

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    async def register_session(self, **_: object) -> object:
        raise ConnectionError("database down")


async def test_session_store_outage_denies_instead_of_allowing(
    env: Env, settings: Settings
) -> None:
    broken = create_app(
        settings,
        auth=env.idp.runtime(settings.auth),
        access=_BrokenSessions(env.world.store),  # type: ignore[arg-type]
        audit=env.world.audit,
    )
    headers = env.token("officer-s1", sid="o")
    async with AsyncClient(transport=ASGITransport(app=broken), base_url="http://test") as client:
        response = await client.get(PROBE, headers=headers)
    assert response.status_code == 503
    assert response.json()["code"] == "authz_unavailable"


async def test_audit_outage_blocks_new_sessions_and_does_not_lose_the_login(env: Env) -> None:
    headers = env.token("officer-s1", sid="audit-down")
    env.world.audit.fail = True
    blocked = await env.client.get(PROBE, headers=headers)
    assert blocked.status_code == 503
    assert blocked.json()["code"] == "audit_unavailable"
    assert ("https://issuer.example.invalid", "audit-down") not in env.world.store.sessions

    env.world.audit.fail = False  # recovery: the same token is a first login again, now audited
    assert (await env.client.get(PROBE, headers=headers)).status_code == 200
    assert len(env.world.audit.of_type(USER_LOGGED_IN)) == 1


async def test_audit_outage_never_turns_a_refusal_into_an_allow(env: Env) -> None:
    headers = env.token("plain", sid="p")
    await env.client.get(PROBE, headers=headers)
    env.world.audit.fail = True
    # Existing session, so authentication proceeds; the permission check still denies.
    denied = await env.client.get("/api/v1/eo/aoi", headers=headers)
    assert denied.status_code == 403
    bad = await env.client.get(PROBE, headers={"Authorization": "Bearer not.a.jwt"})
    assert bad.status_code == 401


# --- Audit trail -------------------------------------------------------------------------------
async def test_login_is_audited_once_per_session(env: Env) -> None:
    headers = env.token("officer-s1", sid="audited")
    for _ in range(3):
        await env.client.get(PROBE, headers=headers)
    events = env.world.audit.of_type(USER_LOGGED_IN)
    assert len(events) == 1
    assert (events[0].actor_user_id, events[0].outcome) == (env.users["officer-s1"], "success")
    assert events[0].request_id is not None


async def test_failed_authentication_is_audited_with_a_reason_code_only(env: Env) -> None:
    bad_token = env.idp.token(claims={"aud": "someone-else"})
    await env.client.get(PROBE, headers={"Authorization": f"Bearer {bad_token}"})
    (event,) = env.world.audit.of_type(USER_LOGIN_FAILED)
    assert event.outcome == "failure" and event.details == {"reason": "bad_audience"}
    assert bad_token not in canonical_fields(event)


async def test_denials_are_audited_with_permission_and_jurisdiction(env: Env) -> None:
    headers = env.token("plain", sid="d")
    await env.client.get("/api/v1/eo/aoi", headers=headers)  # no eo:aoi:read
    (event,) = env.world.audit.of_type(ACCESS_DENIED)
    assert event.permission == "eo:aoi:read"
    assert event.actor_user_id == env.users["plain"]
    assert event.details["path"] == "/api/v1/eo/aoi"


async def test_revocations_are_audited_with_actor_target_and_reason(env: Env) -> None:
    await env.client.post(
        f"/api/v1/admin/users/{env.users['officer-s1']}/revoke-sessions",
        json={"reason": "lost laptop"},
        headers=env.token("admin-s1"),
    )
    (event,) = env.world.audit.of_type(SESSION_REVOKED)
    assert event.actor_user_id == env.users["admin-s1"]
    assert event.details == {
        "target_user": str(env.users["officer-s1"]),
        "scope": "user",
        "reason": "lost laptop",
    }


async def test_no_audit_event_ever_contains_a_token(env: Env) -> None:
    tokens = [env.idp.token(claims={"sub": "plain", "sid": f"t{i}"}) for i in range(2)]
    for token in tokens:
        headers = {"Authorization": f"Bearer {token}"}
        await env.client.get(PROBE, headers=headers)
        await env.client.get("/api/v1/eo/aoi", headers=headers)
    await env.client.get(PROBE, headers={"Authorization": "Bearer bad.token.value"})
    assert env.world.audit.events
    blob = " ".join(canonical_fields(e) for e in env.world.audit.events)
    assert "bad.token.value" not in blob and not any(t in blob for t in tokens)
    assert (await env.world.audit.verify_chain()).ok


def test_timestamps_are_timezone_aware() -> None:
    assert datetime.now(UTC) - timedelta(seconds=1) < datetime.now(UTC)
