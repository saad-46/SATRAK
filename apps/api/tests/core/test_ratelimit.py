"""Rate limiter semantics, identical on the in-memory twin and on a real Redis (A12).

Redis-backed cases need ``SATRAK_TEST_REDIS_URL`` (a disposable instance); they are skipped
otherwise. Real time is used for Redis, so windows are one second.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.core.ratelimit import (
    InMemoryRateLimiter,
    RateLimiter,
    RateLimiterUnavailable,
    RedisRateLimiter,
    Rule,
    resolve_client_ip,
)

REDIS_URL = os.environ.get("SATRAK_TEST_REDIS_URL")


class Harness:
    """A limiter plus the means to move time forward for it."""

    def __init__(self, limiter: RateLimiter, advance: object, make_peer: object) -> None:
        self.limiter = limiter
        self.advance = advance  # async callable(seconds)
        self.make_peer = make_peer  # () -> second limiter sharing the same state


@pytest_asyncio.fixture(params=["memory", "redis"])
async def h(request: pytest.FixtureRequest) -> AsyncIterator[Harness]:
    if request.param == "memory":
        now = [1000.0]
        limiter = InMemoryRateLimiter(clock=lambda: now[0])

        async def advance(seconds: float) -> None:
            now[0] += seconds

        yield Harness(limiter, advance, lambda: limiter)
        return
    if REDIS_URL is None:
        pytest.skip("SATRAK_TEST_REDIS_URL is not set")
    client = Redis.from_url(REDIS_URL)
    await client.flushdb()

    async def real_sleep(seconds: float) -> None:
        await asyncio.sleep(seconds)

    yield Harness(
        RedisRateLimiter(client), real_sleep, lambda: RedisRateLimiter(Redis.from_url(REDIS_URL))
    )
    await client.flushdb()
    await client.aclose()


def _key() -> str:
    return f"t:{uuid.uuid4().hex}"


async def test_allows_up_to_the_limit_then_denies_with_retry_after(h: Harness) -> None:
    rule = Rule(_key(), 3, 1)
    decisions = [await h.limiter.hit([rule]) for _ in range(4)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert [d.remaining for d in decisions[:3]] == [2, 1, 0]
    assert decisions[3].retry_after >= 1


async def test_window_slides_so_capacity_returns(h: Harness) -> None:
    rule = Rule(_key(), 2, 1)
    assert (await h.limiter.hit([rule])).allowed and (await h.limiter.hit([rule])).allowed
    assert not (await h.limiter.hit([rule])).allowed
    await h.advance(1.2)  # type: ignore[operator]
    assert (await h.limiter.hit([rule])).allowed


async def test_keys_are_independent(h: Harness) -> None:
    a, b = Rule(_key(), 1, 60), Rule(_key(), 1, 60)
    assert (await h.limiter.hit([a])).allowed
    assert not (await h.limiter.hit([a])).allowed
    assert (await h.limiter.hit([b])).allowed


async def test_a_denied_request_consumes_no_budget_from_other_rules(h: Harness) -> None:
    per_minute, per_hour = Rule(_key(), 5, 60), Rule(_key(), 2, 3600)
    assert (await h.limiter.hit([per_minute, per_hour])).allowed
    assert (await h.limiter.hit([per_minute, per_hour])).allowed
    for _ in range(10):  # the hourly rule denies; the minute rule must not be charged for them
        decision = await h.limiter.hit([per_minute, per_hour])
        assert not decision.allowed
        assert decision.retry_after > 60  # the binding constraint is the hourly rule
    only_minute = await h.limiter.hit([per_minute])
    assert only_minute.allowed and only_minute.remaining == 2  # 2 of 5 used, not 12


async def test_concurrent_requests_never_exceed_the_limit(h: Harness) -> None:
    rule = Rule(_key(), 10, 60)
    results = await asyncio.gather(*(h.limiter.hit([rule]) for _ in range(60)))
    assert sum(r.allowed for r in results) == 10


async def test_the_limit_is_shared_across_instances(h: Harness) -> None:
    if isinstance(h.limiter, InMemoryRateLimiter):
        pytest.skip("process-local state is shared by construction")
    second = h.make_peer()  # type: ignore[operator]
    rule = Rule(_key(), 10, 60)
    results = await asyncio.gather(
        *(limiter.hit([rule]) for limiter in (h.limiter, second) for _ in range(20))
    )
    assert sum(r.allowed for r in results) == 10


async def test_failures_block_progressively_and_blocks_expire(h: Harness) -> None:
    key = _key()
    kwargs = {"limit": 3, "window_seconds": 60, "base_block": 2, "max_block": 8}
    assert [await h.limiter.record_failure(key, **kwargs) for _ in range(3)] == [0, 0, 0]
    assert await h.limiter.blocked_for(key) == 0

    first = await h.limiter.record_failure(key, **kwargs)  # 4th failure: over budget
    assert first == 2 and 0 < await h.limiter.blocked_for(key) <= 2

    await h.advance(2.2)  # type: ignore[operator]
    assert await h.limiter.blocked_for(key) == 0
    for _ in range(3):
        await h.limiter.record_failure(key, **kwargs)
    second = await h.limiter.record_failure(key, **kwargs)  # second strike doubles the block
    assert second == 4
    await h.advance(4.2)  # type: ignore[operator]
    for _ in range(3):
        await h.limiter.record_failure(key, **kwargs)
    third = await h.limiter.record_failure(key, **kwargs)
    assert third == 8
    await h.advance(8.2)  # type: ignore[operator]
    for _ in range(3):
        await h.limiter.record_failure(key, **kwargs)
    assert await h.limiter.record_failure(key, **kwargs) == 8  # capped


async def test_blocks_are_per_key(h: Harness) -> None:
    noisy, quiet = _key(), _key()
    kwargs = {"limit": 1, "window_seconds": 60, "base_block": 30, "max_block": 60}
    await h.limiter.record_failure(noisy, **kwargs)
    await h.limiter.record_failure(noisy, **kwargs)
    assert await h.limiter.blocked_for(noisy) > 0
    assert await h.limiter.blocked_for(quiet) == 0


@pytest.mark.skipif(REDIS_URL is None, reason="SATRAK_TEST_REDIS_URL is not set")
async def test_unreachable_redis_raises_instead_of_allowing() -> None:
    client = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    limiter = RedisRateLimiter(client)
    with pytest.raises(RateLimiterUnavailable):
        await limiter.hit([Rule("x", 1, 1)])
    with pytest.raises(RateLimiterUnavailable):
        await limiter.blocked_for("x")
    with pytest.raises(RateLimiterUnavailable):
        await limiter.record_failure("x", limit=1, window_seconds=1, base_block=1, max_block=1)
    await client.aclose()


@pytest.mark.parametrize(
    ("peer", "xff", "hops", "expected"),
    [
        ("10.0.0.9", "1.2.3.4", 0, "10.0.0.9"),  # header ignored without trusted proxies
        ("10.0.0.9", None, 1, "10.0.0.9"),
        ("10.0.0.9", "1.2.3.4", 1, "1.2.3.4"),
        ("10.0.0.9", "6.6.6.6, 1.2.3.4", 1, "1.2.3.4"),  # client-forged left entry ignored
        ("10.0.0.9", "6.6.6.6, 1.2.3.4, 10.1.1.1", 2, "1.2.3.4"),
        ("10.0.0.9", "1.2.3.4", 2, "10.0.0.9"),  # fewer entries than trusted hops: distrust
        ("10.0.0.9", "not-an-ip", 1, "10.0.0.9"),
        ("10.0.0.9", "2001:db8::1", 1, "2001:db8::/64"),
        (None, None, 0, "unknown"),
    ],
)
def test_client_ip_resolution(peer: str | None, xff: str | None, hops: int, expected: str) -> None:
    assert resolve_client_ip(peer, xff, hops) == expected


def test_ipv6_clients_are_keyed_by_subscriber_prefix() -> None:
    a = resolve_client_ip("2001:db8:1:2:aaaa::1", None, 0)
    b = resolve_client_ip("2001:db8:1:2:bbbb::9", None, 0)
    assert a == b == "2001:db8:1:2::/64"
    assert resolve_client_ip("::ffff:203.0.113.5", None, 0) == "203.0.113.5"
    assert resolve_client_ip("203.0.113.5", "2001:db8:1:2:1::1", 1) == "2001:db8:1:2::/64"
