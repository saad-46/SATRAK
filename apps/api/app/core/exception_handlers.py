"""Exception handlers producing RFC 9457 Problem Details responses.

Four layers are handled uniformly into ``application/problem+json``:

* :class:`~app.core.exceptions.AppError` — deliberate application errors.
* :class:`~app.shared.domain.errors.DomainError` — domain-rule violations raised
  deep in the model, mapped to a transport status via ``DOMAIN_ERROR_STATUS``.
* request validation failures — 422 with the field errors attached.
* anything else — a generic 500 that never leaks internals.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import DOMAIN_ERROR_STATUS, AppError
from app.core.problem_details import PROBLEM_CONTENT_TYPE, ProblemDetail
from app.shared.domain.errors import DomainError

logger = structlog.get_logger("api.error")


def _current_request_id() -> str | None:
    return structlog.contextvars.get_contextvars().get("request_id")


def _title_from_code(code: str) -> str:
    return code.replace("_", " ").title()


def _problem_response(problem: ProblemDetail) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error("app_error", code=exc.code, message=exc.message)
    return _problem_response(
        ProblemDetail(
            title=_title_from_code(exc.code),
            status=exc.status_code,
            detail=exc.message,
            instance=request.url.path,
            code=exc.code,
            request_id=_current_request_id(),
            errors=[exc.details] if exc.details else None,
        )
    )


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    status = DOMAIN_ERROR_STATUS.get(exc.code, 422)
    return _problem_response(
        ProblemDetail(
            title=_title_from_code(exc.code),
            status=status,
            detail=exc.message,
            instance=request.url.path,
            code=exc.code,
            request_id=_current_request_id(),
            errors=[exc.details] if exc.details else None,
        )
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _problem_response(
        ProblemDetail(
            title=_title_from_code(f"http_{exc.status_code}"),
            status=exc.status_code,
            detail=str(exc.detail),
            instance=request.url.path,
            code=f"http_{exc.status_code}",
            request_id=_current_request_id(),
        )
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _problem_response(
        ProblemDetail(
            title="Validation Error",
            status=422,
            detail="Request validation failed.",
            instance=request.url.path,
            code="validation_error",
            request_id=_current_request_id(),
            errors=[dict(e) for e in exc.errors()],
        )
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception")
    return _problem_response(
        ProblemDetail(
            title="Internal Server Error",
            status=500,
            detail="An unexpected error occurred.",
            instance=request.url.path,
            code="internal_error",
            request_id=_current_request_id(),
        )
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire all handlers onto the application."""
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
