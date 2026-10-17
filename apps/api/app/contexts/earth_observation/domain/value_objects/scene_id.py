"""Provider scene identity — the deduplication key for a delivered scene."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject


@dataclass(frozen=True)
class ProviderSceneId(ValueObject):
    """A scene's identity at its source: ``(provider, native_id)``.

    This pair is globally unique and is the key used to avoid re-downloading a scene the
    platform already holds (spec §5.6, §13 ``unique(provider, provider_scene_id)``).
    """

    provider: str
    native_id: str

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        native_id = self.native_id.strip()
        if not provider:
            raise ValueValidationError("provider is required", field="provider")
        if not native_id:
            raise ValueValidationError("native_id is required", field="native_id")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "native_id", native_id)

    def __str__(self) -> str:
        return f"{self.provider}:{self.native_id}"
