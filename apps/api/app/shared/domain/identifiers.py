"""Entity identity.

SATRAK uses UUIDv4 identifiers everywhere (not serial integers) so ids are
globally unique across shards/services and safe to generate client-side or
before persistence — a requirement for the national-scale, multi-tenant design.
"""

from __future__ import annotations

from uuid import UUID, uuid4

# A type alias today; can become a NewType/branded id per aggregate later without
# changing call sites that import ``EntityId``.
EntityId = UUID


def new_id() -> EntityId:
    """Generate a new random entity identifier."""
    return uuid4()


def parse_id(value: str | UUID) -> EntityId:
    """Coerce a string/UUID into an :data:`EntityId`, raising ``ValueError`` if invalid."""
    return value if isinstance(value, UUID) else UUID(str(value))
