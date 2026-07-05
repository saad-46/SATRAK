"""Exception handlers producing a single, consistent error envelope.

All error responses share the shape::

    {"error": {"code": "...", "message": "...", "details": {...},
               "request_id": "..."}}

so clients handle failures uniformly regardless of origin (deliberate AppError,
request-validation failure, or an unhandled crash).
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError

logger = structlog.get_logger("api.error")


def _current_request_id() -> str | None:
    return structlog.contextvars.get_contextvars().get("request_id")


def _envelope(
    code: str, message: str, status_code: int, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": _current_request_id(),
            }
        },
    )


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error("app_error", code=exc.code, message=exc.message)
    return _envelope(exc.code, exc.message, exc.status_code, exc.details)


async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _envelope(
        code=f"http_{exc.status_code}",
        message=str(exc.detail),
        status_code=exc.status_code,
    )


async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return _envelope(
        code="validation_error",
        message="Request validation failed.",
        status_code=422,
        details={"errors": exc.errors()},
    )


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    # Never leak internals: log the full trace, return a generic message.
    logger.exception("unhandled_exception")
    return _envelope(
        code="internal_error",
        message="An unexpected error occurred.",
        status_code=500,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire all handlers onto the application."""
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
