"""RFC 9457 Problem Details.

All error responses are ``application/problem+json`` bodies shaped per RFC 9457,
with two SATRAK extensions: a stable machine-readable ``code`` and the
``request_id`` for support/correlation. Standardizing this means every client
(web, mobile, integrations) handles failures uniformly across every module.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

PROBLEM_CONTENT_TYPE = "application/problem+json"


class ProblemDetail(BaseModel):
    """RFC 9457 problem details object (+ ``code``/``request_id`` extensions)."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    # Extensions:
    code: str | None = None
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None
