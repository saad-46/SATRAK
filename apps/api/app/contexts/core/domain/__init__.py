"""Core domain model — generic reusable entities."""

from app.contexts.core.domain.attachment import Document, FileAttachment
from app.contexts.core.domain.audit import ActivityLog, AuditLog
from app.contexts.core.domain.comment import Comment
from app.contexts.core.domain.configuration import Configuration, SystemSettings
from app.contexts.core.domain.notification import Notification, NotificationStatus
from app.contexts.core.domain.tag import Tag
from app.contexts.core.domain.task import Task, TaskStatus

__all__ = [
    "ActivityLog",
    "AuditLog",
    "Comment",
    "Configuration",
    "Document",
    "FileAttachment",
    "Notification",
    "NotificationStatus",
    "SystemSettings",
    "Tag",
    "Task",
    "TaskStatus",
]
