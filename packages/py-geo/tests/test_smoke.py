"""Smoke test: the scaffold package imports and exposes its placeholder interface."""

from py_geo import CrsTransformer


def test_crs_transformer_is_importable() -> None:
    assert CrsTransformer.__name__ == "CrsTransformer"
