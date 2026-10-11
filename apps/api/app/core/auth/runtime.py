"""Wires settings, HTTP client, key provider and verifier into one per-app object."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.auth.jwks import JwksKeyProvider
from app.core.auth.verifier import KeyProvider, TokenVerifier
from app.core.config import AuthSettings


@dataclass
class AuthRuntime:
    verifier: TokenVerifier
    _client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def build_auth_runtime(
    settings: AuthSettings,
    *,
    client: httpx.AsyncClient | None = None,
    keys: KeyProvider | None = None,
) -> AuthRuntime | None:
    """Return the runtime, or ``None`` when authentication is explicitly disabled.

    ``client``/``keys`` let tests substitute a transport or key provider; production
    uses an ``httpx`` client that never follows redirects.
    """
    if not settings.enabled:
        return None
    http = client if client is not None else httpx.AsyncClient(follow_redirects=False)
    provider: KeyProvider = keys if keys is not None else JwksKeyProvider(settings, http)
    # Only close a client this function created.
    return AuthRuntime(
        verifier=TokenVerifier(settings, provider),
        _client=http if client is None else None,
    )
