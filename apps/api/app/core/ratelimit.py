"""Distributed sliding-window rate limiting (Redis), with an in-memory twin for tests/dev.

Design (Story 6):

* **Exact sliding window, atomic across instances.** Each rule is a sorted set of request
  timestamps; one Lua script evaluates *all* rules of a policy and records the request only if
  every rule passes, so concurrent requests on any number of API instances can never exceed a
  limit. Time comes from the Redis server clock, never from API hosts.
* **Progressive throttling** for authentication failures: exceeding the failure budget blocks
  the source for ``base * 2^(strikes-1)`` seconds (capped); strikes decay after a quiet period.
* **Failure handling is the caller's decision** (see ``app.api.ratelimit``): this module raises
  :class:`RateLimiterUnavailable` and never silently allows.
* Single Redis primary assumed (keys of one policy touch several keys in one script, which
  Redis Cluster would reject unless hash-tagged).
"""

from __future__ import annotations

import ipaddress
import math
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

KEY_PREFIX = "rl:"


@dataclass(frozen=True, slots=True)
class Rule:
    key: str
    limit: int
    window_seconds: int


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    retry_after: int = 0
    remaining: int = 0


class RateLimiterUnavailable(Exception):
    """The shared limiter state could not be consulted."""


class RateLimiter(Protocol):
    async def hit(self, rules: Sequence[Rule]) -> Decision:
        """Count one request against every rule atomically; if any rule fails, count nothing."""
        ...

    async def blocked_for(self, key: str) -> int:
        """Seconds the key remains blocked by progressive throttling (0 = not blocked)."""
        ...

    async def record_failure(
        self, key: str, *, limit: int, window_seconds: int, base_block: int, max_block: int
    ) -> int:
        """Count a failure; when over ``limit`` block the key. Returns seconds blocked now."""
        ...


# --- Redis -----------------------------------------------------------------------------------
_HIT_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local member = ARGV[1]
local retry = 0
local remaining = -1
for i = 1, #KEYS do
  local limit = tonumber(ARGV[2 * i])
  local window = tonumber(ARGV[2 * i + 1])
  redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now - window)
  local count = redis.call('ZCARD', KEYS[i])
  if count >= limit then
    local oldest = redis.call('ZRANGE', KEYS[i], 0, 0, 'WITHSCORES')
    local wait = tonumber(oldest[2]) + window - now
    if wait > retry then retry = wait end
  else
    local rem = limit - count - 1
    if remaining < 0 or rem < remaining then remaining = rem end
  end
end
if retry > 0 then return {0, retry, 0} end
for i = 1, #KEYS do
  local window = tonumber(ARGV[2 * i + 1])
  redis.call('ZADD', KEYS[i], now, member)
  redis.call('PEXPIRE', KEYS[i], window)
end
return {1, 0, remaining}
"""

_FAILURE_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local limit, window = tonumber(ARGV[2]), tonumber(ARGV[3])
local base, cap = tonumber(ARGV[4]), tonumber(ARGV[5])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
redis.call('ZADD', KEYS[1], now, ARGV[1])
redis.call('PEXPIRE', KEYS[1], window)
if redis.call('ZCARD', KEYS[1]) <= limit then return 0 end
local strikes = redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], cap * 2)
local block = base * (2 ^ math.min(strikes - 1, 30))
if block > cap then block = cap end
redis.call('SET', KEYS[3], 1, 'EX', math.floor(block))
redis.call('DEL', KEYS[1])
return math.floor(block)
"""


class RedisRateLimiter:
    def __init__(self, client: Redis) -> None:
        self._client = client
        self._hit = client.register_script(_HIT_LUA)
        self._failure = client.register_script(_FAILURE_LUA)

    async def _run(self, call: Awaitable[Any]) -> Any:
        try:
            return await call
        except (RedisError, OSError, TimeoutError) as exc:
            raise RateLimiterUnavailable(type(exc).__name__) from exc

    async def hit(self, rules: Sequence[Rule]) -> Decision:
        if not rules:
            return Decision(True)
        keys = [f"{KEY_PREFIX}w:{r.key}" for r in rules]
        args: list[str | int] = [uuid.uuid4().hex]
        for r in rules:
            args += [r.limit, r.window_seconds * 1000]
        allowed, retry_ms, remaining = await self._run(self._hit(keys=keys, args=args))
        if allowed:
            return Decision(True, 0, int(remaining))
        return Decision(False, max(1, math.ceil(int(retry_ms) / 1000)), 0)

    async def blocked_for(self, key: str) -> int:
        ttl_ms = int(await self._run(self._client.pttl(f"{KEY_PREFIX}b:{key}")))
        return math.ceil(ttl_ms / 1000) if ttl_ms > 0 else 0

    async def record_failure(
        self, key: str, *, limit: int, window_seconds: int, base_block: int, max_block: int
    ) -> int:
        keys = [f"{KEY_PREFIX}f:{key}", f"{KEY_PREFIX}s:{key}", f"{KEY_PREFIX}b:{key}"]
        args: list[str | int] = [
            uuid.uuid4().hex,
            limit,
            window_seconds * 1000,
            base_block,
            max_block,
        ]
        return int(await self._run(self._failure(keys=keys, args=args)))


# --- In-memory twin ----------------------------------------------------------------------------
class InMemoryRateLimiter:
    """Same semantics, one process. Used when Redis is not configured (development/tests) and
    as the strict per-process fallback while Redis is down."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._windows: dict[str, list[float]] = {}
        self._strikes: dict[str, tuple[int, float]] = {}
        self._blocks: dict[str, float] = {}

    def _live(self, key: str, window: float, now: float) -> list[float]:
        stamps = [t for t in self._windows.get(key, []) if t > now - window]
        self._windows[key] = stamps
        return stamps

    async def hit(self, rules: Sequence[Rule]) -> Decision:
        now = self._clock()
        retry = 0.0
        remaining = -1
        live = []
        for rule in rules:
            stamps = self._live(rule.key, rule.window_seconds, now)
            live.append(stamps)
            if len(stamps) >= rule.limit:
                retry = max(retry, stamps[0] + rule.window_seconds - now)
            else:
                rem = rule.limit - len(stamps) - 1
                remaining = rem if remaining < 0 else min(remaining, rem)
        if retry > 0:
            return Decision(False, max(1, math.ceil(retry)), 0)
        for stamps in live:
            stamps.append(now)
        return Decision(True, 0, max(0, remaining))

    async def blocked_for(self, key: str) -> int:
        until = self._blocks.get(key, 0.0)
        left = until - self._clock()
        return math.ceil(left) if left > 0 else 0

    async def record_failure(
        self, key: str, *, limit: int, window_seconds: int, base_block: int, max_block: int
    ) -> int:
        now = self._clock()
        stamps = self._live(f"f:{key}", window_seconds, now)
        stamps.append(now)
        if len(stamps) <= limit:
            return 0
        strikes, expires = self._strikes.get(key, (0, 0.0))
        strikes = strikes + 1 if expires > now else 1
        self._strikes[key] = (strikes, now + max_block * 2)
        block = min(base_block * 2 ** min(strikes - 1, 30), max_block)
        self._blocks[key] = now + block
        self._windows.pop(f"f:{key}", None)
        return int(block)


# --- Client address ----------------------------------------------------------------------------
def _normalise(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """IPv6 clients are keyed by /64 (one subscriber), so rotating host bits cannot evade limits."""
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network((address, 64), strict=False))
    return str(address)


def _peer_is_trusted(
    peer: str | None, networks: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network]
) -> bool:
    if not peer:
        return False
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in networks if network.version == address.version)


def _normalise_text(value: str) -> str:
    try:
        return _normalise(ipaddress.ip_address(value))
    except ValueError:
        return value


def resolve_client_ip(
    peer: str | None,
    forwarded_for: str | None,
    trusted_hops: int,
    trusted_networks: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network] = (),
) -> str:
    """The caller's address. ``X-Forwarded-For`` is honoured only behind ``trusted_hops``
    reverse proxies, only when the TCP peer is one of ``trusted_networks`` (if any are
    configured), and then only the entry those proxies appended (counted from the right):
    anything a client put further left, or sent by connecting directly, is ignored."""
    fallback = _normalise_text(peer) if peer else "unknown"
    if trusted_hops <= 0 or not forwarded_for:
        return fallback
    if trusted_networks and not _peer_is_trusted(peer, trusted_networks):
        return fallback
    parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
    if len(parts) < trusted_hops:
        return fallback
    try:
        return _normalise(ipaddress.ip_address(parts[-trusted_hops]))
    except ValueError:
        return fallback
