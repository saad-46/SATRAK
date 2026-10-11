"""Smoke test: the scaffold package imports and exposes its placeholder interfaces."""

from py_imagery import AerialProvider, EarthObservationProvider, SatelliteProvider


def test_provider_hierarchy() -> None:
    assert issubclass(SatelliteProvider, EarthObservationProvider)
    assert issubclass(AerialProvider, EarthObservationProvider)
