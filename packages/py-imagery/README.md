# py-imagery (scaffold)

Shared **imagery-provider abstractions** — the capability-driven extension mechanism for
imagery sources (ADR-0007). Establishes the provider hierarchy:

```
EarthObservationProvider
 ├── SatelliteProvider   (Sentinel, Landsat, Planet, Maxar, Airbus, Cartosat, Bhuvan, ...)
 └── AerialProvider      (manned airborne / aerial orthophoto)
```

**Drone/UAV imagery is deliberately excluded** — it belongs to the `drone` bounded context
(ADR-0010).

**Status — Epic 3 Story 1:** scaffold only. Contains the package structure, **placeholder
interfaces** (the abstract hierarchy above, with no methods declared to avoid locking
signatures prematurely), and a tests folder. **No providers implemented** — concrete
providers arrive in the provider stories (spec §5).

## Structure

```
py-imagery/
├── pyproject.toml
├── src/py_imagery/
│   ├── __init__.py
│   └── interfaces.py   # EarthObservationProvider / SatelliteProvider / AerialProvider (placeholder)
└── tests/
    └── test_smoke.py
```

Not yet wired into CI.
