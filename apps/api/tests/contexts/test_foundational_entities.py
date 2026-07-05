"""Tests for the foundational domain entities across core/identity/organization."""

from __future__ import annotations

import pytest

from app.contexts.core.domain import (
    Comment,
    Document,
    Notification,
    NotificationStatus,
    Tag,
    Task,
)
from app.contexts.identity.domain import Role, UserProfile
from app.contexts.organization.domain import Organization, OrganizationType
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.events import (
    CommentAdded,
    EntityCreated,
    EntityUpdated,
    FileUploaded,
    NotificationCreated,
    TaskAssigned,
)
from app.shared.domain.identifiers import new_id
from app.shared.services.notification import NotificationChannel
from app.shared.value_objects.email import Email
from app.shared.value_objects.file_reference import FileCategory, FileReference


def _file() -> FileReference:
    return FileReference(
        storage_key="k", content_type="application/pdf", size_bytes=10, filename="a.pdf"
    )


class TestOrganization:
    def test_create_records_event(self) -> None:
        org = Organization.create(
            name="BBMP", code="BBMP", type=OrganizationType.MUNICIPAL_CORPORATION
        )
        events = org.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], EntityCreated)
        assert org.version == 1

    def test_rename_bumps_version_and_records_update(self) -> None:
        org = Organization.create(name="A", code="A")
        org.pull_events()
        org.rename("B")
        assert org.name == "B"
        assert org.version == 2
        assert isinstance(org.pull_events()[0], EntityUpdated)

    def test_blank_name_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            Organization(name="  ", code="X")


class TestIdentity:
    def test_role_grant_revoke(self) -> None:
        role = Role.create(name="Officer", code="officer")
        perm = new_id()
        role.grant(perm)
        assert role.has_permission(perm)
        role.revoke(perm)
        assert not role.has_permission(perm)

    def test_user_profile_assign_role(self) -> None:
        profile = UserProfile.create(display_name="Asha", email=Email("asha@gov.in"))
        assert isinstance(profile.pull_events()[0], EntityCreated)
        role_id = new_id()
        profile.assign_role(role_id)
        assert role_id in profile.role_ids


class TestCoreEntities:
    def test_task_assign_event(self) -> None:
        task = Task.create(title="Inspect parcel 42")
        task.pull_events()
        assignee = new_id()
        task.assign(assignee)
        event = task.pull_events()[0]
        assert isinstance(event, TaskAssigned)
        assert task.assignee_id == assignee

    def test_document_create_events(self) -> None:
        doc = Document.create(title="Notice", file=_file(), category=FileCategory.PDF)
        events = doc.pull_events()
        assert any(isinstance(e, EntityCreated) for e in events)
        assert any(isinstance(e, FileUploaded) for e in events)

    def test_notification_lifecycle(self) -> None:
        n = Notification.create(
            recipient_id=new_id(),
            channel=NotificationChannel.EMAIL,
            subject="Hi",
            body="Body",
        )
        assert isinstance(n.pull_events()[0], NotificationCreated)
        n.mark_sent()
        assert n.status is NotificationStatus.SENT

    def test_comment_event(self) -> None:
        c = Comment.create(
            subject_type="Case", subject_id=new_id(), author_id=new_id(), body="Looks off"
        )
        assert isinstance(c.pull_events()[0], CommentAdded)

    def test_tag_invalid_slug(self) -> None:
        with pytest.raises(InvariantViolation):
            Tag(label="Water Body", slug="Water Body")
