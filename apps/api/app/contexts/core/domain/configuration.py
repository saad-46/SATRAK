"""Configuration and system-settings entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.shared.domain.entity import Entity
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.identifiers import EntityId


@dataclass(kw_only=True, eq=False)
class Configuration(Entity):
    """A single, scoped configuration key/value (e.g. per-jurisdiction override)."""

    key: str
    value: str
    scope: str = "global"
    scope_id: EntityId | None = None

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.key.strip():
            raise InvariantViolation("configuration key is required")

    def update_value(self, value: str, *, actor: EntityId | None = None) -> None:
        self.value = value
        self.touch(actor=actor)


@dataclass(kw_only=True, eq=False)
class SystemSettings(Entity):
    """A namespaced bag of system settings (one row per namespace)."""

    namespace: str
    values: dict[str, Any] = field(default_factory=dict)

    def _check_invariants(self) -> None:
        super()._check_invariants()
        if not self.namespace.strip():
            raise InvariantViolation("settings namespace is required")

    def set(self, key: str, value: Any, *, actor: EntityId | None = None) -> None:
        self.values[key] = value
        self.touch(actor=actor)
