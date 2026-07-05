"""File service abstraction (higher-level document operations).

Sits above :class:`~app.shared.services.storage.StorageProvider` and adds
domain-meaningful operations: categorized upload, thumbnail generation, and
versioned document handling for SATRAK's data types (imagery, PDFs, GeoJSON,
shapefiles, GeoTIFF, drone recordings, reports). Interface only in Epic 2.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.shared.value_objects.file_reference import FileCategory, FileReference


@runtime_checkable
class FileService(Protocol):
    async def upload(
        self,
        data: bytes,
        *,
        filename: str,
        content_type: str,
        category: FileCategory,
        owner_id: object | None = None,
    ) -> FileReference: ...

    async def download(self, reference: FileReference) -> bytes: ...

    async def generate_thumbnail(self, reference: FileReference) -> FileReference | None: ...

    async def create_version(self, reference: FileReference, data: bytes) -> FileReference: ...

    async def delete(self, reference: FileReference) -> None: ...
