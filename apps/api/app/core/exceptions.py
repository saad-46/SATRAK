"""Domain-agnostic application exception hierarchy.

Every error the API deliberately raises derives from :class:`AppError`, carrying a
stable machine-readable ``code``, a human message, and the HTTP status it maps to.
This keeps handlers (see ``exception_handlers.py``) simple and lets the frontend
pattern-match on ``code`` rather than parsing message strings.

No domain-specific errors are defined here — only the reusable base types the
foundation provides. Bounded contexts add their own subclasses later.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all deliberate application errors."""

    code: str = "internal_error"
    message: str = "An unexpected error occurred."
    status_code: int = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    code = "not_found"
    message = "The requested resource was not found."
    status_code = 404


class ConflictError(AppError):
    code = "conflict"
    message = "The request conflicts with the current state of the resource."
    status_code = 409


class ValidationError(AppError):
    code = "validation_error"
    message = "The request failed validation."
    status_code = 422


class UnauthorizedError(AppError):
    code = "unauthorized"
    message = "Authentication is required."
    status_code = 401


class ForbiddenError(AppError):
    code = "forbidden"
    message = "You do not have permission to perform this action."
    status_code = 403


class ServiceUnavailableError(AppError):
    code = "service_unavailable"
    message = "A required dependency is currently unavailable."
    status_code = 503
