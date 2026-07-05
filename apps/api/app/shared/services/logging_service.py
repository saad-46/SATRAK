"""Logging abstraction.

A thin port so domain/application code can obtain a structured logger without
importing structlog directly (keeping the dependency at the edges). The default
implementation delegates to the app's structlog configuration.
"""

from __future__ import annotations

from typing import Any, Protocol, cast, runtime_checkable


@runtime_checkable
class Logger(Protocol):
    def info(self, event: str, **kwargs: Any) -> None: ...

    def warning(self, event: str, **kwargs: Any) -> None: ...

    def error(self, event: str, **kwargs: Any) -> None: ...


@runtime_checkable
class LoggerFactory(Protocol):
    def get_logger(self, name: str) -> Logger: ...


class StructlogLoggerFactory:
    """Returns structlog bound loggers (see app.core.logging)."""

    def get_logger(self, name: str) -> Logger:
        import structlog

        return cast("Logger", structlog.get_logger(name))
