"""Rate-limit enforcement for the HTTP API (Story 6).

Keys are built only from server-established facts: the verified local user id, and the client
address resolved from the TCP peer (``X-Forwarded-For`` only behind configured trusted
proxies). Client-supplied identity or jurisdiction headers are never used, so an
unauthenticated caller cannot dodge a limit by changing who it claims to be.

Failure handling when the shared (Redis) state is unreachable:

* ``critical`` policies (authentication entry points, expensive operations) fail **closed**:
  503 with ``Retry-After``;
* everything else falls back to a strict process-local budget and logs
  ``rate_limiter_unavailable`` at error level so operators are alerted. It never fails open.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import cast

import structlog
from fastapi import Depends, Request

from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError, TooManyRequestsError
from app.core.ratelimit import (
    Decision,
    InMemoryRateLimiter,
    RateLimiter,
    RateLimiterUnavailable,
    Rule,
    resolve_client_ip,
)

logger = structlog.get_logger("api.ratelimit")

_UNAVAILABLE_RETRY_SECONDS = 5


def client_ip(request: Request) -> str:
    settings = cast(Settings, request.app.state.settings)
    peer = request.client.host if request.client else None
    return resolve_client_ip(
        peer, request.headers.get("x-forwarded-for"), settings.rate_limit.trusted_proxy_hops
    )


def _rules(settings: Settings, policy: str, key: str) -> list[Rule]:
    return [
        Rule(f"{policy}:{index}:{key}", spec.limit, spec.window_seconds)
        for index, spec in enumerate(settings.rate_limit.policy(policy))
    ]


def _fallback_rules(settings: Settings, rules: Sequence[Rule]) -> list[Rule]:
    budget = settings.rate_limit.fallback_per_minute
    return [
        Rule(r.key, max(1, min(r.limit, budget * r.window_seconds // 60)), r.window_seconds)
        for r in rules
    ]


def _limiters(request: Request) -> tuple[RateLimiter, InMemoryRateLimiter] | None:
    state = request.app.state
    if not state.settings.rate_limit.enabled or getattr(state, "rate_limiter", None) is None:
        return None
    return cast(RateLimiter, state.rate_limiter), cast(InMemoryRateLimiter, state.rate_fallback)


async def enforce(request: Request, policy: str, key: str, *, critical: bool = False) -> None:
    """Count one request against ``policy`` for ``key``; raise 429 (or 503) when not allowed."""
    pair = _limiters(request)
    if pair is None:
        return
    limiter, fallback = pair
    settings = cast(Settings, request.app.state.settings)
    rules = _rules(settings, policy, key)
    decision: Decision
    try:
        decision = await limiter.hit(rules)
    except RateLimiterUnavailable as exc:
        logger.error("rate_limiter_unavailable", policy=policy, critical=critical, cause=str(exc))
        if critical:
            raise ServiceUnavailableError(
                "Request throttling is temporarily unavailable.",
                code="rate_limit_unavailable",
                headers={"Retry-After": str(_UNAVAILABLE_RETRY_SECONDS)},
            ) from exc
        decision = await fallback.hit(_fallback_rules(settings, rules))
    if not decision.allowed:
        logger.info("rate_limited", policy=policy)
        raise TooManyRequestsError(decision.retry_after)


async def gate_source_ip(request: Request) -> None:
    """Before authentication: refuse blocked sources and apply the per-IP ceiling."""
    pair = _limiters(request)
    if pair is None:
        return
    limiter, fallback = pair
    ip = client_ip(request)
    try:
        remaining = await limiter.blocked_for(ip)
    except RateLimiterUnavailable as exc:
        logger.error("rate_limiter_unavailable", policy="block_check", cause=str(exc))
        remaining = await fallback.blocked_for(ip)
    if remaining > 0:
        logger.info("rate_limited", policy="auth_failure_block")
        raise TooManyRequestsError(remaining)
    await enforce(request, "api_ip", ip)


async def note_auth_failure(request: Request) -> None:
    """Count an authentication failure against the source IP (progressive throttling)."""
    pair = _limiters(request)
    if pair is None:
        return
    limiter, fallback = pair
    settings = cast(Settings, request.app.state.settings)
    cfg = settings.rate_limit
    spec = cfg.policy("auth_failure_ip")[0]
    kwargs = {
        "limit": spec.limit,
        "window_seconds": spec.window_seconds,
        "base_block": cfg.penalty_base_seconds,
        "max_block": cfg.penalty_max_seconds,
    }
    ip = client_ip(request)
    try:
        blocked = await limiter.record_failure(ip, **kwargs)
    except RateLimiterUnavailable as exc:
        logger.error("rate_limiter_unavailable", policy="auth_failure", cause=str(exc))
        blocked = await fallback.record_failure(ip, **kwargs)
    if blocked:
        logger.warning("auth_failure_block", seconds=blocked)


def limit_user(policy: str, *, critical: bool = False) -> Callable[..., Awaitable[None]]:
    """Dependency: count the request against ``policy`` for the authenticated local user."""
    from app.api.deps import get_current_principal  # local: deps imports this module

    async def dependency(
        request: Request, _principal: object = Depends(get_current_principal)
    ) -> None:
        user = getattr(request.state, "user", None)
        # Dev mode with authentication disabled has no user; key by IP instead.
        key = f"u:{user.id}" if user is not None else f"ip:{client_ip(request)}"
        await enforce(request, policy, key, critical=critical)

    return dependency


def limit_ip(policy: str, *, critical: bool = False) -> Callable[..., Awaitable[None]]:
    """Dependency: count the request against ``policy`` for the source IP."""

    async def dependency(request: Request) -> None:
        await enforce(request, policy, f"ip:{client_ip(request)}", critical=critical)

    return dependency
