"""Story 6 — rate limiting at the HTTP layer (A12): policies, identity, failure handling."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.ratelimit import limit_user
from app.core.config import Environment, RateLimitSettings, RatePolicySpec, Settings
from app.core.ratelimit import (
    Decision,
    InMemoryRateLimiter,
    RateLimiter,
    RateLimiterUnavailable,
    Rule,
)
from app.main import create_app
from tests.api.eo_support import HOME
from tests.auth_support import TEST_ISSUER, TestIdp, auth_settings
from tests.authz_support import MemoryWorld

SYSTEM = "/api/v1/system/info"
PERMS = ["eo:scene:read", "eo:aoi:read", "eo:tile:read", "session:revoke", "system:metrics:read"]


def _spec(limit: int, window: int = 60) -> list[RatePolicySpec]:
    return [RatePolicySpec(limit=limit, window_seconds=window)]


class RecordingLimiter:
    """Delegates to a real limiter and remembers every rule key it was asked to count."""

    def __init__(self, inner: RateLimiter) -> None:
        self.inner = inner
        self.keys: list[str] = []

    async def hit(self, rules: Sequence[Rule]) -> Decision:
        self.keys += [r.key for r in rules]
        return await self.inner.hit(rules)

    async def blocked_for(self, key: str) -> int:
        return await self.inner.blocked_for(key)

    async def record_failure(self, key: str, **kwargs: int) -> int:
        return await self.inner.record_failure(key, **kwargs)


class DownLimiter:
    """A limiter whose shared state is unreachable (Redis outage)."""

    async def hit(self, rules: Sequence[Rule]) -> Decision:
        raise RateLimiterUnavailable("down")

    async def blocked_for(self, key: str) -> int:
        raise RateLimiterUnavailable("down")

    async def record_failure(self, key: str, **kwargs: int) -> int:
        raise RateLimiterUnavailable("down")


@dataclass
class Env:
    settings: Settings
    idp: TestIdp
    world: MemoryWorld
    limiter: RecordingLimiter
    app: FastAPI
    client: AsyncClient
    extra: dict[str, object] = field(default_factory=dict)

    def headers(self, subject: str = "officer", **extra_headers: str) -> dict[str, str]:
        return {**self.idp.bearer(claims={"sub": subject}), **extra_headers}

    def rebuild(self, limiter: RateLimiter, **settings_changes: object) -> AsyncClient:
        settings = self.settings.model_copy(update=settings_changes)
        app = create_app(
            settings,
            auth=self.idp.runtime(settings.auth),
            access=self.world.store,
            audit=self.world.audit,
            rate_limiter=limiter,
        )
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _settings(**overrides: list[RatePolicySpec]) -> Settings:
    return Settings(
        environment=Environment.TEST,
        log_format="console",
        auth=auth_settings(),
        rate_limit=RateLimitSettings(enabled=True, overrides=overrides, fallback_per_minute=3),
    )


async def _make_env(idp: TestIdp, settings: Settings) -> tuple[Env, AsyncClient]:
    world = MemoryWorld()
    world.store.parents[HOME] = None
    role = await world.role("all", PERMS)
    for subject in ("officer", "other", "admin"):
        uid = await world.user(subject)
        world.store.users[uid] = (TEST_ISSUER, subject, "active")
        await world.assign(uid, role, HOME)
    limiter = RecordingLimiter(InMemoryRateLimiter())
    app = create_app(
        settings,
        auth=idp.runtime(settings.auth),
        access=world.store,
        audit=world.audit,
        rate_limiter=limiter,
    )

    @app.get(
        "/__probe/expensive", dependencies=[Depends(limit_user("expensive_user", critical=True))]
    )
    async def expensive() -> dict[str, str]:
        return {"ok": "yes"}

    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return Env(settings, idp, world, limiter, app, client), client


@pytest_asyncio.fixture
async def env(idp: TestIdp) -> AsyncIterator[Env]:
    e, client = await _make_env(
        idp,
        _settings(
            api_user=_spec(5),
            eo_search_user=_spec(2),
            tiles_user=_spec(3),
            admin_user=_spec(2),
            auth_entry_ip=_spec(2),
            auth_failure_ip=_spec(3),
            expensive_user=[RatePolicySpec(limit=2, window_seconds=60)],
        ),
    )
    async with client:
        yield e


async def _statuses(client: AsyncClient, method: str, path: str, n: int, **kw: object) -> list[int]:
    return [(await client.request(method, path, **kw)).status_code for _ in range(n)]  # type: ignore[arg-type]


# --- Per-user budgets ------------------------------
async def test_ordinary_api_is_limited_per_user_with_retry_after(env: Env) -> None:
    headers = env.headers()
    assert await _statuses(env.client, "GET", SYSTEM, 5, headers=headers) == [200] * 5
    limited = await env.client.get(SYSTEM, headers=headers)
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    assert limited.headers["content-type"].startswith("application/problem+json")
    # Another user is unaffected by this user's exhaustion.
    assert (await env.client.get(SYSTEM, headers=env.headers("other"))).status_code == 200


async def test_the_same_user_on_new_tokens_shares_one_budget(env: Env) -> None:
    codes = [(await env.client.get(SYSTEM, headers=env.headers())).status_code for _ in range(7)]
    assert codes == [200] * 5 + [429] * 2


async def test_eo_search_has_its_own_tighter_budget(env: Env) -> None:
    headers = env.headers()
    assert await _statuses(env.client, "GET", "/api/v1/eo/scenes", 2, headers=headers) == [200, 200]
    assert (await env.client.get("/api/v1/eo/scenes", headers=headers)).status_code == 429
    # A non-search route is still available (and counted against the ordinary budget).
    assert (await env.client.get("/api/v1/eo/aoi", headers=headers)).status_code == 200


async def test_tiles_use_a_separate_budget_from_ordinary_requests(env: Env) -> None:
    headers = env.headers("other")
    path = f"/api/v1/eo/scenes/{uuid.uuid4()}/tiles/1/0/0"
    codes = await _statuses(env.client, "GET", path, 4, headers=headers)
    assert codes[:3] == [404, 404, 404] and codes[3] == 429  # 404 = reached the handler
    assert (await env.client.get(SYSTEM, headers=headers)).status_code == 200  # not charged


async def test_admin_routes_have_a_tight_budget(env: Env) -> None:
    uid = uuid.uuid4()
    statuses = [
        (
            await env.client.post(
                f"/api/v1/admin/users/{uid}/revoke-sessions",
                json={"reason": "testing"},
                headers=env.headers("admin"),
            )
        ).status_code
        for _ in range(3)
    ]
    # The first two reach the handler (a national admin may revoke any id); the third is limited.
    assert statuses[:2] == [204, 204] and statuses[2] == 429


async def test_expensive_operations_enforce_per_minute_and_per_hour_budgets(idp: TestIdp) -> None:
    e, client = await _make_env(
        idp,
        _settings(
            expensive_user=[
                RatePolicySpec(limit=5, window_seconds=60),
                RatePolicySpec(limit=2, window_seconds=3600),
            ]
        ),
    )
    async with client:
        codes = await _statuses(client, "GET", "/__probe/expensive", 4, headers=e.headers())
    assert codes == [200, 200, 429, 429]


def test_default_policies_match_the_approved_starting_values() -> None:
    settings = RateLimitSettings()
    expected = {
        "auth_entry_ip": [(10, 60)],
        "auth_failure_ip": [(10, 60)],
        "api_user": [(120, 60)],
        "eo_search_user": [(30, 60)],
        "expensive_user": [(5, 60), (30, 3600)],
        "admin_user": [(10, 60)],
    }
    for name, rules in expected.items():
        assert [(s.limit, s.window_seconds) for s in settings.policy(name)] == rules, name


# --- Identity: the caller cannot choose their own bucket ------------------------------
async def test_client_supplied_identity_headers_do_not_change_the_budget(env: Env) -> None:
    spoofed = {
        "X-User-Id": "someone-else",
        "X-Jurisdiction-Id": str(uuid.uuid4()),
        "X-Forwarded-For": "203.0.113.7",
    }
    for i in range(5):
        r = await env.client.get(SYSTEM, headers=env.headers(**{**spoofed, "X-User-Id": f"u{i}"}))
        assert r.status_code == 200
    limited = await env.client.get(SYSTEM, headers=env.headers(**spoofed))
    assert limited.status_code == 429


async def test_unauthenticated_callers_cannot_escape_by_rotating_identities(env: Env) -> None:
    codes = []
    for i in range(6):
        r = await env.client.get(
            SYSTEM,
            headers={
                "Authorization": f"Bearer forged.token.{i}",
                "X-User-Id": f"user-{i}",
                "X-Forwarded-For": f"198.51.100.{i}",
            },
        )
        codes.append(r.status_code)
    # Three failures are tolerated; the fourth triggers the block, which then applies to
    # every further request from this address, whatever identity it claims.
    assert codes[:4] == [401, 401, 401, 401]
    assert codes[4:] == [429, 429]


async def test_forwarded_for_is_trusted_only_behind_configured_proxies(env: Env) -> None:
    async with env.rebuild(
        env.limiter.inner,
        rate_limit=env.settings.rate_limit.model_copy(update={"trusted_proxy_hops": 1}),
    ) as proxied:
        for ip in ("198.51.100.1", "198.51.100.2"):
            # Each real client (the entry our proxy appended) gets its own failure budget...
            codes = [
                (
                    await proxied.get(
                        SYSTEM,
                        headers={
                            "Authorization": "Bearer bad.token.x",
                            "X-Forwarded-For": f"6.6.6.6, {ip}",  # left entry is forged
                        },
                    )
                ).status_code
                for _ in range(4)
            ]
            assert codes == [401, 401, 401, 401], ip
        blocked = await proxied.get(
            SYSTEM,
            headers={
                "Authorization": "Bearer bad.token.x",
                "X-Forwarded-For": "1.1.1.1, 198.51.100.1",
            },
        )
        assert blocked.status_code == 429  # forging the left entry did not help


# --- Authentication abuse ------------------------------
async def test_repeated_failures_block_the_source_progressively(env: Env) -> None:
    bad = {"Authorization": "Bearer bad.token.value"}
    assert await _statuses(env.client, "GET", SYSTEM, 4, headers=bad) == [401] * 4
    blocked = await env.client.get(SYSTEM, headers=env.headers())  # even a valid token
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) == 60  # first strike = base penalty


async def test_logout_is_a_per_ip_auth_entry_point(env: Env) -> None:
    codes = [
        (await env.client.post("/api/v1/auth/logout", headers=env.headers(f"u{i}"))).status_code
        for i in range(3)
    ]
    # Unknown subjects are provisioned with no permissions but may log out; 2 per IP allowed.
    assert codes[:2] == [204, 204] and codes[2] == 429


# --- Failure handling ------------------------------
async def test_limiter_outage_fails_closed_for_the_auth_entry_point(env: Env) -> None:
    async with env.rebuild(DownLimiter()) as client:
        r = await client.post("/api/v1/auth/logout", headers=env.headers())
    assert r.status_code == 503
    assert r.json()["code"] == "rate_limit_unavailable"
    assert r.headers["retry-after"] == "5"


async def test_expensive_probe_fails_closed_when_the_limiter_is_down(idp: TestIdp) -> None:
    e, client = await _make_env(idp, _settings())
    e.app.state.rate_limiter = DownLimiter()
    async with client:
        r = await client.get("/__probe/expensive", headers=e.headers())
    assert r.status_code == 503 and r.json()["code"] == "rate_limit_unavailable"


async def test_limiter_outage_degrades_to_a_strict_local_budget_never_to_unlimited(
    env: Env,
) -> None:
    async with env.rebuild(DownLimiter()) as client:
        codes = [(await client.get(SYSTEM, headers=env.headers())).status_code for _ in range(8)]
    # fallback_per_minute=3 per key (the per-IP ceiling and the per-user budget are both local)
    assert codes[:3] == [200, 200, 200]
    assert set(codes[3:]) == {429}


# --- Concurrency and coverage ------------------------------
async def test_concurrent_requests_cannot_exceed_the_budget(env: Env) -> None:
    headers = env.headers()
    results = await asyncio.gather(*(env.client.get(SYSTEM, headers=headers) for _ in range(40)))
    assert sorted(r.status_code for r in results).count(200) == 5


async def test_every_authenticated_operation_is_charged_to_a_user_budget(idp: TestIdp) -> None:
    from tests.api.test_auth_api import PUBLIC_PATHS, _concrete, _operations

    e, client = await _make_env(idp, _settings())  # generous defaults
    uncharged = []
    async with client:
        for method, path in _operations(e.app):
            if path in PUBLIC_PATHS:
                continue
            before = len(e.limiter.keys)
            await client.request(
                method,
                _concrete(path).replace("/x", f"/{uuid.uuid4()}"),
                headers=e.headers(),
                json={"reason": "coverage", "user_id": str(uuid.uuid4()), "session_key": "k"}
                if method in {"POST", "PUT", "PATCH"}
                else None,
            )
            charged = e.limiter.keys[before:]
            if not any(":u:" in key for key in charged):
                uncharged.append((method, path))
    assert uncharged == []


# --- Configuration ------------------------------
def test_unknown_policy_overrides_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown rate limit policies"):
        RateLimitSettings(overrides={"nonsense": _spec(1)})


def test_production_cannot_disable_limits_or_run_without_redis() -> None:
    base = {"environment": Environment.PRODUCTION, "auth": auth_settings(), "log_format": "console"}
    with pytest.raises(ValueError, match="rate limiting cannot be disabled"):
        Settings(**base, rate_limit=RateLimitSettings(enabled=False), redis_url="redis://r:6379/0")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="requires redis_url"):
        Settings(**base, rate_limit=RateLimitSettings())  # type: ignore[arg-type]
    Settings(**base, rate_limit=RateLimitSettings(), redis_url="redis://r:6379/0")  # type: ignore[arg-type]


# --- Degraded-mode observability and operational endpoints --------------------------------------
def _counter(name: str, **labels: str) -> int:
    from app.core.metrics import metrics

    return sum(
        int(c["value"])  # type: ignore[call-overload]
        for c in metrics.snapshot()["counters"]  # type: ignore[attr-defined]
        if c["name"] == name and all(c["labels"].get(k) == v for k, v in labels.items())  # type: ignore[index, attr-defined]
    )


async def test_degraded_mode_is_counted_by_mode_and_exposed_to_operators(env: Env) -> None:
    before_closed = _counter("rate_limiter_unavailable_total", mode="fail_closed")
    before_local = _counter("rate_limiter_unavailable_total", mode="local_fallback")
    before_denied = _counter("rate_limit_fallback_decisions_total", outcome="denied")
    async with env.rebuild(DownLimiter()) as client:
        await client.post("/api/v1/auth/logout", headers=env.headers())  # critical
        for _ in range(6):  # ordinary traffic exhausts the strict local budget
            await client.get(SYSTEM, headers=env.headers())
    assert _counter("rate_limiter_unavailable_total", mode="fail_closed") > before_closed
    assert _counter("rate_limiter_unavailable_total", mode="local_fallback") > before_local
    assert _counter("rate_limit_fallback_decisions_total", outcome="denied") > before_denied

    r = await env.client.get(
        "/api/v1/system/metrics?format=prometheus", headers=env.headers("admin")
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "satrak_rate_limiter_unavailable_total{" in r.text
    assert "satrak_rate_limiter_degraded_last_timestamp_seconds" in r.text
    as_json = await env.client.get("/api/v1/system/metrics", headers=env.headers("admin"))
    assert "rate_limiter_degraded" in as_json.json()["last_events"]


async def test_metrics_need_the_permission_at_national_scope(env: Env) -> None:
    url = "/api/v1/system/metrics"
    assert (await env.client.get(url)).status_code == 401
    assert (await env.client.get(url, headers=env.headers("nobody"))).status_code == 403
    # A holder of the permission in a narrower (non-national) jurisdiction is still refused.
    narrow = uuid.uuid4()
    env.world.store.parents[narrow] = HOME
    role = await env.world.role("metrics-local", ["system:metrics:read"])
    uid = await env.world.user("local-admin")
    env.world.store.users[uid] = (TEST_ISSUER, "local-admin", "active")
    await env.world.assign(uid, role, narrow)
    assert (await env.client.get(url, headers=env.headers("local-admin"))).status_code == 403


async def test_readiness_is_cached_and_reveals_no_internals(idp: TestIdp) -> None:
    e, client = await _make_env(idp, _settings())
    async with client:
        first = await client.get("/api/v1/health/ready")
        stamp = e.app.state.readiness_cache[0]
        codes = [(await client.get("/api/v1/health/ready")).status_code for _ in range(3)]
    assert first.status_code == 503 and codes == [503, 503, 503]  # degraded without datastores
    assert e.app.state.readiness_cache[0] == stamp  # repeat calls reused one probe
    body = first.json()
    assert {d["detail"] for d in body["dependencies"]} == {"unavailable"}
    assert getattr(e.app.state, "readiness_cache", None) is not None  # probes share one check
