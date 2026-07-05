"""Tag entity — a reusable label attachable to any subject."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.shared.domain.entity import Entity
from app.shared.domain.errors import InvariantViolation

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(kw_only=True, eq=False)
class Tag(Entity):
    label: str
    slug: str
    color: str | None = None

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.label.strip():
            raise InvariantViolation("tag label is required")
        if not _SLUG_RE.match(self.slug):
            raise InvariantViolation(f"invalid tag slug: {self.slug!r}")
