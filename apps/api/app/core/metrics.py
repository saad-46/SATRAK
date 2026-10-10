"""Lightweight in-process metrics registry.

A minimal, dependency-free counter registry so the platform exposes basic
operational metrics (request counts, uptime) from day one. It is deliberately
simple; a Prometheus client / OpenTelemetry exporter replaces it at the
infrastructure layer without changing call sites (the registry is the seam).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

# Hard cap on distinct label sets per metric, so a label fed by untrusted input can never grow
# the registry (or a scraper's time-series count) without bound.
MAX_SERIES_PER_METRIC = 200


class MetricsRegistry:
    """Thread-unsafe but adequate in-process counters (single event loop)."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self._started_at = datetime.now(UTC)
        self._last: dict[str, datetime] = {}

    def increment(self, name: str, value: int = 1, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        if key not in self._counters:
            series = sum(1 for existing, _ in self._counters if existing == name)
            if series >= MAX_SERIES_PER_METRIC:
                key = (name, (("overflow", "true"),))  # one shared bucket past the cap
        self._counters[key] += value

    def mark(self, name: str) -> None:
        """Remember when ``name`` last happened (for "is it degraded right now" alerts)."""
        self._last[name] = datetime.now(UTC)

    def render_prometheus(self) -> str:
        """Prometheus text exposition (version 0.0.4) of every counter and marker."""
        lines = [
            "# TYPE satrak_uptime_seconds gauge",
            f"satrak_uptime_seconds {self.uptime_seconds:.3f}",
        ]
        typed: set[str] = set()
        for (name, labels), value in sorted(self._counters.items()):
            metric = f"satrak_{name}"
            if metric not in typed:
                lines.append(f"# TYPE {metric} counter")
                typed.add(metric)
            rendered = ",".join(f'{k}="{_escape(v)}"' for k, v in labels)
            lines.append(f"{metric}{{{rendered}}} {value}" if rendered else f"{metric} {value}")
        for name, when in sorted(self._last.items()):
            metric = f"satrak_{name}_last_timestamp_seconds"
            lines += [f"# TYPE {metric} gauge", f"{metric} {when.timestamp():.0f}"]
        return "\n".join(lines) + "\n"

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
            "last_events": {name: when.isoformat() for name, when in sorted(self._last.items())},
        }


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# Process-wide registry.
metrics = MetricsRegistry()
