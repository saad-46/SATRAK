"""Organization domain model."""

from app.contexts.organization.domain.department import Department
from app.contexts.organization.domain.organization import Organization, OrganizationType

__all__ = ["Department", "Organization", "OrganizationType"]
