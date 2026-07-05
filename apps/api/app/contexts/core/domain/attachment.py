"""File attachment and document aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain.entity import AggregateRoot, Entity
from app.shared.domain.enums import EntityStatus
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.events import EntityCreated, FileUploaded
from app.shared.domain.identifiers import EntityId
from app.shared.value_objects.file_reference import FileCategory, FileReference


@dataclass(kw_only=True, eq=False)
class FileAttachment(Entity):
    """A file attached to some subject entity (lightweight, no versioning)."""

    subject_type: str
    subject_id: EntityId
    file: FileReference

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.subject_type.strip():
            raise InvariantViolation("attachment subject_type is required")


@dataclass(kw_only=True, eq=False)
class Document(AggregateRoot):
    """A first-class, versioned document (contracts, reports, evidence bundles)."""

    title: str
    file: FileReference
    category: FileCategory = FileCategory.OTHER
    status: EntityStatus = EntityStatus.ACTIVE
    revision: int = 1

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.title.strip():
            raise InvariantViolation("document title is required")
        if self.revision < 1:
            raise InvariantViolation("document revision must be >= 1")

    @classmethod
    def create(
        cls,
        *,
        title: str,
        file: FileReference,
        category: FileCategory,
        actor: EntityId | None = None,
    ) -> Document:
        doc = cls(title=title, file=file, category=category, created_by=actor, updated_by=actor)
        doc.record_event(EntityCreated(aggregate_id=doc.id, aggregate_type=cls.__name__))
        doc.record_event(
            FileUploaded(
                file_id=doc.id,
                storage_key=file.storage_key,
                content_type=file.content_type,
                size_bytes=file.size_bytes,
            )
        )
        return doc

    def add_revision(self, new_file: FileReference, *, actor: EntityId | None = None) -> None:
        self.file = new_file
        self.revision += 1
        self.touch(actor=actor)
