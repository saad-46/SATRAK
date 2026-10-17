"""ORM tables. Importing this package registers every table on ``Base.metadata``."""

from app.db.models.access import (
    Jurisdiction,
    Organization,
    Permission,
    Role,
    RoleAssignment,
    RolePermission,
    UserAccount,
)
from app.db.models.compliance import (
    BuildingPermitRecord,
    CandidateEvaluation,
    CandidateReview,
    CaseAssignment,
    CaseFinding,
    CaseStateTransition,
    ConstructionChangeCandidate,
    InspectionCase,
    Parcel,
    ParcelGeometryVersion,
    PermitHistory,
    PropertyRecord,
)
from app.db.models.security import AuditEvent, AuthSession

__all__ = [
    "AuditEvent",
    "AuthSession",
    "BuildingPermitRecord",
    "CandidateEvaluation",
    "CandidateReview",
    "CaseAssignment",
    "CaseFinding",
    "CaseStateTransition",
    "ConstructionChangeCandidate",
    "InspectionCase",
    "Jurisdiction",
    "Organization",
    "Parcel",
    "ParcelGeometryVersion",
    "Permission",
    "PermitHistory",
    "PropertyRecord",
    "Role",
    "RoleAssignment",
    "RolePermission",
    "UserAccount",
]
