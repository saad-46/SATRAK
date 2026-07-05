"""Enable PostGIS extension (foundation baseline — no domain tables).

This is the initial migration. It provisions the spatial capability the platform
is built on (PostGIS, plus topology) so that every later migration that adds a
geometry column can rely on it existing. No domain tables are created yet.

Downgrade policy — PostGIS is a non-reversible baseline capability
------------------------------------------------------------------
``downgrade()`` is an intentional no-op. Rationale:

* Dropping the ``postgis`` extension cascades to **every geometry column in the
  database** and to dependent extensions. On the ``postgis/postgis`` image used in
  CI/prod, the entrypoint provisions ``postgis``, ``postgis_topology``,
  ``fuzzystrmatch`` and ``postgis_tiger_geocoder``; ``postgis_tiger_geocoder``
  depends on ``postgis``, so a bare ``DROP EXTENSION postgis`` *errors*, and
  ``DROP ... CASCADE`` would silently destroy spatial data — never acceptable as an
  automated rollback.
* ``CREATE EXTENSION IF NOT EXISTS`` in ``upgrade()`` is idempotent and may adopt an
  extension the platform/DBA already provisioned; a migration must not drop what it
  did not exclusively create.
* Removing the spatial capability is a deliberate, manual DBA operation, not a
  schema-migration rollback.

``alembic downgrade base`` still succeeds — Alembic records the version change
regardless of the (empty) downgrade body — so the CI upgrade/downgrade round-trip
passes without destroying the extension graph.

Revision ID: 0001
Revises:
Create Date: 2026-07-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis_topology;")


def downgrade() -> None:
    # Intentional no-op — see the module docstring "Downgrade policy". PostGIS is a
    # baseline capability the whole platform depends on; dropping it (or its
    # dependent extensions) during a rollback would cascade-destroy every geometry
    # column. Extension removal is a manual DBA action, not an automated migration.
    pass
