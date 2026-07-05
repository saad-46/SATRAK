"""Structured logging configuration.

Uses ``structlog`` with a shared processor chain that renders either
developer-friendly console output or machine-parseable JSON, selected by
``SATRAK_API_LOG_FORMAT``. ``request_id`` / ``correlation_id`` are bound into a
context-local so every log line emitted while handling a request carries them
without each call site having to pass them explicitly.
"""

from __future__ import annotations

import logging
import sys
from typing import cast

import structlog

from app.core.config import Settings

# Context-local variables bound per request by RequestContextMiddleware and
# merged into every log entry automatically.
request_id_var = structlog.contextvars.bind_contextvars
merge_contextvars = structlog.contextvars.merge_contextvars


def configure_logging(settings: Settings) -> None:
    """Configure stdlib logging + structlog once at application startup."""
    log_level = getattr(logging, settings.log_level, logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy) through the same handler so the
    # output stream is uniform.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).handlers.clear()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))
