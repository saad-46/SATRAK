"""Background task queue abstraction (port).

Modules enqueue deferred work (image processing, report generation, notification
fan-out) without knowing the executor (Celery/RQ/Arq). :class:`InlineTaskQueue`
runs work immediately in-process — handy for tests and local dev.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class BackgroundTask:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TaskQueue(Protocol):
    async def enqueue(self, task: BackgroundTask) -> None: ...


class InlineTaskQueue:
    """Executes registered handlers synchronously on enqueue. For tests/dev."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[BackgroundTask], Awaitable[None] | None]] = {}
        self.enqueued: list[BackgroundTask] = []

    def register(
        self, name: str, handler: Callable[[BackgroundTask], Awaitable[None] | None]
    ) -> None:
        self._handlers[name] = handler

    async def enqueue(self, task: BackgroundTask) -> None:
        import inspect

        self.enqueued.append(task)
        handler = self._handlers.get(task.name)
        if handler is not None:
            result = handler(task)
            if inspect.isawaitable(result):
                await result
