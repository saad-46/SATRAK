"""Lightweight in-process metrics registry.

A minimal, dependency-free counter registry so the platform exposes basic
operational metrics (request counts, uptime) from day one. It is deliberately
simple; a Prometheus client / OpenTelemetry exporter replaces it at the
infrastructure layer without changing call sites (the registry is the seam).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime


class MetricsRegistry:
    """Thread-unsafe but adequate in-process counters (single event loop)."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self._started_at = datetime.now(UTC)

    def increment(self, name: str, value: int = 1, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        self._counters[key] += value

    @property
    def uptime_seconds(self) -> float:
        return (datetime.now(UTC) - self._started_at).total_seconds()

    def snapshot(self) -> dict[str, object]:
        counters = [
            {"name": name, "labels": dict(labels), "value": value}
            for (name, labels), value in sorted(self._counters.items())
        ]
        return {
            "uptime_seconds": round(self.uptime_seconds, 3),
            "started_at": self._started_at.isoformat(),
            "counters": counters,
        }


# Process-wide registry.
metrics = MetricsRegistry()
