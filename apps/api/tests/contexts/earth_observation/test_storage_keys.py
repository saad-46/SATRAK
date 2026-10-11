"""Story 9 — storage key strategy and lifecycle policy."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.contexts.earth_observation.domain.enums import AssetTier, SensorType
from app.contexts.earth_observation.domain.value_objects import (
    ProviderSceneId,
    TileCoord,
    TileMatrixSetRef,
)
from app.contexts.earth_observation.infrastructure.storage import (
    LifecycleAction,
    LifecycleRule,
    StorageKeyStrategy,
    StorageLifecyclePolicy,
    default_policy,
    ensure_sha256,
    tier_of,
)
from app.shared.domain.errors import ValueValidationError

_SHA = "ab" * 32
_SCENE_ID = UUID("00000000-0000-0000-0000-000000000abc")
_ACQUIRED = datetime(2024, 6, 1, 5, 32, tzinfo=UTC)
_PSID = ProviderSceneId(provider="sentinel-2", native_id="S2A_MSIL2A_1")
_KEYS = StorageKeyStrategy()


# --- Checksums ------------------------------------------------------------------
def test_ensure_sha256_normalizes_case_and_whitespace() -> None:
    assert ensure_sha256(f"  {_SHA.upper()} ") == _SHA


@pytest.mark.parametrize("bad", ["", "abc", "z" * 64, "ab" * 31])
def test_ensure_sha256_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueValidationError):
        ensure_sha256(bad)


# --- Keys ------------------------------------------------------------------------
def test_raw_key_layout() -> None:
    key = _KEYS.raw_key(
        provider_scene_id=_PSID,
        sensor_type=SensorType.OPTICAL,
        acquired_at=_ACQUIRED,
        checksum_sha256=_SHA,
        extension="zip",
    )
    assert key == f"raw/sentinel-2/optical/2024/06/01/S2A_MSIL2A_1/ab/{_SHA}.zip"
    assert tier_of(key) is AssetTier.RAW


def test_processed_and_cog_keys_share_layout() -> None:
    processed = _KEYS.processed_key(
        provider="sentinel-2",
        sensor_type=SensorType.OPTICAL,
        acquired_at=_ACQUIRED,
        scene_id=_SCENE_ID,
        pipeline_version="1.2.0",
        product="surface",
    )
    assert processed == (f"processed/sentinel-2/optical/2024/06/01/{_SCENE_ID}/v1.2.0/surface.tif")
    assert (
        _KEYS.cog_key(
            provider="sentinel-2",
            sensor_type=SensorType.OPTICAL,
            acquired_at=_ACQUIRED,
            scene_id=_SCENE_ID,
            pipeline_version="1.2.0",
            product="surface",
        )
        == processed
    )


def test_tile_thumbnail_export_temporary_keys() -> None:
    tile = _KEYS.tile_key(
        tile_matrix_set=TileMatrixSetRef.web_mercator_quad(),
        scene_id=_SCENE_ID,
        pipeline_version="1.2.0",
        tile=TileCoord(z=12, x=2933, y=1849),
    )
    assert tile == f"tiles/WebMercatorQuad/{_SCENE_ID}/v1.2.0/12/2933/1849.png"

    assert _KEYS.thumbnail_key(scene_id=_SCENE_ID) == f"thumbnails/{_SCENE_ID}/quicklook.webp"
    assert (
        _KEYS.export_key(request_id=_SCENE_ID, artifact="clip", extension="tif")
        == f"exports/{_SCENE_ID}/clip.tif"
    )
    assert (
        _KEYS.temporary_key(job_id=_SCENE_ID, name="scratch.tif")
        == f"temporary/{_SCENE_ID}/scratch.tif"
    )


def test_archive_key_mirrors_original() -> None:
    raw = _KEYS.raw_key(
        provider_scene_id=_PSID,
        sensor_type=SensorType.OPTICAL,
        acquired_at=_ACQUIRED,
        checksum_sha256=_SHA,
        extension="zip",
    )
    archived = _KEYS.archive_key(original_key=raw)
    assert archived == f"archive/{raw}"
    assert tier_of(archived) is AssetTier.ARCHIVE


def test_archive_rejects_archive_and_temporary() -> None:
    with pytest.raises(ValueValidationError):
        _KEYS.archive_key(original_key="archive/raw/x/y")
    with pytest.raises(ValueValidationError):
        _KEYS.archive_key(original_key=f"temporary/{_SCENE_ID}/scratch")


@pytest.mark.parametrize("bad", ["with space", "a/b", "../etc", "", ".hidden"])
def test_segment_validation_rejects_unsafe_values(bad: str) -> None:
    with pytest.raises(ValueValidationError):
        _KEYS.thumbnail_key(scene_id=_SCENE_ID, variant=bad)


def test_raw_key_rejects_bad_checksum() -> None:
    with pytest.raises(ValueValidationError):
        _KEYS.raw_key(
            provider_scene_id=_PSID,
            sensor_type=SensorType.OPTICAL,
            acquired_at=_ACQUIRED,
            checksum_sha256="nope",
            extension="zip",
        )


@pytest.mark.parametrize("bad", ["noslash", "unknown/prefix/key"])
def test_tier_of_rejects_invalid_keys(bad: str) -> None:
    with pytest.raises(ValueValidationError):
        tier_of(bad)


# --- Lifecycle ---------------------------------------------------------------------
def test_default_policy_actions() -> None:
    policy = default_policy()
    assert policy.action_for(tier=AssetTier.RAW, age_days=10) is LifecycleAction.RETAIN
    assert policy.action_for(tier=AssetTier.RAW, age_days=90) is LifecycleAction.ARCHIVE
    assert policy.action_for(tier=AssetTier.EXPORTS, age_days=7) is LifecycleAction.DELETE
    assert policy.action_for(tier=AssetTier.TEMPORARY, age_days=1) is LifecycleAction.DELETE
    assert policy.action_for(tier=AssetTier.PROCESSED, age_days=9999) is LifecycleAction.RETAIN


def test_delete_dominates_archive() -> None:
    policy = StorageLifecyclePolicy(
        rules=(
            LifecycleRule(tier=AssetTier.RAW, after_days=90, action=LifecycleAction.ARCHIVE),
            LifecycleRule(tier=AssetTier.RAW, after_days=365, action=LifecycleAction.DELETE),
        )
    )
    assert policy.action_for(tier=AssetTier.RAW, age_days=100) is LifecycleAction.ARCHIVE
    assert policy.action_for(tier=AssetTier.RAW, age_days=400) is LifecycleAction.DELETE


def test_lifecycle_validation() -> None:
    with pytest.raises(ValueValidationError):
        LifecycleRule(tier=AssetTier.RAW, after_days=-1, action=LifecycleAction.DELETE)
    with pytest.raises(ValueValidationError):
        LifecycleRule(tier=AssetTier.RAW, after_days=1, action=LifecycleAction.RETAIN)
    with pytest.raises(ValueValidationError):
        LifecycleRule(tier=AssetTier.ARCHIVE, after_days=1, action=LifecycleAction.ARCHIVE)
    rule = LifecycleRule(tier=AssetTier.RAW, after_days=90, action=LifecycleAction.ARCHIVE)
    with pytest.raises(ValueValidationError):
        StorageLifecyclePolicy(rules=(rule, rule))
    with pytest.raises(ValueValidationError):
        default_policy().action_for(tier=AssetTier.RAW, age_days=-5)
