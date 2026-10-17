"""Deterministic pixel encoding (Epic 3 Stories 14-15).

``ImageEncoder`` is the rendering seam: tiles and thumbnails hand pixel buffers to an
encoder and store whatever comes back. ``RawFloat32Encoder`` is the working analysis-tier
implementation — packed little-endian float32, band-sequential, byte-identical across
platforms — matching the COG/range-read consumption model (ADR-0006). Visual encoders
(PNG/WEBP) are adapters behind this same Protocol when an imaging dependency is
introduced; no imaging library exists here.
"""

from __future__ import annotations

import hashlib
import sys
from array import array
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.shared.domain.errors import ValueValidationError


@dataclass(frozen=True)
class EncodedImage:
    """An encoded pixel payload ready for storage."""

    data: bytes
    content_type: str
    extension: str

    @property
    def checksum_sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def size_bytes(self) -> int:
        return len(self.data)


@runtime_checkable
class ImageEncoder(Protocol):
    """Encodes band-sequential float buffers into a stored image format."""

    def encode(
        self, *, width: int, height: int, bands: tuple[array[float], ...]
    ) -> EncodedImage: ...


def pack_float32_le(bands: tuple[array[float], ...]) -> bytes:
    """Band-sequential float32 little-endian bytes — identical on any platform."""
    chunks: list[bytes] = []
    for band in bands:
        if sys.byteorder == "big":  # pragma: no cover - LE on all target platforms
            swapped = array("f", band)
            swapped.byteswap()
            chunks.append(swapped.tobytes())
        else:
            chunks.append(band.tobytes())
    return b"".join(chunks)


class RawFloat32Encoder:
    """Analysis-tier raw encoder: lossless, deterministic, dependency-free."""

    content_type = "application/octet-stream"
    extension = "bin"

    def encode(self, *, width: int, height: int, bands: tuple[array[float], ...]) -> EncodedImage:
        if width < 1 or height < 1:
            raise ValueValidationError("image dimensions must be >= 1x1", field="size")
        if not bands:
            raise ValueValidationError("at least one band is required", field="bands")
        expected = width * height
        for index, band in enumerate(bands):
            if len(band) != expected:
                raise ValueValidationError(
                    f"band {index} holds {len(band)} pixels, image needs {expected}",
                    field="bands",
                )
        return EncodedImage(
            data=pack_float32_le(bands),
            content_type=self.content_type,
            extension=self.extension,
        )
