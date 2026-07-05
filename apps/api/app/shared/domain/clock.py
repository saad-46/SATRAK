"""Timestamp helper for the domain layer.

Entities default their audit timestamps via :func:`utcnow`. This is a thin,
dependency-free helper; application code that needs *injectable* time (for
deterministic tests) uses the :class:`~app.shared.services.clock.Clock` service
instead. Both agree on timezone-aware UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``."""
    return datetime.now(UTC)
