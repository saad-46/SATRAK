"""Identifier generation service."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4


@runtime_checkable
class IdGenerator(Protocol):
    def new_id(self) -> UUID: ...


class Uuid4Generator:
    """Default: random UUIDv4 identifiers."""

    def new_id(self) -> UUID:
        return uuid4()
