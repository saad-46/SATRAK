"""Tests for reference implementations of platform services."""

from __future__ import annotations

from datetime import UTC, datetime

from app.shared.services.cache import InMemoryCache
from app.shared.services.clock import FixedClock, SystemClock
from app.shared.services.configuration import DictConfigurationProvider
from app.shared.services.id_generator import Uuid4Generator
from app.shared.services.storage import InMemoryStorageProvider
from app.shared.value_objects.file_reference import FileCategory


class TestClock:
    def test_system_clock_is_utc(self) -> None:
        assert SystemClock().now().tzinfo is not None

    def test_fixed_clock(self) -> None:
        moment = datetime(2026, 7, 5, tzinfo=UTC)
        clock = FixedClock(moment)
        assert clock.now() == moment


def test_uuid_generator_unique() -> None:
    gen = Uuid4Generator()
    assert gen.new_id() != gen.new_id()


class TestInMemoryCache:
    async def test_set_get_delete(self) -> None:
        cache = InMemoryCache()
        await cache.set("k", 42)
        assert await cache.get("k") == 42
        assert await cache.exists("k") is True
        await cache.delete("k")
        assert await cache.get("k") is None


class TestConfiguration:
    def test_settings_and_flags(self) -> None:
        cfg = DictConfigurationProvider(
            settings={"MAX": "5", "DEBUG": "true"},
            feature_flags={"new_ui": True},
        )
        assert cfg.get("MAX") == "5"
        assert cfg.get_bool("DEBUG") is True
        assert cfg.is_feature_enabled("new_ui") is True
        assert cfg.is_feature_enabled("missing") is False


class TestInMemoryStorage:
    async def test_save_open_roundtrip(self) -> None:
        storage = InMemoryStorageProvider()
        ref = await storage.save(
            "cases/1/photo.jpg",
            b"binary-content",
            content_type="image/jpeg",
            filename="photo.jpg",
            category=FileCategory.IMAGE,
        )
        assert ref.size_bytes == len(b"binary-content")
        assert ref.checksum_sha256 is not None
        stored = await storage.open("cases/1/photo.jpg")
        assert stored.data == b"binary-content"
        assert await storage.exists("cases/1/photo.jpg") is True
