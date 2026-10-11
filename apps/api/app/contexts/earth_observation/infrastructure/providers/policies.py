"""Retry and rate-limit policy contracts (spec §5.4).

Pure, immutable policy values. They describe *what* a transport must do — the HTTP client
that applies them (backoff sleeps, token buckets) arrives with the download story; nothing
here performs I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.contexts.earth_observation.infrastructure.providers.errors import (
    ProviderConfigurationError,
)


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with an upper bound; optionally full-jitter at runtime.

    ``delay_for_attempt`` returns the *maximum* delay for an attempt; a transport applying
    full jitter draws uniformly from ``[0, delay]`` (AWS-style), which is a runtime concern.
    """

    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 60.0
    full_jitter: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ProviderConfigurationError("max_attempts must be >= 1")
        for name in ("base_delay_seconds", "backoff_multiplier", "max_delay_seconds"):
            value: float = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ProviderConfigurationError(f"{name} must be a finite, positive number")
        if self.backoff_multiplier < 1.0:
            raise ProviderConfigurationError("backoff_multiplier must be >= 1")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ProviderConfigurationError("max_delay_seconds must be >= base_delay_seconds")

    def delay_for_attempt(self, attempt: int) -> float:
        """Upper-bound delay before retry ``attempt`` (1-based first retry)."""
        if attempt < 1:
            raise ProviderConfigurationError("attempt must be >= 1")
        delay = self.base_delay_seconds * self.backoff_multiplier ** (attempt - 1)
        return min(delay, self.max_delay_seconds)

    def is_exhausted(self, attempt: int) -> bool:
        return attempt >= self.max_attempts


@dataclass(frozen=True)
class RateLimitPolicy:
    """Token-bucket parameters for a provider's API quota."""

    requests_per_second: float = 5.0
    burst: int = 10

    def __post_init__(self) -> None:
        if not math.isfinite(self.requests_per_second) or self.requests_per_second <= 0:
            raise ProviderConfigurationError(
                "requests_per_second must be a finite, positive number"
            )
        if self.burst < 1:
            raise ProviderConfigurationError("burst must be >= 1")

    @property
    def min_interval_seconds(self) -> float:
        """The steady-state spacing between requests."""
        return 1.0 / self.requests_per_second
