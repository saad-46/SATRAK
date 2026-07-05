"""Comment aggregate — free-text remark attached to any subject entity."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain.entity import AggregateRoot
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.events import CommentAdded
from app.shared.domain.identifiers import EntityId


@dataclass(kw_only=True, eq=False)
class Comment(AggregateRoot):
    subject_type: str
    subject_id: EntityId
    author_id: EntityId
    body: str

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.body.strip():
            raise InvariantViolation("comment body is required")

    @classmethod
    def create(
        cls,
        *,
        subject_type: str,
        subject_id: EntityId,
        author_id: EntityId,
        body: str,
    ) -> Comment:
        comment = cls(
            subject_type=subject_type,
            subject_id=subject_id,
            author_id=author_id,
            body=body,
            created_by=author_id,
            updated_by=author_id,
        )
        comment.record_event(
            CommentAdded(
                comment_id=comment.id,
                subject_type=subject_type,
                subject_id=subject_id,
                author_id=author_id,
            )
        )
        return comment
