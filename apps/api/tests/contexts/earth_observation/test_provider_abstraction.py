"""Story 6 — provider abstraction: policies, auth, base, health, features, registry."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from app.contexts.earth_observation.domain.enums import SensorType
from app.contexts.earth_observation.domain.ports.imagery_provider import (
    EarthObservationProvider,
    SceneCandidate,
)
from app.contexts.earth_observation.domain.value_objects import (
    AcquisitionMetadata,
    ProviderCapabilities,
    ProviderSceneId,
)
from app.contexts.earth_observation.infrastructure.providers import (
    ApiKeyAuth,
    AuthStrategy,
    HealthState,
    NoAuth,
    ProviderConfiguration,
    ProviderConfigurationError,
    ProviderError,
    ProviderFeature,
    ProviderFeatureUnavailable,
    ProviderRegistry,
    ProviderRequirements,
    RateLimitPolicy,
    RetryPolicy,
    SatelliteProvider,
    StaticBearerAuth,
)
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange

_AREA = BoundingBox(min_longitude=0.0, min_latitude=0.0, max_longitude=1.0, max_latitude=1.0)
_WINDOW = TimeRange(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 12, 31, tzinfo=UTC))


class _FakeCatalog:
    def __init__(self, items: Sequence[Mapping[str, Any]]) -> None:
        self.items = items
        self.last_query: Mapping[str, Any] | None = None

    async def search_items(
        self, *, area: BoundingBox, window: TimeRange, query: Mapping[str, Any]
    ) -> Sequence[Mapping[str, Any]]:
        self.last_query = query
        return self.items


class _FakeDownloader:
    def stream(self, provider_scene_id: ProviderSceneId) -> AsyncIterator[bytes]:
        async def _gen() -> AsyncIterator[bytes]:
            yield b"chunk-1"
            yield b"chunk-2"

        return _gen()


class _StubProvider(SatelliteProvider):
    """Minimal concrete provider for exercising the base skeleton."""

    min_gsd = 10.0
    tasking = False

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self.name,
            sensor_types=frozenset({SensorType.OPTICAL}),
            supports_tasking=self.tasking,
            min_gsd_m=self.min_gsd,
        )

    def validate_configuration(self) -> None:
        if self.config.extras.get("invalid") == "yes":
            raise ProviderConfigurationError("stub invalidated")

    def search_query(self) -> Mapping[str, Any]:
        return {"collections": ["stub"]}

    def normalize_item(self, item: Mapping[str, Any]) -> SceneCandidate:
        return SceneCandidate(
            provider_scene_id=ProviderSceneId(provider=self.name, native_id=str(item["id"])),
            bounding_box=_AREA,
            acquisition=AcquisitionMetadata(
                acquired_at=datetime(2024, 6, 1, tzinfo=UTC), sensor_type=SensorType.OPTICAL
            ),
        )


def _config(name: str = "stub", **kwargs: Any) -> ProviderConfiguration:
    return ProviderConfiguration(name=name, base_url="https://stub.example", **kwargs)


# --- Policies -----------------------------------------------------------------
def test_retry_policy_backoff_and_cap() -> None:
    policy = RetryPolicy(base_delay_seconds=1.0, backoff_multiplier=2.0, max_delay_seconds=5.0)
    assert policy.delay_for_attempt(1) == 1.0
    assert policy.delay_for_attempt(2) == 2.0
    assert policy.delay_for_attempt(3) == 4.0
    assert policy.delay_for_attempt(4) == 5.0  # capped
    assert policy.is_exhausted(5) is True
    assert policy.is_exhausted(4) is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"base_delay_seconds": 0.0},
        {"backoff_multiplier": 0.5},
        {"max_delay_seconds": 0.5, "base_delay_seconds": 1.0},
    ],
)
def test_retry_policy_invalid(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ProviderConfigurationError):
        RetryPolicy(**kwargs)


def test_retry_policy_rejects_bad_attempt() -> None:
    with pytest.raises(ProviderConfigurationError):
        RetryPolicy().delay_for_attempt(0)


def test_rate_limit_policy() -> None:
    policy = RateLimitPolicy(requests_per_second=4.0, burst=8)
    assert policy.min_interval_seconds == 0.25
    with pytest.raises(ProviderConfigurationError):
        RateLimitPolicy(requests_per_second=0.0)
    with pytest.raises(ProviderConfigurationError):
        RateLimitPolicy(burst=0)


# --- Auth ---------------------------------------------------------------------
async def test_auth_strategies() -> None:
    assert await NoAuth().headers() == {}
    assert await ApiKeyAuth(header_name="X-Api-Key", api_key="k").headers() == {"X-Api-Key": "k"}
    assert await StaticBearerAuth(token="t").headers() == {"Authorization": "Bearer t"}
    assert isinstance(NoAuth(), AuthStrategy)


@pytest.mark.parametrize(
    ("cls", "kwargs"),
    [
        (ApiKeyAuth, {"header_name": " ", "api_key": "k"}),
        (ApiKeyAuth, {"header_name": "X", "api_key": " "}),
        (StaticBearerAuth, {"token": "  "}),
    ],
)
def test_auth_strategies_invalid(cls: type, kwargs: dict[str, str]) -> None:
    with pytest.raises(ProviderConfigurationError):
        cls(**kwargs)


# --- Configuration ---------------------------------------------------------------
@pytest.mark.parametrize(("name", "url"), [("", "https://x"), ("p", "  ")])
def test_provider_configuration_invalid(name: str, url: str) -> None:
    with pytest.raises(ProviderConfigurationError):
        ProviderConfiguration(name=name, base_url=url)


def test_construction_runs_validation() -> None:
    with pytest.raises(ProviderConfigurationError):
        _StubProvider(config=_config(extras={"invalid": "yes"}))


# --- Base: features, health, search, fetch ---------------------------------------
def test_feature_discovery_tracks_wiring() -> None:
    bare = _StubProvider(config=_config())
    assert bare.features() == frozenset()
    wired = _StubProvider(config=_config(), catalog=_FakeCatalog([]), downloader=_FakeDownloader())
    assert wired.features() == {ProviderFeature.SEARCH, ProviderFeature.DOWNLOAD}


def test_tasking_feature_follows_capability() -> None:
    class _Tasking(_StubProvider):
        tasking = True

    assert ProviderFeature.TASKING in _Tasking(config=_config()).features()


def test_health_states() -> None:
    healthy = _StubProvider(config=_config(), catalog=_FakeCatalog([]))
    assert healthy.health().state is HealthState.HEALTHY

    degraded = _StubProvider(config=_config())
    assert degraded.health().state is HealthState.DEGRADED

    disabled = _StubProvider(config=_config(enabled=False), catalog=_FakeCatalog([]))
    assert disabled.health().state is HealthState.UNAVAILABLE

    broken = _StubProvider(config=_config(), catalog=_FakeCatalog([]))
    broken._config = _config(extras={"invalid": "yes"})  # invalidate after construction
    assert broken.health().state is HealthState.UNAVAILABLE


async def test_search_normalizes_via_catalog() -> None:
    catalog = _FakeCatalog([{"id": "a"}, {"id": "b"}])
    provider = _StubProvider(config=_config(), catalog=catalog)
    candidates = await provider.search(area=_AREA, window=_WINDOW)
    assert [c.provider_scene_id.native_id for c in candidates] == ["a", "b"]
    assert catalog.last_query == {"collections": ["stub"]}


async def test_search_without_catalog_raises() -> None:
    provider = _StubProvider(config=_config())
    with pytest.raises(ProviderFeatureUnavailable) as exc:
        await provider.search(area=_AREA, window=_WINDOW)
    assert exc.value.feature == ProviderFeature.SEARCH


async def test_fetch_streams_via_downloader() -> None:
    provider = _StubProvider(config=_config(), downloader=_FakeDownloader())
    psid = ProviderSceneId(provider="stub", native_id="a")
    chunks = [chunk async for chunk in provider.fetch(psid)]
    assert chunks == [b"chunk-1", b"chunk-2"]


def test_fetch_without_downloader_raises() -> None:
    provider = _StubProvider(config=_config())
    with pytest.raises(ProviderFeatureUnavailable):
        provider.fetch(ProviderSceneId(provider="stub", native_id="a"))


def test_base_satisfies_domain_port() -> None:
    provider = _StubProvider(config=_config())
    assert isinstance(provider, EarthObservationProvider)
    assert isinstance(provider.auth, NoAuth)  # defaults to open access


# --- Registry ----------------------------------------------------------------------
def _registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    coarse = _StubProvider(config=_config("coarse"), catalog=_FakeCatalog([]))
    coarse.min_gsd = 30.0

    fine = _StubProvider(config=_config("fine"), catalog=_FakeCatalog([]))
    fine.min_gsd = 0.5

    disabled = _StubProvider(config=_config("disabled", enabled=False))
    registry.register(coarse)
    registry.register(fine)
    registry.register(disabled)
    return registry


def test_registry_register_get_names() -> None:
    registry = _registry()
    assert registry.get("fine").name == "fine"
    assert set(registry.names()) == {"coarse", "fine", "disabled"}
    with pytest.raises(ProviderError):
        registry.register(_StubProvider(config=_config("fine")))
    with pytest.raises(ProviderError):
        registry.get("missing")


def test_registry_resolve_matches_and_sorts_finest_first() -> None:
    matches = _registry().resolve(ProviderRequirements(sensor_type=SensorType.OPTICAL))
    assert [p.name for p in matches] == ["fine", "coarse"]  # disabled excluded


def test_registry_resolve_filters() -> None:
    registry = _registry()
    assert [p.name for p in registry.resolve(ProviderRequirements(max_gsd_m=1.0))] == ["fine"]
    assert registry.resolve(ProviderRequirements(sensor_type=SensorType.SAR)) == ()
    assert registry.resolve(ProviderRequirements(require_tasking=True)) == ()
    assert (
        registry.resolve(
            ProviderRequirements(required_features=frozenset({ProviderFeature.DOWNLOAD}))
        )
        == ()
    )


def test_registry_health_report() -> None:
    report = _registry().health_report()
    assert report["fine"].state is HealthState.HEALTHY
    assert report["disabled"].state is HealthState.UNAVAILABLE
