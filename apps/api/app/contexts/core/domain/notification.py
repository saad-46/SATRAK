"""Notification aggregate — a message queued for a recipient."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.shared.domain.entity import AggregateRoot
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.events import NotificationCreated
from app.shared.domain.identifiers import EntityId
from app.shared.services.notification import NotificationChannel


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    READ = "read"
    FAILED = "failed"


@dataclass(kw_only=True, eq=False)
class Notification(AggregateRoot):
    recipient_id: EntityId
    channel: NotificationChannel
    subject: str
    body: str
    status: NotificationStatus = NotificationStatus.PENDING

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.subject.strip():
            raise InvariantViolation("notification subject is required")

    @classmethod
    def create(
        cls,
        *,
        recipient_id: EntityId,
        channel: NotificationChannel,
        subject: str,
        body: str,
    ) -> Notification:
        notification = cls(recipient_id=recipient_id, channel=channel, subject=subject, body=body)
        notification.record_event(
            NotificationCreated(
                notification_id=notification.id,
                recipient_id=recipient_id,
                channel=str(channel),
            )
        )
        return notification

    def mark_sent(self, *, actor: EntityId | None = None) -> None:
        self.status = NotificationStatus.SENT
        self.touch(actor=actor)

    def mark_read(self, *, actor: EntityId | None = None) -> None:
        self.status = NotificationStatus.READ
        self.touch(actor=actor)

    def mark_failed(self, *, actor: EntityId | None = None) -> None:
        self.status = NotificationStatus.FAILED
        self.touch(actor=actor)
