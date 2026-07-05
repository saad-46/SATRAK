"""Enable PostGIS extension (foundation baseline — no domain tables).

This is the initial migration. It provisions the spatial capability the platform
is built on (PostGIS, plus topology) so that every later migration that adds a
geometry column can rely on it existing. No domain tables are created yet.

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
    op.execute("DROP EXTENSION IF EXISTS postgis_topology;")
    op.execute("DROP EXTENSION IF EXISTS postgis;")
