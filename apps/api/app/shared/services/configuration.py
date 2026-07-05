"""Configuration & feature-flag abstraction.

A read port over runtime configuration and feature flags, decoupled from the
source (env, database, remote config service). :class:`DictConfigurationProvider`
backs tests/local; a database- or remote-backed provider implements the same
interface later, enabling per-jurisdiction feature rollout.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ConfigurationProvider(Protocol):
    def get(self, key: str, default: str | None = None) -> str | None: ...

    def get_bool(self, key: str, default: bool = False) -> bool: ...

    def is_feature_enabled(self, flag: str) -> bool: ...


class DictConfigurationProvider:
    """In-memory configuration backed by two dicts (settings + feature flags)."""

    _TRUE = frozenset({"1", "true", "yes", "on"})

    def __init__(
        self,
        settings: dict[str, str] | None = None,
        feature_flags: dict[str, bool] | None = None,
    ) -> None:
        self._settings = settings or {}
        self._flags = feature_flags or {}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._settings.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self._settings.get(key)
        return raw.lower() in self._TRUE if raw is not None else default

    def is_feature_enabled(self, flag: str) -> bool:
        return self._flags.get(flag, False)
