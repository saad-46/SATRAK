# py-geo (scaffold)

Shared **geospatial support** package — the single boundary for coordinate-reference-system
transforms (national projected CRS ↔ WGS84), so no service hand-rolls a `pyproj` call
(Blueprint Part 5, spec §9).

**Status — Epic 3 Story 1:** scaffold only. Contains the package structure, a **placeholder
interface** (`CrsTransformer`), and a tests folder. **No implementation yet** — the concrete
transformer lands in a later Earth Observation story. Consumed by the `earth_observation`
context and reusable by any other context (e.g. `drone`) without cross-context imports
(ADR-0010).

## Structure

```
py-geo/
├── pyproject.toml
├── src/py_geo/
│   ├── __init__.py
│   └── interfaces.py   # CrsTransformer (Protocol, placeholder)
└── tests/
    └── test_smoke.py
```

Not yet wired into CI (packages gain their own lint/type/test jobs when they get real
implementations).
