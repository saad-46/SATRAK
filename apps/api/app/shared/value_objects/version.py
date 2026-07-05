"""Semantic version value object."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


@total_ordering
@dataclass(frozen=True)
class SemanticVersion(ValueObject):
    """A ``MAJOR.MINOR.PATCH`` version with optional prerelease tag.

    Used for API versions, model checkpoint versions, and document revisions.
    Ordering ignores the prerelease tag beyond core precedence for simplicity.
    """

    major: int
    minor: int
    patch: int
    prerelease: str | None = None

    def __post_init__(self) -> None:
        for name, part in (("major", self.major), ("minor", self.minor), ("patch", self.patch)):
            if part < 0:
                raise ValueValidationError(f"{name} must be >= 0", field=name)

    @classmethod
    def parse(cls, raw: str) -> SemanticVersion:
        match = _SEMVER_RE.match(raw.strip())
        if match is None:
            raise ValueValidationError(f"invalid semantic version: {raw!r}")
        major, minor, patch, prerelease = match.groups()
        return cls(int(major), int(minor), int(patch), prerelease)

    @property
    def core(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __lt__(self, other: SemanticVersion) -> bool:
        return self.core < other.core

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.prerelease}" if self.prerelease else base
