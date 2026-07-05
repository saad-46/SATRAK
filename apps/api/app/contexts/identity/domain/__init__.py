"""Identity domain model."""

from app.contexts.identity.domain.permission import Permission
from app.contexts.identity.domain.role import Role
from app.contexts.identity.domain.user_profile import UserProfile

__all__ = ["Permission", "Role", "UserProfile"]
