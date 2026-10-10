"""Classification of every table as jurisdiction-owned or system-global (ADR-0011).

Single source of truth for the startup role check and the policy-coverage test. A new table
must be added to one of the two collections: a table in neither fails the coverage test, so
new business tables default to jurisdiction isolation and a global table needs a reviewed,
reasoned exception here.
"""

from __future__ import annotations

from typing import Final

# Non-null ``jurisdiction_id``; row-level security enabled and forced.
TENANT_TABLES: Final = frozenset({"organization", "role_assignment"})

# System-global tables and why they are exempt from per-jurisdiction row security.
GLOBAL_TABLES: Final[dict[str, str]] = {
    "jurisdiction": "the hierarchy every tenant context is derived from",
    "user_account": "identity, resolved before any jurisdiction context exists",
    "role": "global role catalogue",
    "permission": "global permission catalogue",
    "role_permission": "global role-to-permission mapping",
    "auth_session": "session registry keyed by user, no jurisdiction",
    "audit_event": "global append-only security log (jurisdiction_id is optional, no FK)",
    "alembic_version": "migration bookkeeping",
    "spatial_ref_sys": "PostGIS extension table",
}
