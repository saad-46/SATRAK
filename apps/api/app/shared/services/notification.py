"""Notification sender abstraction (transport port).

Defines how a rendered notification leaves the system. The Notification bounded
context owns *what* and *when*; this port owns *delivery* over a channel
(SMS/email/push). Concrete gateways are wired in the notification epic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class NotificationChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    IN_APP = "in_app"


@dataclass(frozen=True)
class NotificationMessage:
    channel: NotificationChannel
    recipient: str
    subject: str
    body: str
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class NotificationSender(Protocol):
    async def send(self, message: NotificationMessage) -> None: ...


class NullNotificationSender:
    """Discards messages (safe default for local/dev)."""

    async def send(self, message: NotificationMessage) -> None:
        return None
