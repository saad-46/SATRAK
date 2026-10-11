"""Smoke test: the scaffold package imports and exposes its placeholder interface."""

from py_raster import RasterEngine


def test_raster_engine_is_importable() -> None:
    assert RasterEngine.__name__ == "RasterEngine"
