"""Story 3 — authorization semantics, run identically against memory and PostgreSQL (A2, A3)."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from tests.authz_support import DAY, ISSUER, NOW, MemoryWorld, SqlWorld, World
from tests.db.conftest import ADMIN_ROLE, APP_ROLE, role_engine

PERM = "eo:scene:read"


@pytest_asyncio.fixture(params=["memory", "postgres"])
async def world(request: pytest.FixtureRequest) -> AsyncIterator[World]:
    if request.param == "memory":
        yield MemoryWorld()
        return
    url = os.environ.get("SATRAK_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("SATRAK_TEST_DATABASE_URL is not set")
    request.getfixturevalue("migrated_database")
    admin, app = role_engine(url, ADMIN_ROLE), role_engine(url, APP_ROLE)
    owner = create_async_engine(url)
    sql = SqlWorld(admin, app, owner)
    await sql.reset()
    try:
        yield sql
    finally:
        await sql.reset()
        await admin.dispose()
        await app.dispose()
        await owner.dispose()


async def _tree(world: World) -> dict[str, uuid.UUID]:
    nat = await world.jurisdiction("IN", "national")
    s1 = await world.jurisdiction("S1", "state", nat)
    s2 = await world.jurisdiction("S2", "state", nat)
    c1 = await world.jurisdiction("C1", "city", s1)
    c2 = await world.jurisdiction("C2", "city", s1)
    c3 = await world.jurisdiction("C3", "city", s2)
    w1 = await world.jurisdiction("W1", "ward", c1)
    return {"nat": nat, "s1": s1, "s2": s2, "c1": c1, "c2": c2, "c3": c3, "w1": w1}


async def _permitted(world: World, user: uuid.UUID, permission: str = PERM) -> frozenset[uuid.UUID]:
    return await world.store.permitted_jurisdictions(user_id=user, permission=permission, at=NOW)


async def test_user_without_assignments_has_no_access(world: World) -> None:
    await _tree(world)
    user = await world.user("nobody")
    assert await _permitted(world, user) == frozenset()


async def test_assignment_covers_the_jurisdiction_and_its_descendants_only(world: World) -> None:
    t = await _tree(world)
    user, role = await world.user("officer"), await world.role("viewer", [PERM])
    await world.assign(user, role, t["c1"])
    assert await _permitted(world, user) == {t["c1"], t["w1"]}


async def test_state_assignment_covers_its_cities_not_siblings_or_parents(world: World) -> None:
    t = await _tree(world)
    user, role = await world.user("state-officer"), await world.role("viewer", [PERM])
    await world.assign(user, role, t["s1"])
    got = await _permitted(world, user)
    assert got == {t["s1"], t["c1"], t["c2"], t["w1"]}
    assert t["s2"] not in got and t["c3"] not in got and t["nat"] not in got


async def test_other_permissions_are_not_implied(world: World) -> None:
    t = await _tree(world)
    user, role = await world.user("u"), await world.role("viewer", [PERM])
    await world.assign(user, role, t["nat"])
    assert await _permitted(world, user, "eo:aoi:write") == frozenset()
    assert await _permitted(world, user, "nonexistent:permission") == frozenset()


async def test_assignments_union_across_roles_and_jurisdictions(world: World) -> None:
    t = await _tree(world)
    user = await world.user("u")
    viewer, other = await world.role("viewer", [PERM]), await world.role("other", ["x:y"])
    await world.assign(user, viewer, t["c1"])
    await world.assign(user, viewer, t["c3"])
    await world.assign(user, other, t["s1"])
    assert await _permitted(world, user) == {t["c1"], t["w1"], t["c3"]}


@pytest.mark.parametrize(
    "window",
    [
        {"revoked": True},
        {"valid_to": NOW - DAY / 2},
        {"valid_from": NOW + DAY, "valid_to": NOW + 2 * DAY},
    ],
    ids=["revoked", "expired", "not-yet-valid"],
)
async def test_inactive_assignments_grant_nothing(world: World, window: dict[str, object]) -> None:
    t = await _tree(world)
    user, role = await world.user("u"), await world.role("viewer", [PERM])
    await world.assign(user, role, t["nat"], **window)  # type: ignore[arg-type]
    assert await _permitted(world, user) == frozenset()


async def test_disabled_user_and_deleted_role_or_jurisdiction_grant_nothing(world: World) -> None:
    t = await _tree(world)
    role = await world.role("viewer", [PERM])
    gone_role = await world.role("gone", [PERM], deleted=True)
    gone_j = await world.jurisdiction("GONE", "city", t["s1"], deleted=True)
    disabled = await world.user("disabled", status="disabled")
    await world.assign(disabled, role, t["nat"])
    assert await _permitted(world, disabled) == frozenset()
    user = await world.user("u")
    await world.assign(user, gone_role, t["nat"])
    await world.assign(user, role, gone_j)
    assert await _permitted(world, user) == frozenset()


async def test_cross_jurisdiction_grant_is_scoped_and_expires(world: World) -> None:
    t = await _tree(world)
    user, role = await world.user("u"), await world.role("viewer", [PERM])
    await world.assign(user, role, t["c1"])
    await world.assign(
        user,
        role,
        t["c3"],
        kind="cross_jurisdiction_grant",
        reason="joint lakebed case",
        valid_to=NOW + DAY,
    )
    assert await _permitted(world, user) == {t["c1"], t["w1"], t["c3"]}
    later = await world.store.permitted_jurisdictions(
        user_id=user, permission=PERM, at=NOW + 2 * DAY
    )
    assert later == {t["c1"], t["w1"]}  # the grant lapsed; the standing assignment did not


async def test_first_sight_creates_a_pending_user_with_no_permissions(world: World) -> None:
    created = await world.store.get_or_create_user(issuer=ISSUER, subject="new-person")
    assert created.status == "pending_role_assignment"
    again = await world.store.get_or_create_user(issuer=ISSUER, subject="new-person")
    assert again.id == created.id
    other_issuer = await world.store.get_or_create_user(
        issuer="https://x.invalid", subject="new-person"
    )
    assert other_issuer.id != created.id
    assert await _permitted(world, created.id) == frozenset()


async def test_concurrent_first_sight_creates_exactly_one_user(world: World) -> None:
    users = await asyncio.gather(
        *[world.store.get_or_create_user(issuer=ISSUER, subject="racer") for _ in range(10)]
    )
    assert len({u.id for u in users}) == 1


# --- Sessions and revocation (Story 5), identical on memory and PostgreSQL ---------------------
async def _register(world: World, user: uuid.UUID, key: str, **kwargs: object) -> object:
    return await world.store.register_session(
        user_id=user,
        issuer=ISSUER,
        session_key=key,
        expires_at=NOW + DAY,
        at=NOW,
        **kwargs,  # type: ignore[arg-type]
    )


async def test_first_use_of_a_session_runs_the_audit_hook_exactly_once(world: World) -> None:
    user = await world.user("s-user")
    calls: list[int] = []

    async def hook() -> None:
        calls.append(1)

    first = await _register(world, user, "sess-1", on_first_seen=hook)
    second = await _register(world, user, "sess-1", on_first_seen=hook)
    assert (first.is_new, first.revoked) == (True, False)  # type: ignore[attr-defined]
    assert (second.is_new, second.revoked) == (False, False)  # type: ignore[attr-defined]
    assert calls == [1]


async def test_failing_audit_hook_rolls_the_registration_back(world: World) -> None:
    user = await world.user("s-user")

    async def broken() -> None:
        raise RuntimeError("audit down")

    with pytest.raises(RuntimeError):
        await _register(world, user, "sess-2", on_first_seen=broken)
    retry = await _register(world, user, "sess-2")
    assert retry.is_new is True  # type: ignore[attr-defined]


async def test_revoked_session_is_reported_revoked_and_stays_revoked(world: World) -> None:
    user, admin = await world.user("s-user"), await world.user("admin")
    await _register(world, user, "sess-3")
    kwargs = {
        "user_id": user,
        "issuer": ISSUER,
        "session_key": "sess-3",
        "expires_at": NOW + DAY,
        "revoked_by": admin,
        "reason": "test",
        "at": NOW,
    }
    await world.store.revoke_session(**kwargs)  # type: ignore[arg-type]
    await world.store.revoke_session(**kwargs)  # idempotent
    assert (await _register(world, user, "sess-3")).revoked is True  # type: ignore[attr-defined]


async def test_a_session_can_be_revoked_before_it_is_ever_used(world: World) -> None:
    user, admin = await world.user("s-user"), await world.user("admin")
    await world.store.revoke_session(
        user_id=user,
        issuer=ISSUER,
        session_key="never-seen",
        expires_at=NOW + DAY,
        revoked_by=admin,
        reason="stolen",
        at=NOW,
    )
    state = await _register(world, user, "never-seen")
    assert (state.is_new, state.revoked) == (False, True)  # type: ignore[attr-defined]


async def test_a_session_key_is_bound_to_the_user_that_first_used_it(world: World) -> None:
    owner, intruder = await world.user("owner"), await world.user("intruder")
    await _register(world, owner, "sess-4")
    assert (await _register(world, intruder, "sess-4")).revoked is True  # type: ignore[attr-defined]
    assert (await _register(world, owner, "sess-4")).revoked is False  # type: ignore[attr-defined]


async def test_user_revocation_sets_revoked_before_and_never_moves_backwards(world: World) -> None:
    user, admin = await world.user("s-user"), await world.user("admin")
    store = world.store
    await store.revoke_user_sessions(user_id=user, at=NOW, revoked_by=admin, reason="x")
    await store.revoke_user_sessions(user_id=user, at=NOW - DAY, revoked_by=admin, reason="older")
    fetched = await store.get_or_create_user(issuer=ISSUER, subject="s-user")
    assert fetched.revoked_before == NOW


async def test_assignment_jurisdictions_lists_only_live_assignments(world: World) -> None:
    t = await _tree(world)
    user, role = await world.user("assigned"), await world.role("viewer", [PERM])
    await world.assign(user, role, t["c1"])
    await world.assign(user, role, t["c2"], revoked=True)
    everything = frozenset(t.values())
    assigned = await world.store.assignment_jurisdictions(user_id=user, within=everything)
    assert assigned == {t["c1"]}
    # Only assignments inside the caller's scope are visible to it.
    elsewhere = frozenset({t["c3"]})
    assert await world.store.assignment_jurisdictions(user_id=user, within=elsewhere) == frozenset()
    unknown = await world.store.assignment_jurisdictions(user_id=uuid.uuid4(), within=everything)
    assert unknown == frozenset()
