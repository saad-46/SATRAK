"""Test-only reset of tenant data, run as the table owner.

The compliance history tables reject TRUNCATE for every role (they are append-only), and the
access-control fixtures truncate with ``CASCADE``, which reaches them through their foreign keys.
A fixture reset therefore disables the user triggers of those tables inside one transaction and
re-enables them before it commits. The production guarantee is unchanged: no application role
owns the tables or holds TRUNCATE, and ``tests/db/test_compliance_schema.py`` proves the triggers
reject the change once the reset has finished.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

APPEND_ONLY = (
    "parcel_geometry_version",
    "permit_history",
    "candidate_review",
    "candidate_evaluation",
    "case_state_transition",
    "case_assignment",
    "case_finding",
)


async def truncate_cascade(conn: AsyncConnection, tables: str) -> None:
    for table in APPEND_ONLY:
        await conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
    await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    for table in APPEND_ONLY:
        await conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
