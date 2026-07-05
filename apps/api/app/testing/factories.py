"""Test data factories.

Small builder helpers producing valid domain objects with sensible defaults and
keyword overrides, so tests state only what matters to them. Kept dependency-free
(no factory_boy) to stay light; extend per context as their models grow.
"""

from __future__ import annotations

from app.contexts.core.domain.task import Task
from app.contexts.identity.domain.role import Role
from app.contexts.identity.domain.user_profile import UserProfile
from app.contexts.organization.domain.organization import Organization, OrganizationType
from app.shared.value_objects.email import Email


def make_email(value: str = "user@example.com") -> Email:
    return Email(value)


def make_organization(
    *,
    name: str = "Test Municipal Corporation",
    code: str = "TMC",
    type: OrganizationType = OrganizationType.MUNICIPAL_CORPORATION,
) -> Organization:
    return Organization.create(name=name, code=code, type=type)


def make_user_profile(
    *, display_name: str = "Test Officer", email: str = "officer@example.gov"
) -> UserProfile:
    return UserProfile.create(display_name=display_name, email=Email(email))


def make_role(*, name: str = "Officer", code: str = "officer") -> Role:
    return Role.create(name=name, code=code)


def make_task(*, title: str = "Test task") -> Task:
    return Task.create(title=title)
