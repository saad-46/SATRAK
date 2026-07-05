"""Search index abstraction (port).

A generic full-text/geo search port so modules can index and query documents
without binding to a specific engine (OpenSearch/Elasticsearch/pgvector). Interface
only in Epic 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchDocument:
    id: str
    index: str
    body: dict[str, Any]


@dataclass(frozen=True)
class SearchHit:
    id: str
    score: float
    source: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SearchIndex(Protocol):
    async def index_document(self, document: SearchDocument) -> None: ...

    async def delete_document(self, index: str, document_id: str) -> None: ...

    async def search(
        self, index: str, query: str, *, limit: int = 20
    ) -> list[SearchHit]: ...
