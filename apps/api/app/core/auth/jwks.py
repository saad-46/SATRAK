"""Signing-key discovery and caching for a configured, trusted OIDC issuer.

Keys are only ever fetched from the configured ``jwks_url`` or from the ``jwks_uri``
published in the issuer's own discovery document (whose ``issuer`` must match exactly).
Nothing in a token (``jku``, ``x5u``, embedded ``jwk``) can steer where keys come from.

Rotation: an unknown ``kid`` triggers at most one network refresh per
``jwks_min_refresh_interval_seconds``; keys no longer published are dropped on refresh, so
retired keys stop validating. If the IdP is unreachable a cached key set keeps working for
at most ``jwks_max_stale_seconds``; with no usable cache the lookup fails closed.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
import structlog
from jwt import PyJWK

from app.core.config import AuthSettings

logger = structlog.get_logger("api.auth.jwks")

_MAX_RESPONSE_BYTES = 1_048_576
_ALLOWED_KEY_TYPES = frozenset({"RSA", "EC"})


class KeyNotFoundError(Exception):
    """The token names a ``kid`` the trusted issuer does not publish."""


class JwksUnavailableError(Exception):
    """Signing keys cannot be obtained and no usable cache exists (fail closed)."""


class JwksKeyProvider:
    def __init__(
        self,
        settings: AuthSettings,
        client: httpx.AsyncClient,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if settings.issuer is None:
            raise ValueError("an issuer is required to discover signing keys")
        self._settings = settings
        self._issuer: str = settings.issuer
        self._client = client
        self._clock = clock
        self._lock = asyncio.Lock()
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float | None = None
        self._last_attempt: float | None = None
        self._jwks_url: str | None = settings.jwks_url

    async def get_key(self, kid: str) -> PyJWK:
        now = self._clock()
        if self._is_fresh(now) and kid in self._keys:
            return self._keys[kid]

        async with self._lock:
            now = self._clock()
            if self._is_fresh(now) and kid in self._keys:
                return self._keys[kid]
            may_refresh = (
                self._last_attempt is None
                or now - self._last_attempt >= self._settings.jwks_min_refresh_interval_seconds
            )
            # Refresh when the cache is stale, empty, or does not know this kid (rotation).
            if may_refresh:
                await self._refresh(now)

        if kid in self._keys and self._usable(self._clock()):
            return self._keys[kid]
        if not self._usable(self._clock()):
            raise JwksUnavailableError("no usable signing-key set")
        raise KeyNotFoundError(kid)

    # -- internals ----------------------------------------------------------------------
    def _is_fresh(self, now: float) -> bool:
        return (
            self._fetched_at is not None
            and now - self._fetched_at < self._settings.jwks_cache_ttl_seconds
        )

    def _usable(self, now: float) -> bool:
        """Fresh, or stale but within the bounded stale-while-error window."""
        if self._fetched_at is None:
            return False
        age = now - self._fetched_at
        return age < self._settings.jwks_cache_ttl_seconds + self._settings.jwks_max_stale_seconds

    async def _refresh(self, now: float) -> None:
        self._last_attempt = now
        try:
            url = await self._resolve_jwks_url()
            document = await self._get_json(url)
            keys = self._parse_keys(document)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("jwks_refresh_failed", error=type(exc).__name__)
            return
        if not keys:
            logger.warning("jwks_refresh_empty")
            return
        self._keys = keys
        self._fetched_at = self._clock()

    async def _resolve_jwks_url(self) -> str:
        if self._jwks_url is not None:
            return self._jwks_url
        issuer = self._issuer
        document = await self._get_json(f"{issuer.rstrip('/')}/.well-known/openid-configuration")
        if document.get("issuer") != issuer:
            raise ValueError("discovery document issuer does not match the configured issuer")
        jwks_uri = document.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri.startswith("https://"):
            raise ValueError("discovery document has no https jwks_uri")
        self._jwks_url = jwks_uri
        return jwks_uri

    async def _get_json(self, url: str) -> dict[str, Any]:
        response = await self._client.get(
            url,
            timeout=self._settings.jwks_fetch_timeout_seconds,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise ValueError("response too large")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("response is not a JSON object")
        return data

    @staticmethod
    def _parse_keys(document: dict[str, Any]) -> dict[str, PyJWK]:
        raw = document.get("keys")
        if not isinstance(raw, list):
            raise ValueError("JWKS has no 'keys' array")
        keys: dict[str, PyJWK] = {}
        for jwk in raw:
            if not isinstance(jwk, dict):
                continue
            kid = jwk.get("kid")
            if not isinstance(kid, str) or not kid:
                continue
            if jwk.get("kty") not in _ALLOWED_KEY_TYPES or jwk.get("use") not in (None, "sig"):
                continue
            try:
                keys[kid] = PyJWK(jwk)
            except (jwt.PyJWTError, ValueError, TypeError):
                logger.warning("jwks_key_skipped", kid=kid)
        return keys
