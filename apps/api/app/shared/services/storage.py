"""Object storage abstraction.

Defines the storage *port* the platform depends on, decoupled from any provider
(S3/MinIO/Azure Blob/GCS). Concrete adapters implement :class:`StorageProvider`;
:class:`InMemoryStorageProvider` backs tests. The provider deals in opaque bytes +
metadata and returns a :class:`~app.shared.value_objects.file_reference.FileReference`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.shared.value_objects.file_reference import FileCategory, FileReference


@dataclass(frozen=True)
class StoredObject:
    """Result of a storage read: the bytes plus resolved metadata."""

    data: bytes
    content_type: str
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class StorageProvider(Protocol):
    """Blob storage port."""

    async def save(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        filename: str,
        category: FileCategory = FileCategory.OTHER,
        metadata: dict[str, str] | None = None,
    ) -> FileReference: ...

    async def open(self, key: str) -> StoredObject: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    async def url(self, key: str, *, expires_seconds: int = 3600) -> str: ...


class InMemoryStorageProvider:
    """Dict-backed storage for tests. Computes checksums like a real provider."""

    def __init__(self) -> None:
        self._objects: dict[str, StoredObject] = {}

    async def save(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        filename: str,
        category: FileCategory = FileCategory.OTHER,
        metadata: dict[str, str] | None = None,
    ) -> FileReference:
        import hashlib

        self._objects[key] = StoredObject(
            data=data, content_type=content_type, metadata=metadata or {}
        )
        return FileReference(
            storage_key=key,
            content_type=content_type,
            size_bytes=len(data),
            filename=filename,
            category=category,
            checksum_sha256=hashlib.sha256(data).hexdigest(),
        )

    async def open(self, key: str) -> StoredObject:
        if key not in self._objects:
            raise KeyError(key)
        return self._objects[key]

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self._objects

    async def url(self, key: str, *, expires_seconds: int = 3600) -> str:
        return f"memory://{key}"
