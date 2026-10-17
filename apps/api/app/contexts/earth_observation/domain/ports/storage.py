"""Storage port for imagery assets.

The Earth Observation context **reuses the shared-kernel** ``StorageProvider`` port rather
than defining a parallel abstraction (DRY; spec Appendix B). The infrastructure layer adds
only the content-addressed key scheme + tier policy (Story 9) on top of a concrete
S3/MinIO adapter. This alias gives the port an EO-local, intention-revealing name.
"""

from __future__ import annotations

from app.shared.services.storage import StorageProvider as ImageStoragePort

__all__ = ["ImageStoragePort"]
