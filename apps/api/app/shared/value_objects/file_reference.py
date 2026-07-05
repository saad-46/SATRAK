"""File reference value object — a pointer to a stored object, not its bytes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject


class FileCategory(StrEnum):
    """High-level classification of a stored file, spanning SATRAK's data types."""

    IMAGE = "image"
    PDF = "pdf"
    GEOJSON = "geojson"
    SHAPEFILE = "shapefile"
    GEOTIFF = "geotiff"
    VIDEO = "video"
    DRONE_RECORDING = "drone_recording"
    REPORT = "report"
    THUMBNAIL = "thumbnail"
    OTHER = "other"


@dataclass(frozen=True)
class FileReference(ValueObject):
    """An immutable pointer to a file in a storage provider.

    Holds addressing + metadata (never the content). The storage abstraction
    (:mod:`app.shared.services.storage`) resolves a reference to a stream/URL.
    """

    storage_key: str
    content_type: str
    size_bytes: int
    filename: str
    category: FileCategory = FileCategory.OTHER
    checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.storage_key.strip():
            raise ValueValidationError("storage_key is required", field="storage_key")
        if not self.filename.strip():
            raise ValueValidationError("filename is required", field="filename")
        if not self.content_type.strip():
            raise ValueValidationError("content_type is required", field="content_type")
        if self.size_bytes < 0:
            raise ValueValidationError("size_bytes must be >= 0", field="size_bytes")
        if self.checksum_sha256 is not None and len(self.checksum_sha256) != 64:
            raise ValueValidationError(
                "checksum_sha256 must be a 64-char hex digest", field="checksum_sha256"
            )
