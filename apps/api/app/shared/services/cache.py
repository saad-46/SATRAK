"""Cache service abstraction."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Cache(Protocol):
    """Key/value cache port. A Redis-backed adapter implements this later."""

    async def get(self, key: str) -> object | None: ...

    async def set(self, key: str, value: object, *, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    async def clear(self) -> None: ...


class InMemoryCache:
    """Process-local cache with no eviction. For tests/dev; not for production."""

    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    async def get(self, key: str) -> object | None:
        return self._store.get(key)

    async def set(self, key: str, value: object, *, ttl_seconds: int | None = None) -> None:
        # TTL is accepted for interface parity but not enforced in-memory.
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def clear(self) -> None:
        self._store.clear()
