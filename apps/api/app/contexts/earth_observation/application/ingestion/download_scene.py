"""Streamed scene download (Epic 3 Story 10).

Pulls a scene's bytes through the provider's download contract, hashing incrementally
while streaming, then stores the raw asset under its content-addressed key
(``StorageKeyStrategy``) and advances the aggregate to ``DOWNLOADED``. The SHA-256 is
computed in one pass over the stream; chunks are joined exactly once because the shared
``StorageProvider.save`` contract takes complete payloads (multipart streaming arrives
with the concrete S3 adapter behind the same port).

An empty stream is rejected immediately: the scene transitions to ``REJECTED`` (emitting
``ImageRejected``) and the failure is raised for the job layer to observe.
"""

from __future__ import annotations

import hashlib

from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.ports.imagery_provider import (
    EarthObservationProvider,
)
from app.contexts.earth_observation.domain.ports.repositories import SceneRepository
from app.contexts.earth_observation.infrastructure.storage.keying import StorageKeyStrategy
from app.shared.domain.errors import BusinessRuleViolation
from app.shared.domain.identifiers import EntityId
from app.shared.domain.scope import AccessScope
from app.shared.persistence.scoped import ScopedRepository
from app.shared.persistence.unit_of_work import UnitOfWork
from app.shared.services.storage import StorageProvider
from app.shared.value_objects.file_reference import FileReference


class EmptyDownloadError(BusinessRuleViolation):
    """The provider stream yielded no bytes for a scene."""

    code = "empty_download"


class SceneDownloadService:
    """Downloads one scene's raw bytes into the content-addressed raw tier."""

    def __init__(
        self,
        *,
        provider: EarthObservationProvider,
        scenes: SceneRepository,
        storage: StorageProvider,
        keys: StorageKeyStrategy,
        uow: UnitOfWork,
        raw_extension: str = "zip",
        content_type: str = "application/octet-stream",
    ) -> None:
        self._provider = provider
        self._scenes = scenes
        self._storage = storage
        self._keys = keys
        self._uow = uow
        self._raw_extension = raw_extension
        self._content_type = content_type

    async def download(self, *, scene_id: EntityId, scope: AccessScope) -> FileReference:
        scenes = ScopedRepository(self._scenes, scope)
        scene = await scenes.require(scene_id)

        hasher = hashlib.sha256()
        chunks: list[bytes] = []
        async for chunk in self._provider.fetch(scene.provider_scene_id):
            if chunk:
                hasher.update(chunk)
                chunks.append(chunk)

        if not chunks:
            await self._reject(scenes, scene, reason="provider returned an empty download stream")
            raise EmptyDownloadError(f"empty download for scene {scene.provider_scene_id}")

        checksum = hasher.hexdigest()
        key = self._keys.raw_key(
            provider_scene_id=scene.provider_scene_id,
            sensor_type=scene.acquisition.sensor_type,
            acquired_at=scene.acquisition.acquired_at,
            checksum_sha256=checksum,
            extension=self._raw_extension,
        )
        reference = await self._storage.save(
            key,
            b"".join(chunks),
            content_type=self._content_type,
            filename=f"{scene.provider_scene_id.native_id}.{self._raw_extension}",
        )

        scene.mark_downloaded(checksum_sha256=checksum)
        await scenes.update(scene)
        self._uow.track(scene)
        await self._uow.commit()
        return reference

    async def _reject(self, scenes: ScopedRepository[Scene], scene: Scene, *, reason: str) -> None:
        scene.reject(reason=reason)
        await scenes.update(scene)
        self._uow.track(scene)
        await self._uow.commit()
