"""Provider-layer errors.

Infrastructure concerns (bad configuration, malformed provider payloads, unavailable
features) — deliberately *not* domain errors: the domain never sees a provider failure
directly; the application layer decides whether one becomes an ``ImageRejected`` event,
a retry, or an operator alert.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all imagery-provider failures."""

    code: str = "provider_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProviderConfigurationError(ProviderError):
    """A provider was constructed or validated with invalid configuration."""

    code = "provider_configuration_error"


class ProviderDataError(ProviderError):
    """A provider returned a payload that cannot be normalized to canonical metadata."""

    code = "provider_data_error"

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.provider = provider


class ProviderFeatureUnavailable(ProviderError):
    """A requested capability is not available on this provider instance.

    Raised e.g. when ``fetch`` is called before a download transport is attached, or
    ``search`` before a catalogue transport is attached — feature availability is
    discoverable up front via ``ProviderBase.features()``.
    """

    code = "provider_feature_unavailable"

    def __init__(self, message: str, *, feature: str) -> None:
        super().__init__(message)
        self.feature = feature
