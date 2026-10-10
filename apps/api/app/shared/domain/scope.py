"""Access scopes for repository operations (ADR-0011).

Every jurisdiction-owned repository query carries a scope, and the scope has no default:
omitting it is a type error, so a caller can never fall through to "all tenants" by
forgetting a filter. ``TenantScope`` matches only the listed jurisdictions (an empty set
matches nothing). The explicit all-tenants scope lives in ``app.shared.domain.system_scope``
and is kept out of the web layer by an import-linter contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.shared.domain.identifiers import EntityId

_PERMITTED_MODULES = frozenset({__name__, "app.shared.domain.system_scope"})


class AccessScope(ABC):
    """Decides whether rows of a given jurisdiction are in reach.

    Sealed: only the scope types defined in this package may subclass it, so a new,
    permissive scope cannot appear in request-handling code without changing this module.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__module__ not in _PERMITTED_MODULES:
            raise TypeError(f"{cls.__qualname__}: AccessScope is sealed")

    @abstractmethod
    def allows(self, jurisdiction_id: EntityId | None) -> bool: ...


@dataclass(frozen=True, slots=True)
class TenantScope(AccessScope):
    """Rows of the listed jurisdictions only; default deny for anything else."""

    jurisdiction_ids: frozenset[EntityId]

    def allows(self, jurisdiction_id: EntityId | None) -> bool:
        return jurisdiction_id is not None and jurisdiction_id in self.jurisdiction_ids
