"""Provider authentication abstraction (spec §5.3).

Providers never see credential storage: an :class:`AuthStrategy` yields the headers a
transport must attach. Credential *values* are injected from configuration/secrets at
wiring time — never hard-coded (Blueprint Part 6). OAuth client-credentials (token fetch +
refresh) requires an HTTP transport and lands with the download story behind this same
Protocol.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from app.contexts.earth_observation.infrastructure.providers.errors import (
    ProviderConfigurationError,
)


@runtime_checkable
class AuthStrategy(Protocol):
    """Yields the authentication headers for a provider request."""

    async def headers(self) -> Mapping[str, str]: ...


class NoAuth:
    """Open-access endpoints (e.g. public STAC catalogues)."""

    async def headers(self) -> Mapping[str, str]:
        return {}


class ApiKeyAuth:
    """A static API key sent in a configurable header."""

    def __init__(self, *, header_name: str, api_key: str) -> None:
        if not header_name.strip():
            raise ProviderConfigurationError("header_name is required")
        if not api_key.strip():
            raise ProviderConfigurationError("api_key is required")
        self._header_name = header_name
        self._api_key = api_key

    async def headers(self) -> Mapping[str, str]:
        return {self._header_name: self._api_key}


class StaticBearerAuth:
    """A pre-issued bearer token (e.g. injected by the deployment platform)."""

    def __init__(self, *, token: str) -> None:
        if not token.strip():
            raise ProviderConfigurationError("token is required")
        self._token = token

    async def headers(self) -> Mapping[str, str]:
        return {"Authorization": f"Bearer {self._token}"}
